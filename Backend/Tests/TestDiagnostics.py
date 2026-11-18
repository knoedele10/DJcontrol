"""M8 诊断、控制器切换和设置持久化回归。"""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from Database import Database, SettingsRepository
from Main import create_app
from Player.Service import PlayerService
from PptControl import PptState
from PptControl.Service import PptService


class FakePptController:
    """只提供诊断路由需要的 PPT 状态，不连接真实 Office。"""

    def __init__(self, app: str) -> None:
        self.state = PptState(app=app, connected=True)
        self.closed = False

    def get_state(self) -> PptState:
        return self.state

    def export_slide(self, slide: int, width: int = 1280, document_id: str | None = None) -> bytes:
        return b"\x89PNG\r\n\x1a\n"

    def next(self) -> None:
        return None

    def previous(self) -> None:
        return None

    def goto_slide(self, slide: int) -> None:
        return None

    def set_black(self, enabled: bool) -> None:
        return None

    def start(self, slide: int | None = None) -> None:
        return None

    def stop(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class DiagnosticsServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_diagnostics_and_controller_setting_survive_service_restart(self) -> None:
        database = Database(":memory:", seed=False)
        database.connect()
        service = PlayerService(database, controller_name="mock", poll_interval=0.02)
        await service.start()
        try:
            result = await service.diagnostics()
            self.assertEqual(result["controller"], "mock")
            self.assertIn("running", result["kugou"])
            self.assertTrue(result["capabilities"])

            await service.switch_controller("mock")
            self.assertEqual(SettingsRepository(database).get("player.controller"), "mock")
        finally:
            await service.close()

        restarted = PlayerService(
            database,
            controller_name=SettingsRepository(database).get("player.controller", "mock"),
            poll_interval=0.02,
        )
        await restarted.start()
        try:
            self.assertEqual((await restarted.refresh())["state"]["controller"], "mock")
        finally:
            await restarted.close()
            database.close()


class DiagnosticsApiTests(unittest.TestCase):
    def test_diagnostics_refresh_and_controller_setting_routes(self) -> None:
        database = Database(":memory:")
        ppt = PptService(factory=lambda app: FakePptController(app), poll_interval=0.02)
        player = PlayerService(database, controller_name="mock", poll_interval=0.02)
        with TestClient(create_app(ppt, database, player)) as client:
            response = client.get("/api/diagnostics")
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["controller"], "mock")
            self.assertEqual(body["ppt"], {"app": "powerpoint", "connected": True})
            self.assertTrue(body["capabilities"])
            self.assertIn("version", body["kugou"])

            refreshed = client.post("/api/diagnostics/refresh")
            self.assertEqual(refreshed.status_code, 200)
            self.assertEqual(refreshed.json()["controller"], "mock")

            switched = client.put("/api/settings/controller", json={"name": "mock"})
            self.assertEqual(switched.status_code, 200)
            self.assertEqual(switched.json()["controller"], "mock")
            self.assertEqual(SettingsRepository(database).get("player.controller"), "mock")

            invalid = client.put("/api/settings/controller", json={"name": "other"})
            self.assertEqual(invalid.status_code, 422)

    def test_tutorial_progress_is_saved_in_backend_settings(self) -> None:
        database = Database(":memory:")
        ppt = PptService(factory=lambda app: FakePptController(app), poll_interval=0.02)
        player = PlayerService(database, controller_name="mock", poll_interval=0.02)
        with TestClient(create_app(ppt, database, player)) as client:
            self.assertEqual(client.get("/api/settings/tutorial").json(), {"completed_version": 0})

            saved = client.put("/api/settings/tutorial", json={"completed_version": 1})
            self.assertEqual(saved.status_code, 200)
            self.assertEqual(saved.json(), {"completed_version": 1})
            self.assertEqual(client.get("/api/settings/tutorial").json(), {"completed_version": 1})
            self.assertEqual(SettingsRepository(database).get("ui.tutorial_version"), 1)

            for body in ({"completed_version": -1}, {"completed_version": "1"}, {"completed_version": True},
                         {"completed_version": 1, "extra": 1}, {}):
                self.assertEqual(client.put("/api/settings/tutorial", json=body).status_code, 422, body)

            SettingsRepository(database).set("ui.tutorial_version", "坏数据")
            self.assertEqual(client.get("/api/settings/tutorial").json(), {"completed_version": 0})


if __name__ == "__main__":
    unittest.main()
