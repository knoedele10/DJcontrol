"""PPT 协议、线程归属和 HTTP/WebSocket 回归；无需启动 Office。"""

import asyncio
import threading
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient

from PptControl import (
    PowerPointController, PptCommandError, PptState, PptUnavailable, WpsController,
)
from Database import Database
from Main import create_app
from PptControl.Model import PptCommand
from PptControl.Service import PptService


class Collection:
    def __init__(self, items=()):
        self.items = list(items)

    @property
    def Count(self):
        return len(self.items)

    def Item(self, index):
        return self.items[index - 1]


class FakeView:
    def __init__(self, app, running=False):
        self.app = app
        self.State = 1
        self.CurrentShowPosition = 1  # 自定义放映顺序与真实页码可以不同。
        self.running = running

    @property
    def Slide(self):
        return SimpleNamespace(SlideIndex=self.app.slide)

    def GotoSlide(self, slide):
        self.app.slide = slide

    def Exit(self):
        self.app.SlideShowWindows.items.clear()


class FakeApplication:
    def __init__(self):
        self.slide = 2
        self.Path = "C:/Program Files/Microsoft Office/root/Office16"
        self.document = SimpleNamespace(
            Name="演出.pptx", FullName="D:\\演出.pptx",
            Slides=SimpleNamespace(Count=4),
            SlideShowSettings=SimpleNamespace(Run=self.run_show),
        )
        self.ActivePresentation = self.document
        self.Presentations = Collection([self.document])
        self.SlideShowWindows = Collection()
        self.ActiveWindow = SimpleNamespace(View=FakeView(self))

    def run_show(self):
        window = SimpleNamespace(Presentation=self.document, View=FakeView(self, True))
        self.SlideShowWindows.items.append(window)
        return window


class ComControllerTests(unittest.TestCase):
    def controllers(self):
        for cls in (PowerPointController, WpsController):
            application = FakeApplication()
            controller = cls()
            controller._pythoncom = Mock()
            controller._client = Mock()
            controller._application = application
            yield controller, application

    def test_both_adapters_control_editing_and_slideshow(self):
        for controller, application in self.controllers():
            with self.subTest(app=controller.app):
                self.assertEqual(controller.get_state().current_slide, 2)
                controller.next()
                self.assertEqual(application.slide, 3)
                controller.previous()
                controller.goto_slide(4)
                controller.start()
                self.assertTrue(controller.get_state().running)
                self.assertEqual(controller.get_state().current_slide, 4)
                controller.start()  # 不重复创建放映窗口。
                self.assertEqual(application.SlideShowWindows.Count, 1)
                controller.set_black(True)
                self.assertTrue(controller.get_state().black)
                controller.previous()
                self.assertFalse(controller.get_state().black)
                controller.set_black(True)
                controller.set_black(False)
                controller.stop()
                controller.stop()
                self.assertFalse(controller.get_state().running)

    def test_external_pen_changes_and_document_index(self):
        for controller, application in self.controllers():
            with self.subTest(app=controller.app):
                application.run_show()
                application.slide = 3
                self.assertEqual(controller.get_state().current_slide, 3)
                application.SlideShowWindows.Item(1).View.State = 3
                self.assertTrue(controller.get_state().black)
                application.SlideShowWindows.items.clear()
                self.assertFalse(controller.get_state().running)

    def test_show_document_takes_priority_over_active_editor(self):
        for controller, application in self.controllers():
            application.run_show()
            application.ActivePresentation = SimpleNamespace(Name="其他文稿.pptx")
            self.assertEqual(controller.get_state().file, "演出.pptx")

    def test_invalid_commands_do_not_change_page(self):
        for controller, application in self.controllers():
            with self.subTest(app=controller.app):
                for slide in (0, 5, True, 1.5):
                    with self.assertRaises(PptCommandError):
                        controller.goto_slide(slide)
                with self.assertRaises(PptCommandError):
                    controller.start(5)
                self.assertEqual(application.SlideShowWindows.Count, 0)
                self.assertEqual(application.slide, 2)
                with self.assertRaises(PptCommandError):
                    controller.set_black(True)
                controller.goto_slide(1)
                with self.assertRaises(PptCommandError):
                    controller.previous()
                controller.goto_slide(4)
                with self.assertRaises(PptCommandError):
                    controller.next()
                self.assertEqual(application.slide, 4)

    def test_no_document_or_single_selected_slide(self):
        for controller, application in self.controllers():
            application.ActiveWindow = None
            self.assertIsNone(controller.get_state().current_slide)
            with self.assertRaises(PptCommandError):
                controller.next()
            application.Presentations.items.clear()
            state = controller.get_state()
            self.assertTrue(state.connected)
            self.assertEqual(state.total_slides, 0)
            with self.assertRaises(PptCommandError):
                controller.start()

    def test_wps_progid_fallback_and_cleanup_never_quits_office(self):
        controller = WpsController()
        application = FakeApplication()
        controller._pythoncom = pythoncom = Mock()
        controller._client = client = Mock()
        client.GetActiveObject.side_effect = [OSError(), application]
        self.assertTrue(controller.get_state().connected)
        self.assertEqual([c.args[0] for c in client.GetActiveObject.call_args_list],
                         ["KWPP.Application", "WPP.Application"])
        controller.close()
        pythoncom.CoUninitialize.assert_called_once()
        client.Dispatch.assert_not_called()

    def test_unavailable_can_reconnect_without_replaying_commands(self):
        controller = PowerPointController()
        controller._pythoncom = Mock()
        controller._client = Mock()
        controller._client.GetActiveObject.side_effect = OSError()
        with self.assertRaises(PptUnavailable):
            controller.get_state()
        application = FakeApplication()
        controller._client.GetActiveObject.side_effect = None
        controller._client.GetActiveObject.return_value = application
        self.assertEqual(controller.get_state().current_slide, 2)

    def test_wps_closed_show_with_stale_count_stays_connected(self):
        controller = WpsController()
        application = FakeApplication()
        controller._application = application
        controller._pythoncom = Mock()
        error = Exception("E_BOUNDS")
        error.excepinfo = (0, None, None, None, 0, -2147483637)
        application.SlideShowWindows = SimpleNamespace(Count=1, Item=Mock(side_effect=error))
        state = controller.get_state()
        self.assertTrue(state.connected)
        self.assertFalse(state.running)
        self.assertEqual(state.current_slide, 2)
        # 不吞掉软件忙碌等不相关错误。
        application.SlideShowWindows.Item.side_effect = OSError("RPC failure")
        with self.assertRaises(PptUnavailable):
            controller.get_state()


    def test_powerpoint_rejects_wps_compatibility_alias(self):
        controller = PowerPointController()
        controller._pythoncom = Mock()
        controller._client = Mock()
        application = FakeApplication()
        application.Path = "C:\\Users\\test\\Kingsoft\\WPS Office\\office6"
        controller._client.GetActiveObject.return_value = application
        with self.assertRaisesRegex(PptUnavailable, "WPS"):
            controller.get_state()
        self.assertIsNone(controller._application)


class FakeController:
    def __init__(self, app):
        self.app = app
        self.owner = threading.get_ident()
        self.closed = False
        self.state = PptState(
            app=app, connected=True, document_id="D:/show.pptx", file="show.pptx",
            current_slide=1, total_slides=4, running=True,
        )

    def check_thread(self):
        assert threading.get_ident() == self.owner, "COM 跨线程访问"

    def get_state(self):
        self.check_thread()
        if not self.state.connected:
            raise PptUnavailable("软件已退出")
        return self.state

    def goto_slide(self, slide):
        self.get_state()
        if not 1 <= slide <= 4:
            raise PptCommandError("页码越界")
        self.state = replace(self.state, current_slide=slide)

    def next(self):
        self.goto_slide(self.state.current_slide + 1)

    def previous(self):
        self.goto_slide(self.state.current_slide - 1)

    def start(self, slide=None):
        self.get_state()
        self.state = replace(self.state, running=True)
        if slide is not None:
            self.goto_slide(slide)

    def stop(self):
        self.get_state()
        self.state = replace(self.state, running=False, black=False)

    def set_black(self, enabled):
        self.get_state()
        self.state = replace(self.state, black=enabled)

    def close(self):
        self.check_thread()
        self.closed = True


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.controllers = []

        def factory(app):
            controller = FakeController(app)
            self.controllers.append(controller)
            return controller

        self.service = PptService(factory=factory, poll_interval=0.01)
        await self.service.start()

    async def asyncTearDown(self):
        await self.service.close()
        self.assertTrue(all(c.closed for c in self.controllers))

    async def test_external_change_is_published_without_any_panel_command(self):
        queue = self.service.subscribe()
        await queue.get()
        self.controllers[0].state = replace(self.controllers[0].state, current_slide=3)
        update = await asyncio.wait_for(queue.get(), timeout=1)
        self.assertEqual(update["state"]["current_slide"], 3)
        self.service.unsubscribe(queue)

    async def test_slow_subscriber_gets_latest_and_unchanged_state_is_deduplicated(self):
        queue = self.service.subscribe()
        await self.service.command(PptCommand(action="goto", slide=2))
        await self.service.command(PptCommand(action="goto", slide=4))
        update = await queue.get()
        self.assertEqual(update["state"]["current_slide"], 4)
        await self.service.refresh()
        self.assertEqual(self.service.snapshot()["revision"], update["revision"])
        self.assertTrue(queue.empty())
        self.service.unsubscribe(queue)

    async def test_switching_closes_old_controller_in_owner_thread(self):
        await asyncio.gather(self.service.refresh(), self.service.connect("wps"))
        self.assertEqual(self.service.state.app, "wps")
        self.assertTrue(self.controllers[0].closed)
        self.assertNotEqual(self.controllers[0].owner, threading.get_ident())

    async def test_failed_command_preserves_actual_state(self):
        with self.assertRaises(PptCommandError):
            await self.service.command(PptCommand(action="previous"))
        self.assertEqual(self.service.state.current_slide, 1)
        self.controllers[0].state = replace(self.controllers[0].state, connected=False)
        await self.service.refresh()
        self.assertFalse(self.service.state.connected)
        self.assertIsNone(self.service.state.current_slide)
        self.assertFalse(self.service.state.running)


class ApiTests(unittest.TestCase):
    def app(self):
        return create_app(self.service(), Database(":memory:"))

    def service(self):
        self.controllers = []

        def factory(app):
            controller = FakeController(app)
            self.controllers.append(controller)
            return controller

        return PptService(factory=factory, poll_interval=0.01)

    def test_commands_and_websocket_external_changes(self):
        with TestClient(self.app()) as client:
            self.assertEqual(client.get("/api/health").status_code, 200)
            self.assertEqual(client.get("/api/ppt/state").json()["state"]["current_slide"], 1)
            with client.websocket_connect("/ws/ppt") as socket:
                self.assertEqual(socket.receive_json()["state"]["current_slide"], 1)
                self.controllers[0].state = replace(self.controllers[0].state, current_slide=3)
                self.assertEqual(socket.receive_json()["state"]["current_slide"], 3)
                for body, field, expected in (
                    ({"action": "previous"}, "current_slide", 2),
                    ({"action": "next"}, "current_slide", 3),
                    ({"action": "goto", "slide": 4}, "current_slide", 4),
                    ({"action": "black", "enabled": True}, "black", True),
                    ({"action": "stop"}, "running", False),
                    ({"action": "start", "slide": 2}, "current_slide", 2),
                ):
                    response = client.post("/api/ppt/command", json=body)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["state"][field], expected)
                    self.assertEqual(socket.receive_json()["state"][field], expected)
            response = client.post("/api/ppt/connect", json={"app": "wps"})
            self.assertEqual(response.json()["state"]["app"], "wps")

    def test_validation_and_error_contract(self):
        with TestClient(self.app()) as client:
            for body in (
                {"action": "goto"}, {"action": "goto", "slide": 0},
                {"action": "goto", "slide": True}, {"action": "goto", "slide": "2"},
                {"action": "black"}, {"action": "black", "enabled": "false"},
                {"action": "next", "enabled": False}, {"action": "stop", "slide": 2},
                {"action": "bogus"}, {"action": "next", "extra": 1},
            ):
                self.assertEqual(client.post("/api/ppt/command", json=body).status_code, 422)
            self.assertEqual(client.post("/api/ppt/connect", json={"app": "other"}).status_code, 422)
            response = client.post("/api/ppt/command", json={"action": "previous"})
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["detail"]["code"], "ppt_command_failed")
            self.controllers[0].state = replace(self.controllers[0].state, connected=False)
            response = client.post("/api/ppt/command", json={"action": "black", "enabled": True})
            self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
