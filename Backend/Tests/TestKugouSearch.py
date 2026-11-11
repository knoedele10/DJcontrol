"""酷狗搜索与收录；不访问网络。"""

import asyncio
import json
import time
import unittest
from unittest.mock import patch

from Database import Database, SongRepository
from KugouControl import Search
from Library.Api import search as search_route
from Library.Service import KugouUnavailable, LibraryNotFound, LibraryService
import Library.Service as ServiceModule


class FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


class KugouSearchClientTests(unittest.TestCase):
    def test_results_are_cleaned_and_kept_in_kugou_order(self):
        payload = {"status": 1, "data": {"info": [
            {"songname": "<em>晴天</em>", "singername": "周杰伦", "duration": 269},
            {"songname": "Unchanged Mind【大家还在搜 : unchangedmind】", "singername": "Valentin", "duration": "307"},
            {"songname": "", "singername": "没有歌名"},
            {"songname": "无时长", "singername": None},
        ]}}
        seen = {}

        def opener(request, timeout):
            seen["url"], seen["timeout"] = request.full_url, timeout
            return FakeResponse(json.dumps(payload).encode())

        with patch.object(Search.urllib.request, "urlopen", opener):
            results = Search.search("晴天 周杰伦", limit=3, timeout=2)
        self.assertEqual(results, [
            {"title": "晴天", "artist": "周杰伦", "duration": 269},
            {"title": "Unchanged Mind", "artist": "Valentin", "duration": 307},
            {"title": "无时长", "artist": "", "duration": 0},
        ])
        self.assertIn("keyword=%E6%99%B4%E5%A4%A9+%E5%91%A8%E6%9D%B0%E4%BC%A6", seen["url"])
        self.assertEqual(seen["timeout"], 2)

    def test_any_failure_becomes_one_clear_error(self):
        def offline(request, timeout):
            raise OSError("断网")

        for opener in (offline, lambda r, timeout: FakeResponse(b"<html>"),
                       lambda r, timeout: FakeResponse(b'{"status": 0}'), lambda r, timeout: FakeResponse(b"[]")):
            with patch.object(Search.urllib.request, "urlopen", opener), self.assertRaises(Search.KugouSearchFailed):
                Search.search("歌")


class KugouSearchServiceTests(unittest.TestCase):
    def run_with(self, searcher, scenario):
        async def main():
            db = Database(":memory:", seed=False); db.connect()
            service = LibraryService(db, kugou_search=searcher)
            try:
                return await scenario(service, db)
            finally:
                await service.close(); db.close()
        return asyncio.run(main())

    def test_results_skip_library_songs_and_can_be_collected(self):
        calls = []

        def searcher(query, limit):
            calls.append((query, limit))
            return [{"title": "晴天", "artist": "周杰伦", "duration": 269},
                    {"title": "晴天", "artist": "刘瑞琦", "duration": 250},
                    {"title": "晴天", "artist": "刘瑞琦", "duration": 251},
                    {"title": "稻香", "artist": "周杰伦", "duration": 223}]

        async def scenario(service, db):
            SongRepository(db).create("晴天", "周杰伦", duration=269)
            results, available = await service.search_kugou("  晴天 ", 30)
            self.assertTrue(available)
            self.assertEqual(calls, [("晴天", 30)])
            self.assertEqual([(r["title"], r["artist"], r["duration"], r["bpm"]) for r in results],
                             [("晴天", "刘瑞琦", 250, None), ("稻香", "周杰伦", 223, None)])
            self.assertEqual(len({r["key"] for r in results}), 2)
            events = service.subscribe(); events.get_nowait()
            song = await service.import_kugou(results[1]["key"])
            self.assertEqual((song["title"], song["artist"], song["duration"], song["source"]), ("稻香", "周杰伦", 223, "kugou"))
            self.assertEqual(events.get_nowait()["scope"], "songs")
            # 再收一次同一条：用已有的那首，不重复建。
            self.assertEqual((await service.import_kugou(results[1]["key"]))["id"], song["id"])
            self.assertEqual(len(SongRepository(db).list()), 2)
            # 收进曲库后，再搜就不出现在酷狗结果里。
            again, _ = await service.search_kugou("晴天", 30)
            self.assertEqual([r["artist"] for r in again], ["刘瑞琦"])
            self.assertEqual(await service.search_kugou("   ", 30), ([], True))
            self.assertEqual(len(calls), 1)  # 同一个词 10 分钟内只查一次网络
            with self.assertRaisesRegex(LibraryNotFound, "过期"):
                await service.import_kugou("kg-unknown")
            later = time.monotonic() + ServiceModule.KUGOU_KEY_TTL + 1
            with patch.object(ServiceModule.time, "monotonic", lambda: later), self.assertRaisesRegex(LibraryNotFound, "过期"):
                await service.import_kugou(results[0]["key"])
        self.run_with(searcher, scenario)

    def test_failure_timeout_and_disabled_only_lose_kugou_results(self):
        def broken(query, limit):
            raise Search.KugouSearchFailed("断网")

        def slow(query, limit):
            time.sleep(0.3)
            return [{"title": "歌", "artist": "人", "duration": 1}]

        async def check(service, db):
            SongRepository(db).create("歌曲", "歌手")
            with patch.object(ServiceModule, "KUGOU_SEARCH_WAIT", 0.05), self.assertLogs(ServiceModule.logger, "WARNING"):
                self.assertEqual(await service.search_kugou("歌", 30), ([], False))
            self.assertEqual(len(await service.search("歌", 30)), 1)
        self.run_with(broken, check)
        self.run_with(slow, check)

        async def disabled(service, db):
            self.assertEqual(await service.search_kugou("歌", 30), ([], False))
            with self.assertRaises(KugouUnavailable):
                await service.import_kugou("kg-any")
        self.run_with(None, disabled)

    def test_search_route_returns_both_lists(self):
        async def scenario(service, db):
            SongRepository(db).create("晴天", "周杰伦")
            request = type("R", (), {"app": type("A", (), {"state": type("S", (), {"library": service})()})()})()
            body = await search_route(request, q="晴天", limit=30, source="all")
            self.assertEqual((body["query"], body["kugou_available"]), ("晴天", True))
            self.assertEqual([s["title"] for s in body["library"]], ["晴天"])
            self.assertEqual([(r["title"], r["artist"]) for r in body["kugou"]], [("晴天", "刘瑞琦")])
            local = await search_route(request, q="晴天", limit=30, source="library")
            self.assertEqual((len(local["library"]), local["kugou"], local["kugou_available"]), (1, [], False))
            remote = await search_route(request, q="晴天", limit=30, source="kugou")
            self.assertEqual((remote["library"], len(remote["kugou"]), remote["kugou_available"]), ([], 1, True))
        self.run_with(lambda q, limit: [{"title": "晴天", "artist": "周杰伦", "duration": 1},
                                        {"title": "晴天", "artist": "刘瑞琦", "duration": 2}], scenario)


if __name__ == "__main__":
    unittest.main()
