"""M3 模拟控制器和持久化队列回归；不依赖 FastAPI 生命周期。"""

import asyncio
import time
import unittest

from Player.Base import PlayerController
from Player.Mock import MockPlayerController
from Database import Database, LibraryRepository, QueueRepository, SongRepository
from Player.Model import PlayerCommand
from Player.Service import PlayerConflict, PlayerService, PlayerUnsupported


class MockPlayerTests(unittest.TestCase):
    def test_real_time_progress_pause_seek_and_end(self) -> None:
        controller = MockPlayerController()
        song = {"id": 1, "title": "测试", "artist": "歌手", "duration": 1}
        controller.play_track(song)
        time.sleep(0.02)
        first = controller.get_state()
        self.assertEqual(first.status, "playing")
        self.assertGreater(first.position or 0, 0)
        controller.toggle()
        paused = controller.get_state()
        self.assertEqual(paused.status, "paused")
        controller.seek(0.8)
        self.assertAlmostEqual(controller.get_state().position or 0, 0.8, delta=0.05)
        controller.toggle()
        controller.seek(0.2)
        self.assertEqual(controller.get_state().status, "playing")
        time.sleep(0.85)
        self.assertEqual(controller.get_state().status, "stopped")

    def test_capabilities_are_all_verified_for_mock(self) -> None:
        capabilities = {cap["name"]: cap for cap in MockPlayerController().capabilities()}
        self.assertTrue(capabilities["read_state"]["supported"])
        self.assertTrue(all(cap["verified"] for cap in capabilities.values()))


class QueueRepositoryM3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = Database(":memory:", seed=False)
        self.database.connect()
        self.songs = SongRepository(self.database)
        self.queue = QueueRepository(self.database)
        self.song_ids = [self.songs.create(f"歌{i}", "歌手", duration=100)["id"] for i in range(3)]

    def tearDown(self) -> None:
        self.database.close()

    def test_enqueue_moves_existing_song_without_duplicate(self) -> None:
        self.queue.enqueue(self.song_ids[0])
        self.queue.enqueue(self.song_ids[1])
        moved = self.queue.enqueue(self.song_ids[0], position=0)
        self.assertEqual(moved["position"], 0)
        rows = self.queue.list_items()
        self.assertEqual([row["song_id"] for row in rows], [self.song_ids[0], self.song_ids[1]])
        self.assertEqual(len(rows), 2)

    def test_order_requires_all_ids_and_clear(self) -> None:
        first = self.queue.enqueue(self.song_ids[0])
        second = self.queue.enqueue(self.song_ids[1])
        self.queue.order([second["id"], first["id"]])
        self.assertEqual([row["id"] for row in self.queue.list_items()], [second["id"], first["id"]])
        with self.assertRaises(ValueError):
            self.queue.order([first["id"]])
        self.queue.clear()
        self.assertEqual(self.queue.list_items(), [])


class PositionUniquenessTests(unittest.TestCase):
    """position 有唯一约束：删除、移动、重排都不能因为原地挪位置而撞约束。"""

    def setUp(self) -> None:
        self.database = Database(":memory:", seed=False)
        self.database.connect()
        self.queue = QueueRepository(self.database)
        songs = SongRepository(self.database)
        self.song_ids = [songs.create(f"歌{i}", "歌手", duration=100)["id"] for i in range(6)]

    def tearDown(self) -> None:
        self.database.close()

    def _fill(self, count: int, *, reordered: bool) -> list[str]:
        """返回按队列顺序排列的队列项 ID。

        reordered=True 时先整体倒序：行的物理顺序与 position 顺序相反。旧实现的原地
        `position - 1` 只有在这种情况下才会撞唯一约束（真实使用中重排、插到下一首后就是这样）。
        """

        self.queue.clear()
        ids = [self.queue.enqueue(song_id)["id"] for song_id in self.song_ids[:count]]
        if reordered:
            ids.reverse()
            self.queue.order(ids)
        return ids

    def _positions(self) -> list[int]:
        return [row["position"] for row in self.queue.list_items()]

    def test_delete_any_item_keeps_order_and_contiguous_positions(self) -> None:
        for reordered in (False, True):
            for count in range(1, 7):
                for index in range(count):
                    with self.subTest(reordered=reordered, count=count, index=index):
                        ids = self._fill(count, reordered=reordered)
                        self.assertTrue(self.queue.delete(ids[index]))
                        self.assertEqual([row["id"] for row in self.queue.list_items()], ids[:index] + ids[index + 1:])
                        self.assertEqual(self._positions(), list(range(count - 1)))

    def test_move_any_existing_song_to_front_or_end(self) -> None:
        for reordered in (False, True):
            for count in range(2, 7):
                for index in range(count):
                    for front in (True, False):
                        with self.subTest(reordered=reordered, count=count, index=index, front=front):
                            ids = self._fill(count, reordered=reordered)
                            order = [row["song_id"] for row in self.queue.list_items()]
                            song_id = order[index]
                            self.queue.enqueue(song_id, position=0 if front else None)
                            others = [s for s in order if s != song_id]
                            expected = [song_id] + others if front else others + [song_id]
                            self.assertEqual([row["song_id"] for row in self.queue.list_items()], expected)
                            self.assertEqual(self._positions(), list(range(count)))
                            self.assertIn(self.queue.list_items()[0 if front else -1]["id"], ids)

    def test_order_works_when_positions_have_gaps(self) -> None:
        ids = self._fill(4, reordered=False)
        # 删除歌曲会级联删掉队列项并留下空位；这里直接制造稀疏位置。
        self.database.execute("UPDATE queue_items SET position = position * 10")
        self.assertEqual(self._positions(), [0, 10, 20, 30])
        self.queue.order(list(reversed(ids)))
        self.assertEqual([row["id"] for row in self.queue.list_items()], list(reversed(ids)))
        self.assertEqual(self._positions(), [0, 1, 2, 3])

    def test_remove_middle_song_from_category(self) -> None:
        library = LibraryRepository(self.database)
        group = library.create_group("组", "#ffffff")
        category = library.create_category(group["id"], "类", "#000000", song_ids=self.song_ids[:5])
        # 把分类内顺序倒过来，但不动物理行顺序：复现旧实现会撞约束的情况
        self.database.execute(
            "UPDATE category_songs SET position = position + 100 WHERE category_id = ?", (category["id"],)
        )
        self.database.execute(
            "UPDATE category_songs SET position = 104 - position WHERE category_id = ?", (category["id"],)
        )
        self.assertEqual(
            next(c for c in library.list_groups()[0]["categories"] if c["id"] == category["id"])["song_ids"],
            list(reversed(self.song_ids[:5])),
        )
        for song_id in (self.song_ids[3], self.song_ids[2], self.song_ids[4]):
            self.assertTrue(library.remove_song(category["id"], song_id))
        actual = next(c for c in library.list_groups()[0]["categories"] if c["id"] == category["id"])
        self.assertEqual(actual["song_ids"], [self.song_ids[1], self.song_ids[0]])


class NoSeekController(MockPlayerController):
    seek = PlayerController.seek  # 回到基类：不支持 seek


class PlayerServiceBehaviourTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.database = Database(":memory:", seed=False)
        self.database.connect()
        songs = SongRepository(self.database)
        # 1 秒的歌，方便验证播完后的行为
        self.a, self.b, self.c = (songs.create(t, "歌手", duration=1)["id"] for t in ("A", "B", "C"))
        self.service = PlayerService(self.database, poll_interval=0.05)
        await self.service.start()

    async def asyncTearDown(self) -> None:
        await self.service.close()
        self.database.close()

    async def _state(self) -> dict:
        return (await self.service.refresh())["state"]

    async def _wait(self, predicate, timeout: float = 2.5) -> dict:
        deadline = time.monotonic() + timeout
        state = await self._state()
        while time.monotonic() < deadline and not predicate(state):
            await asyncio.sleep(0.05)
            state = await self._state()
        return state

    async def test_auto_next_plays_queue_head_when_song_ends(self) -> None:
        await self.service.enqueue(self.b, "end")
        await self.service.command(PlayerCommand(action="play", song_id=self.a))
        state = await self._wait(lambda s: s["song_id"] == self.b and s["status"] == "playing")
        self.assertEqual((state["song_id"], state["status"]), (self.b, "playing"))
        self.assertEqual([h["song_id"] for h in state["recent_history"]], [self.b, self.a])

    async def test_song_added_after_queue_ran_dry_does_not_start_by_itself(self) -> None:
        await self.service.command(PlayerCommand(action="play", song_id=self.a))
        await self._wait(lambda s: s["status"] == "stopped")
        await asyncio.sleep(0.2)
        await self.service.enqueue(self.b, "end")
        await asyncio.sleep(0.4)
        state = await self._state()
        self.assertEqual((state["song_id"], state["status"]), (self.a, "stopped"))
        self.assertEqual([q["song_id"] for q in state["queue"]], [self.b])

    async def test_auto_next_off_stops_at_end_and_setting_is_persisted(self) -> None:
        await self.service.set_auto_next(False)
        await self.service.enqueue(self.b, "end")
        await self.service.command(PlayerCommand(action="play", song_id=self.a))
        await self._wait(lambda s: s["status"] == "stopped")
        await asyncio.sleep(0.3)
        state = await self._state()
        self.assertEqual((state["song_id"], state["status"]), (self.a, "stopped"))
        # 之后再打开自动接歌，也不会把早就播完的那首当成刚播完
        await self.service.set_auto_next(True)
        await asyncio.sleep(0.3)
        self.assertEqual((await self._state())["song_id"], self.a)

        restarted = PlayerService(self.database, poll_interval=0.05)
        await self.service.set_auto_next(False)
        await restarted.start()
        try:
            self.assertFalse((await restarted.refresh())["state"]["auto_next"])
        finally:
            await restarted.close()

    async def test_previous_walks_back_without_bouncing_or_rewriting_history(self) -> None:
        for song_id in (self.a, self.b, self.c):
            await self.service.command(PlayerCommand(action="play", song_id=song_id))
        state = (await self.service.command(PlayerCommand(action="previous")))["state"]
        self.assertEqual(state["song_id"], self.b)
        state = (await self.service.command(PlayerCommand(action="previous")))["state"]
        self.assertEqual(state["song_id"], self.a)
        with self.assertRaises(PlayerConflict):
            await self.service.command(PlayerCommand(action="previous"))
        self.assertEqual([h["song_id"] for h in (await self._state())["recent_history"]], [self.c, self.b, self.a])
        # 正常播放后，"上一首"重新从最新一条往回数，并跳过正在播的这首之前的同名记录
        await self.service.command(PlayerCommand(action="play", song_id=self.c))
        state = (await self.service.command(PlayerCommand(action="previous")))["state"]
        self.assertEqual(state["song_id"], self.b)

    async def test_unsupported_capability_uses_contract_code(self) -> None:
        service = PlayerService(self.database, factory=NoSeekController, poll_interval=0.05)
        await service.start()
        try:
            await service.command(PlayerCommand(action="play", song_id=self.a))
            with self.assertRaises(PlayerUnsupported) as caught:
                await service.command(PlayerCommand(action="seek", position=0.5))
            self.assertEqual(caught.exception.code, "capability_unsupported")
        finally:
            await service.close()


if __name__ == "__main__":
    unittest.main()
