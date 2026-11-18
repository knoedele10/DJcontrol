"""M1 SQLite 数据层测试；真实软件不参与，文件库测试使用工作区临时目录。"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from Database import (
    Database,
    LibraryRepository,
    PptBindingRepository,
    QueueRepository,
    SessionRepository,
    SettingsRepository,
    SongRepository,
)


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = Database(":memory:")
        self.database.connect()

    def tearDown(self) -> None:
        self.database.close()

    def test_migrations_are_recorded_and_idempotent(self) -> None:
        self.assertEqual(self.database.query_one("SELECT COUNT(*) FROM schema_migrations")[0], 2)
        self.database._migrate(self.database.connection)
        self.assertEqual(self.database.query_one("SELECT COUNT(*) FROM schema_migrations")[0], 2)
        tables = {
            row[0]
            for row in self.database.query_all(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertTrue({"songs", "event_groups", "categories", "category_songs", "queue_items", "sessions", "history", "ppt_bindings", "settings"} <= tables)

    def test_seed_matches_frontend_library_and_groups(self) -> None:
        self.assertEqual(self.database.query_one("SELECT COUNT(*) FROM songs")[0], 28)
        self.assertEqual(self.database.query_one("SELECT COUNT(*) FROM event_groups")[0], 2)
        self.assertEqual(self.database.query_one("SELECT COUNT(*) FROM categories")[0], 8)
        self.assertEqual(self.database.query_one("SELECT COUNT(*) FROM category_songs")[0], 33)
        song = self.database.query_one("SELECT title, artist, bpm, duration FROM songs WHERE id = 1")
        self.assertEqual(tuple(song), ("晴天", "周杰伦", 69, 269))
        groups = LibraryRepository(self.database).list_groups()
        self.assertEqual(groups[0]["categories"][0]["song_ids"], [0, 1, 2, 3, 4])
        self.assertEqual(groups[1]["categories"][1]["song_ids"], [20, 21, 23, 9, 27])

    def test_empty_database_can_skip_seed_data(self) -> None:
        empty = Database(":memory:", seed=False)
        try:
            empty.connect()
            self.assertEqual(empty.query_one("SELECT COUNT(*) FROM songs")[0], 0)
        finally:
            empty.close()

    def test_file_database_enables_foreign_keys_wal_and_reopens_idempotently(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd(), ignore_cleanup_errors=True) as directory:
            path = Path(directory) / "dashboard.db"
            database = Database(path, seed=False)
            try:
                connection = database.connection
                self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
                self.assertEqual(database.query_one("SELECT COUNT(*) FROM schema_migrations")[0], 2)
            finally:
                database.close()

            reopened = Database(path, seed=False)
            try:
                self.assertEqual(reopened.query_one("SELECT COUNT(*) FROM schema_migrations")[0], 2)
                self.assertEqual(reopened.query_one("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'songs'")[0], 1)
            finally:
                reopened.close()

    def test_seed_does_not_overwrite_existing_rows_after_reopen(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd(), ignore_cleanup_errors=True) as directory:
            path = Path(directory) / "seeded.db"
            first = Database(path)
            try:
                SongRepository(first).create("用户歌曲", "用户歌手", duration=123)
                self.assertEqual(first.query_one("SELECT COUNT(*) FROM songs")[0], 29)
            finally:
                first.close()

            second = Database(path)
            try:
                self.assertEqual(second.query_one("SELECT COUNT(*) FROM songs")[0], 29)
                self.assertEqual(SongRepository(second).get(28)["title"], "用户歌曲")
            finally:
                second.close()

    def test_category_replacement_is_ordered_and_atomic(self) -> None:
        database = Database(":memory:", seed=False)
        try:
            songs = SongRepository(database)
            ids = [songs.create(f"歌曲{i}", "歌手", duration=i)["id"] for i in range(3)]
            library = LibraryRepository(database)
            group = library.create_group("排序组", "#ffffff")
            category = library.create_category(group["id"], "排序类", "#000000", song_ids=ids)
            library.replace_category_songs(category["id"], [ids[2], ids[0]])
            actual = next(item for item in library.list_groups()[0]["categories"] if item["id"] == category["id"])
            self.assertEqual(actual["song_ids"], [ids[2], ids[0]])

            with self.assertRaises(sqlite3.IntegrityError):
                library.replace_category_songs(category["id"], [ids[0], 999999])
            actual = next(item for item in library.list_groups()[0]["categories"] if item["id"] == category["id"])
            self.assertEqual(actual["song_ids"], [ids[2], ids[0]])
        finally:
            database.close()

    def test_schema_constraints_are_enforced(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.database.execute(
                "INSERT INTO category_songs (category_id, song_id, position) VALUES (?, ?, ?)",
                ("missing-category", 1, 0),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.database.execute(
                "INSERT INTO songs (title, artist, duration, source, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("", "歌手", 1, "library", "now", "now"),
            )

    def test_foreign_keys_remove_memberships_queue_and_clear_binding_song(self) -> None:
        songs = SongRepository(self.database)
        song = songs.create("测试歌曲", "测试歌手", duration=120)
        library = LibraryRepository(self.database)
        group = library.create_group("测试组", "#ffffff")
        category = library.create_category(group["id"], "测试分类", "#000000", song_ids=[song["id"]])
        QueueRepository(self.database).add(song["id"])
        PptBindingRepository(self.database).set("powerpoint", "demo.pptx", 1, song["id"])

        self.assertEqual(self.database.query_one("SELECT COUNT(*) FROM category_songs WHERE song_id = ?", (song["id"],))[0], 1)
        self.assertTrue(songs.delete(song["id"]))
        self.assertEqual(self.database.query_one("SELECT COUNT(*) FROM category_songs WHERE song_id = ?", (song["id"],))[0], 0)
        self.assertEqual(self.database.query_one("SELECT COUNT(*) FROM queue_items WHERE song_id = ?", (song["id"],))[0], 0)
        self.assertIsNone(PptBindingRepository(self.database).get("powerpoint", "demo.pptx", 1)["song_id"])
        self.assertEqual(category["song_ids"], [song["id"]])

    def test_queue_insert_shifts_positions_without_unique_conflict(self) -> None:
        queue = QueueRepository(self.database)
        first = queue.add(0)
        third = queue.add(2)
        middle = queue.add(1, position=1)
        self.assertEqual([item["id"] for item in queue.list_items()], [first["id"], middle["id"], third["id"]])
        self.assertTrue(queue.delete(middle["id"]))
        self.assertEqual([item["position"] for item in queue.list_items()], [0, 1])

    def test_sessions_history_settings_and_binding_repositories(self) -> None:
        sessions = SessionRepository(self.database)
        current = sessions.start(session_id="session-1", started_at="2026-11-07T19:00:00+08:00")
        sessions.add_history(current["id"], song_id=1, title="晴天", artist="周杰伦", played_at="2026-11-07T19:01:00+08:00")
        self.assertEqual(sessions.current()["id"], "session-1")
        self.assertEqual(sessions.list_history("session-1")[0]["song_id"], 1)
        self.assertTrue(sessions.end_current(ended_at="2026-11-07T20:00:00+08:00"))
        self.assertIsNone(sessions.current())

        settings = SettingsRepository(self.database)
        settings.set("feature_flags", {"link_music": True})
        self.assertEqual(settings.get("feature_flags"), {"link_music": True})
        self.assertEqual(settings.get("missing", "fallback"), "fallback")

        bindings = PptBindingRepository(self.database)
        binding = bindings.set("wps", "show.pptx", 2, 1)
        self.assertEqual(binding["song_id"], 1)
        self.assertEqual(bindings.set("wps", "show.pptx", 2, None)["song_id"], None)


if __name__ == "__main__":
    unittest.main()
