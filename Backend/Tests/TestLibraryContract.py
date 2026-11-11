"""M2 请求契约测试；验证严格字段和接口路由已注册。"""

import unittest

from pydantic import ValidationError

from Main import app
from Library.Model import CategoryOrderRequest, GroupOrderRequest, SongCreate
from Library.Service import _public_song


class LibraryContractTests(unittest.TestCase):
    def test_models_reject_extra_and_non_strict_numbers(self) -> None:
        with self.assertRaises(ValidationError):
            SongCreate(title="歌", artist="人", duration="120")
        with self.assertRaises(ValidationError):
            SongCreate(title="歌", artist="人", extra="x")
        with self.assertRaises(ValidationError):
            GroupOrderRequest(group_ids=[1])
        with self.assertRaises(ValidationError):
            from Library.Model import CategoryCreate
            CategoryCreate(name="分类", song_ids=[True])
        with self.assertRaises(ValidationError):
            CategoryOrderRequest(category_ids=["c1"], extra=True)

    def test_m2_routes_are_registered(self) -> None:
        paths = {route.path for route in app.routes}
        self.assertTrue({
            "/api/songs", "/api/songs/import", "/api/search", "/api/groups", "/api/groups/order",
            "/api/groups/{group_id}/categories", "/api/categories/{category_id}/songs", "/ws/library",
        } <= paths)

    def test_public_song_shape_excludes_database_audit_columns(self) -> None:
        self.assertEqual(
            set(_public_song({
                "id": 1, "title": "歌", "artist": "人", "bpm": None, "duration": 1,
                "source": "library", "note": "", "created_at": "now", "updated_at": "now",
            })),
            {"id", "title", "artist", "bpm", "duration", "source", "note"},
        )


if __name__ == "__main__":
    unittest.main()
