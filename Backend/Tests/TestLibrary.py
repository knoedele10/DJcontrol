"""M2 曲库、活动组和分类仓储回归；不依赖 FastAPI 或真实软件。"""

import sqlite3
import unittest

from Database import Database, LibraryRepository, SongRepository


class LibraryRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = Database(":memory:", seed=False)
        self.database.connect()
        self.songs = SongRepository(self.database)
        self.library = LibraryRepository(self.database)

    def tearDown(self) -> None:
        self.database.close()

    def test_group_and_category_crud_preserves_order_and_cascade(self) -> None:
        first = self.library.create_group("第一组", "#111111", group_id="g-first")
        second = self.library.create_group("第二组", "#222222", group_id="g-second")
        category = self.library.create_category(first["id"], "开场", "#333333", category_id="c-open")
        self.library.create_category(first["id"], "高潮", "#444444", category_id="c-high")
        self.assertEqual([item["id"] for item in self.library.list_groups()], ["g-first", "g-second"])
        self.library.reorder_groups(["g-second", "g-first"])
        self.assertEqual([item["id"] for item in self.library.list_groups()], ["g-second", "g-first"])
        self.library.reorder_categories(first["id"], ["c-high", "c-open"])
        self.assertEqual([c["id"] for c in self.library.get_group(first["id"])["categories"]], ["c-high", "c-open"])
        self.assertEqual(self.library.update_group(second["id"], name="改名")["name"], "改名")
        self.assertEqual(self.library.update_category(category["id"], name="序曲")["name"], "序曲")
        self.assertTrue(self.library.delete_group(first["id"]))
        self.assertIsNone(self.library.get_category(category["id"]))

    def test_membership_add_remove_replace_and_duplicate_conflict(self) -> None:
        songs = [self.songs.create(f"歌曲{i}", "歌手", duration=100 + i)["id"] for i in range(3)]
        group = self.library.create_group("演出", "#fff", group_id="g")
        category = self.library.create_category(group["id"], "开场", "#000", category_id="c")
        self.assertTrue(self.library.add_song(category["id"], songs[0]))
        self.assertFalse(self.library.add_song(category["id"], songs[0]))
        self.assertTrue(self.library.add_song(category["id"], songs[1]))
        self.assertTrue(self.library.remove_song(category["id"], songs[0]))
        self.library.replace_category_songs(category["id"], [songs[2], songs[0]])
        self.assertEqual(self.library.get_category(category["id"])["song_ids"], [songs[2], songs[0]])
        with self.assertRaises(sqlite3.IntegrityError):
            self.library.replace_category_songs(category["id"], [songs[0], 999999])
        self.assertEqual(self.library.get_category(category["id"])["song_ids"], [songs[2], songs[0]])

    def test_reorder_requires_complete_unique_ids(self) -> None:
        group = self.library.create_group("演出", "#fff", group_id="g")
        self.library.create_category(group["id"], "一", "#000", category_id="c1")
        self.library.create_category(group["id"], "二", "#000", category_id="c2")
        with self.assertRaises(ValueError):
            self.library.reorder_categories(group["id"], ["c1"])
        with self.assertRaises(ValueError):
            self.library.reorder_categories(group["id"], ["c1", "c1"])
        with self.assertRaises(ValueError):
            self.library.reorder_groups(["missing"])


if __name__ == "__main__":
    unittest.main()
