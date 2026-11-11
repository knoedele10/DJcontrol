"""PPT 页面绑定与翻页联动：绑定存后端，翻页只触发一次播放。"""

import asyncio
import time
import unittest
from dataclasses import replace

from fastapi.testclient import TestClient

from Database import Database, PptBindingRepository, SongRepository
from Main import create_app
from PptControl import PptCommandError, PptUnavailable
from PptControl.Link import PptLink
from PptControl.Model import PptCommand
from PptControl.Service import PptService
from Tests.TestPpt import FakeController


class PptLinkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database(":memory:", seed=False)
        self.db.connect()
        self.first = SongRepository(self.db).create("入场", "乐队")["id"]
        self.second = SongRepository(self.db).create("颁奖", "乐队")["id"]
        self.controllers = []

        def factory(app):
            controller = FakeController(app)
            self.controllers.append(controller)
            return controller

        self.played, self.playing, self.failure, self.delay = [], None, None, 0.0

        async def play(song_id):
            if self.playing == song_id:
                return False
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.failure:
                raise self.failure
            self.played.append(song_id)
            self.playing = song_id
            return True

        self.service = PptService(factory=factory, poll_interval=0.01)
        self.link = PptLink(self.db, self.service, play)
        await self.service.start()

    async def asyncTearDown(self):
        await self.link.close()
        await self.service.close()
        self.db.close()

    @property
    def ppt(self):
        return self.controllers[-1]

    async def settle(self, seconds=0.08):
        await asyncio.sleep(seconds)

    async def flip(self, slide):
        """模拟翻页笔：直接改 PPT 的实际页码，不经过面板。"""

        self.ppt.state = replace(self.ppt.state, current_slide=slide)
        await self.settle()

    async def test_turning_to_a_bound_page_plays_its_song_once(self):
        watchers = [self.service.subscribe(), self.service.subscribe()]  # 两个面板窗口
        update = await self.link.bind(3, self.first)
        self.assertEqual((update["bindings"], update["link_music"], update["link"]), ({"3": self.first}, True, None))
        self.assertEqual(self.played, [])  # 绑定本身不播放
        await self.flip(2)
        self.assertEqual(self.played, [])  # 没绑歌的页
        await self.flip(3)
        self.assertEqual(self.played, [self.first])
        for queue in watchers:
            latest = queue.get_nowait()
            self.assertEqual(latest["link"]["status"], "played")
            self.assertEqual((latest["link"]["slide"], latest["link"]["song_id"]), (3, self.first))
        # 面板翻页走同一条路；翻走再翻回来时这首还在播，不重播。
        await self.service.command(PptCommand(action="goto", slide=4))
        await self.service.command(PptCommand(action="goto", slide=3))
        await self.settle()
        self.assertEqual(self.played, [self.first])

    async def test_no_playback_without_a_real_page_turn(self):
        await self.link.bind(1, self.first)
        await self.link.bind(2, self.first)
        await self.link.bind(3, self.second)
        # 没在放映：翻页不播。
        self.ppt.state = replace(self.ppt.state, running=False)
        await self.settle()
        await self.flip(2)
        # 关掉联动：不播；开关存进数据库。
        self.ppt.state = replace(self.ppt.state, running=True)
        self.assertFalse((await self.link.set_link_music(False))["link_music"])
        await self.flip(3)
        self.assertEqual(self.played, [])
        self.assertFalse(PptLink(self.db, PptService(factory=lambda app: None), lambda song: None).link_music)
        await self.link.set_link_music(True)
        # 软件退出后重新连上，页码和断开前不同：这不是翻页。
        self.ppt.state = replace(self.ppt.state, connected=False)
        await self.settle()
        self.assertFalse(self.service.state.connected)
        self.ppt.state = replace(self.ppt.state, connected=True, current_slide=1)
        await self.settle()
        # 换了一份文稿：也不是翻页，绑定按新文稿读取。
        self.ppt.state = replace(self.ppt.state, document_id="D:/other.pptx", current_slide=2)
        await self.settle()
        self.assertEqual(self.service.snapshot()["bindings"], {})
        self.assertEqual(self.played, [])
        await self.flip(3)
        self.assertEqual(self.played, [])  # 新文稿这一页没绑歌

    async def test_fast_flipping_only_plays_where_it_stops_and_failures_are_reported(self):
        await self.link.bind(2, self.first)
        await self.link.bind(3, self.second)
        await self.link.bind(4, self.first)
        self.delay = 0.4
        await self.flip(2)   # 开始播第一首（要 0.4 秒）
        await self.flip(3)   # 还没播出来又翻了两页
        await self.flip(4)
        await self.settle(1.0)
        self.assertEqual(self.played, [self.first])  # 第 3 页被跳过；第 4 页的歌和正在播的是同一首
        self.assertEqual(self.service.snapshot()["link"]["slide"], 2)
        self.delay, self.failure = 0, RuntimeError("酷狗还在连接「颁奖 乐队」")
        seq = self.service.snapshot()["link"]["seq"]
        await self.flip(3)
        link = self.service.snapshot()["link"]
        self.assertEqual((link["status"], link["slide"], link["song_id"]), ("failed", 3, self.second))
        self.assertIn("还在连接", link["message"])
        self.assertGreater(link["seq"], seq)

    async def test_binding_rules_and_one_time_import(self):
        with self.assertRaisesRegex(PptCommandError, "超出"):
            await self.link.bind(5, self.first)
        with self.assertRaisesRegex(PptCommandError, "不存在"):
            await self.link.bind(1, 999)
        await self.link.bind(1, self.first)
        self.assertEqual((await self.link.bind(1, None))["bindings"], {})
        # 歌被删掉：绑定跟着清空，翻到那一页不播。
        await self.link.bind(2, self.second)
        SongRepository(self.db).delete(self.second)
        await self.flip(2)
        self.assertEqual(self.played, [])
        self.assertEqual(self.service.snapshot()["bindings"], {})
        # 导入浏览器里的旧绑定：已有记录的页不覆盖，歌不存在、格式不对的跳过。
        await self.link.bind(3, self.first)
        result = await self.link.import_bindings({
            "powerpoint:D:/show.pptx": {"3": 999, "4": self.first, "1": None, "x": self.first, "0": self.first},
            "wps:D:/b.dps": {"2": self.first, "5": 999},
            "keynote:x": {"1": self.first}, "broken": {"1": self.first},
        })
        self.assertEqual(result["imported"], 2)
        self.assertEqual(result["bindings"], {"3": self.first, "4": self.first})
        self.assertEqual(PptBindingRepository(self.db).list("wps", "D:/b.dps"), {2: self.first})
        self.assertEqual((await self.link.import_bindings({"powerpoint:D:/show.pptx": {"4": self.first}}))["imported"], 0)
        # 没有打开文稿时不能绑定。
        self.ppt.state = replace(self.ppt.state, connected=False)
        await self.settle()
        with self.assertRaises(PptUnavailable):
            await self.link.bind(1, self.first)


class PptLinkApiTests(unittest.TestCase):
    def test_two_panels_one_playback(self):
        controllers = []

        def factory(app):
            controllers.append(FakeController(app))
            return controllers[-1]

        database = Database(":memory:", seed=False)
        database.connect()
        song = SongRepository(database).create("入场", "乐队", duration=200)["id"]
        with TestClient(create_app(PptService(factory=factory, poll_interval=0.01), database)) as client:
            self.assertEqual(client.put("/api/ppt/bindings/3", json={"song_id": song}).json()["bindings"], {"3": song})
            self.assertEqual(client.put("/api/ppt/bindings/9", json={"song_id": song}).status_code, 409)
            self.assertEqual(client.put("/api/ppt/bindings/0", json={"song_id": song}).status_code, 422)
            self.assertEqual(client.put("/api/ppt/bindings/3", json={"song": song}).status_code, 422)
            self.assertEqual(client.patch("/api/ppt/settings", json={"link_music": "yes"}).status_code, 422)
            self.assertTrue(client.patch("/api/ppt/settings", json={"link_music": True}).json()["link_music"])
            self.assertEqual(client.post("/api/ppt/bindings/import", json={"bindings": {}}).json()["imported"], 0)
            with client.websocket_connect("/ws/ppt") as one, client.websocket_connect("/ws/ppt") as two:
                self.assertEqual(one.receive_json()["bindings"], {"3": song})
                self.assertEqual(two.receive_json()["bindings"], {"3": song})
                self.assertEqual(client.post("/api/ppt/command", json={"action": "goto", "slide": 3}).status_code, 200)
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    state = client.get("/api/player/state").json()["state"]
                    if state["song_id"] == song:
                        break
                    time.sleep(0.05)
                self.assertEqual((state["song_id"], state["status"]), (song, "playing"))
                history = client.get("/api/history").json()
                self.assertEqual([row["song_id"] for row in history], [song])  # 两个窗口开着，只播了一次


if __name__ == "__main__":
    unittest.main()
