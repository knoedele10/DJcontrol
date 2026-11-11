"""数据库仓储：集中处理 SQL，让服务层只组合业务规则。"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Iterable
from uuid import uuid4

from Database.Connection import Database


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return None if row is None else dict(row)


def _rewrite_positions(connection: sqlite3.Connection, table: str, rowids: list[int]) -> None:
    """把给定行（按列表顺序）的 position 写成 0..n-1。

    position 有唯一约束，SQLite 逐行检查；原地 `position - 1` 会撞上还没挪动的行。
    先把这些行整体挪到全表最大值之上，再写回最终值，两步都不会冲突。
    position 有 `>= 0` 约束，所以临时区间只能往上放、不能用负数。
    `table` 只接受本模块内的固定表名，不来自用户输入。
    """

    if not rowids:
        return
    offset = int(connection.execute(f"SELECT COALESCE(MAX(position), 0) + 1 FROM {table}").fetchone()[0])
    for index, rowid in enumerate(rowids):
        connection.execute(f"UPDATE {table} SET position = ? WHERE rowid = ?", (offset + index, rowid))
    for index, rowid in enumerate(rowids):
        connection.execute(f"UPDATE {table} SET position = ? WHERE rowid = ?", (index, rowid))


def _compact_queue(connection: sqlite3.Connection) -> None:
    rowids = [row[0] for row in connection.execute("SELECT rowid FROM queue_items ORDER BY position, id")]
    _rewrite_positions(connection, "queue_items", rowids)


@dataclass(frozen=True)
class SongRecord:
    id: int
    title: str
    artist: str
    bpm: int | None
    duration: int
    source: str
    note: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class HistoryRecord:
    id: int
    session_id: str
    song_id: int | None
    title: str
    artist: str
    played_at: str


class SongRepository:
    """提供歌曲的持久化读写，唯一性和外键约束由数据库保证。"""

    def __init__(self, database: Database) -> None:
        self.database = database

    def list(self, *, source: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM songs"
        parameters: tuple[object, ...] = ()
        if source is not None:
            sql += " WHERE source = ?"
            parameters = (source,)
        sql += " ORDER BY id"
        return [_dict(row) for row in self.database.query_all(sql, parameters)]  # type: ignore[list-item]

    def get(self, song_id: int) -> dict[str, Any] | None:
        return _dict(self.database.query_one("SELECT * FROM songs WHERE id = ?", (song_id,)))

    def create(
        self,
        title: str,
        artist: str,
        *,
        bpm: int | None = None,
        duration: int = 0,
        source: str = "library",
        note: str = "",
    ) -> dict[str, Any]:
        now = _now()
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO songs (title, artist, bpm, duration, source, note, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (title, artist, bpm, duration, source, note, now, now),
            )
            song_id = int(cursor.lastrowid)
        return self.get(song_id)  # type: ignore[return-value]

    def update(self, song_id: int, **changes: Any) -> dict[str, Any] | None:
        allowed = {"title", "artist", "bpm", "duration", "source", "note"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"不支持更新字段：{', '.join(sorted(unknown))}")
        if not changes:
            return self.get(song_id)
        changes["updated_at"] = _now()
        assignments = ", ".join(f"{field} = ?" for field in changes)
        with self.database.transaction() as connection:
            cursor = connection.execute(
                f"UPDATE songs SET {assignments} WHERE id = ?",
                (*changes.values(), song_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get(song_id)

    def delete(self, song_id: int) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute("DELETE FROM songs WHERE id = ?", (song_id,))
            return cursor.rowcount > 0


class LibraryRepository:
    """读取活动组及其有序分类；歌曲归属单独存于关联表。"""

    def __init__(self, database: Database) -> None:
        self.database = database

    def list_groups(self) -> list[dict[str, Any]]:
        groups = [dict(row) for row in self.database.query_all("SELECT * FROM event_groups ORDER BY sort_order, id")]
        for group in groups:
            categories = [
                dict(row)
                for row in self.database.query_all(
                    "SELECT id, group_id, name, color, sort_order FROM categories WHERE group_id = ? ORDER BY sort_order, id",
                    (group["id"],),
                )
            ]
            for category in categories:
                songs = self.database.query_all(
                    "SELECT song_id FROM category_songs WHERE category_id = ? ORDER BY position, song_id",
                    (category["id"],),
                )
                category["song_ids"] = [int(row["song_id"]) for row in songs]
                category.pop("group_id", None)
                category.pop("sort_order", None)
            group["categories"] = categories
            group.pop("sort_order", None)
        return groups

    def get_group(self, group_id: str) -> dict[str, Any] | None:
        return next((group for group in self.list_groups() if group["id"] == group_id), None)

    def update_group(self, group_id: str, **changes: Any) -> dict[str, Any] | None:
        allowed = {"name", "color"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"不支持更新字段：{', '.join(sorted(unknown))}")
        if not changes:
            return self.get_group(group_id)
        assignments = ", ".join(f"{field} = ?" for field in changes)
        with self.database.transaction() as connection:
            cursor = connection.execute(
                f"UPDATE event_groups SET {assignments} WHERE id = ?",
                (*changes.values(), group_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_group(group_id)

    def delete_group(self, group_id: str) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute("DELETE FROM event_groups WHERE id = ?", (group_id,))
            return cursor.rowcount > 0

    def reorder_groups(self, group_ids: Iterable[str]) -> None:
        ids = list(group_ids)
        existing = [row["id"] for row in self.database.query_all("SELECT id FROM event_groups ORDER BY sort_order, id")]
        if len(ids) != len(set(ids)) or set(ids) != set(existing):
            raise ValueError("活动组顺序必须包含全部活动组且不能重复")
        with self.database.transaction() as connection:
            for position, group_id in enumerate(ids):
                connection.execute("UPDATE event_groups SET sort_order = ? WHERE id = ?", (position, group_id))

    def create_group(self, name: str, color: str, *, group_id: str | None = None) -> dict[str, Any]:
        group_id = group_id or f"g-{uuid4().hex}"
        now = _now()
        with self.database.transaction() as connection:
            order = connection.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM event_groups").fetchone()[0]
            connection.execute(
                "INSERT INTO event_groups (id, name, color, sort_order, created_at) VALUES (?, ?, ?, ?, ?)",
                (group_id, name, color, order, now),
            )
        return next(group for group in self.list_groups() if group["id"] == group_id)

    def create_category(
        self,
        group_id: str,
        name: str,
        color: str,
        *,
        song_ids: Iterable[int] = (),
        category_id: str | None = None,
    ) -> dict[str, Any]:
        category_id = category_id or f"c-{uuid4().hex}"
        with self.database.transaction() as connection:
            order = connection.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM categories WHERE group_id = ?",
                (group_id,),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO categories (id, group_id, name, color, sort_order) VALUES (?, ?, ?, ?, ?)",
                (category_id, group_id, name, color, order),
            )
            connection.executemany(
                "INSERT INTO category_songs (category_id, song_id, position) VALUES (?, ?, ?)",
                [(category_id, song_id, position) for position, song_id in enumerate(song_ids)],
            )
        return next(
            category
            for group in self.list_groups()
            for category in group["categories"]
            if category["id"] == category_id
        )

    def get_category(self, category_id: str) -> dict[str, Any] | None:
        row = self.database.query_one(
            "SELECT id, group_id, name, color, sort_order FROM categories WHERE id = ?",
            (category_id,),
        )
        if row is None:
            return None
        category = dict(row)
        category["song_ids"] = [
            int(song["song_id"])
            for song in self.database.query_all(
                "SELECT song_id FROM category_songs WHERE category_id = ? ORDER BY position, song_id",
                (category_id,),
            )
        ]
        category.pop("group_id", None)
        category.pop("sort_order", None)
        return category

    def update_category(self, category_id: str, **changes: Any) -> dict[str, Any] | None:
        allowed = {"name", "color"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"不支持更新字段：{', '.join(sorted(unknown))}")
        if not changes:
            return self.get_category(category_id)
        assignments = ", ".join(f"{field} = ?" for field in changes)
        with self.database.transaction() as connection:
            cursor = connection.execute(
                f"UPDATE categories SET {assignments} WHERE id = ?",
                (*changes.values(), category_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_category(category_id)

    def delete_category(self, category_id: str) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute("DELETE FROM categories WHERE id = ?", (category_id,))
            return cursor.rowcount > 0

    def reorder_categories(self, group_id: str, category_ids: Iterable[str]) -> None:
        ids = list(category_ids)
        existing = [
            row["id"]
            for row in self.database.query_all(
                "SELECT id FROM categories WHERE group_id = ? ORDER BY sort_order, id", (group_id,)
            )
        ]
        if len(ids) != len(set(ids)) or set(ids) != set(existing):
            raise ValueError("分类顺序必须包含该活动组的全部分类且不能重复")
        with self.database.transaction() as connection:
            for position, category_id in enumerate(ids):
                connection.execute("UPDATE categories SET sort_order = ? WHERE id = ?", (position, category_id))

    def add_song(self, category_id: str, song_id: int) -> bool:
        with self.database.transaction() as connection:
            exists = connection.execute(
                "SELECT 1 FROM category_songs WHERE category_id = ? AND song_id = ?",
                (category_id, song_id),
            ).fetchone()
            if exists is not None:
                return False
            position = connection.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM category_songs WHERE category_id = ?",
                (category_id,),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO category_songs (category_id, song_id, position) VALUES (?, ?, ?)",
                (category_id, song_id, position),
            )
            return True

    def remove_song(self, category_id: str, song_id: int) -> bool:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT position FROM category_songs WHERE category_id = ? AND song_id = ?",
                (category_id, song_id),
            ).fetchone()
            if row is None:
                return False
            connection.execute(
                "DELETE FROM category_songs WHERE category_id = ? AND song_id = ?",
                (category_id, song_id),
            )
            remaining = [
                r[0]
                for r in connection.execute(
                    "SELECT rowid FROM category_songs WHERE category_id = ? ORDER BY position", (category_id,)
                )
            ]
            _rewrite_positions(connection, "category_songs", remaining)
            return True

    def replace_category_songs(self, category_id: str, song_ids: Iterable[int]) -> None:
        """原子替换一个分类的排序，拖拽排序时避免中间状态被读到。"""

        with self.database.transaction() as connection:
            connection.execute("DELETE FROM category_songs WHERE category_id = ?", (category_id,))
            connection.executemany(
                "INSERT INTO category_songs (category_id, song_id, position) VALUES (?, ?, ?)",
                [(category_id, song_id, position) for position, song_id in enumerate(song_ids)],
            )


class QueueRepository:
    """提供队列项和已播记录的基础持久化操作。"""

    def __init__(self, database: Database) -> None:
        self.database = database

    def list_items(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.database.query_all("SELECT * FROM queue_items ORDER BY position, id")]

    def add(self, song_id: int, *, position: int | None = None, item_id: str | None = None) -> dict[str, Any]:
        item_id = item_id or f"q-{uuid4().hex}"
        now = _now()
        with self.database.transaction() as connection:
            if position is None:
                position = int(connection.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM queue_items").fetchone()[0])
            # 先移到超过当前最大值的临时区间，避免 CHECK/UNIQUE 约束在原地挪动时冲突。
            max_position = int(connection.execute("SELECT COALESCE(MAX(position), -1) FROM queue_items").fetchone()[0])
            offset = max_position + 2
            connection.execute(
                "UPDATE queue_items SET position = position + ? WHERE position >= ?",
                (offset, position),
            )
            connection.execute(
                "UPDATE queue_items SET position = position - ? + 1 WHERE position >= ?",
                (offset, offset),
            )
            connection.execute(
                "INSERT INTO queue_items (id, song_id, position, added_at) VALUES (?, ?, ?, ?)",
                (item_id, song_id, position, now),
            )
        return dict(self.database.query_one("SELECT * FROM queue_items WHERE id = ?", (item_id,)))  # type: ignore[arg-type]

    def enqueue(self, song_id: int, *, position: int | None = None) -> dict[str, Any]:
        """加入或移动同一首歌，保持队列项 ID 并避免重复。"""

        with self.database.transaction() as connection:
            existing = connection.execute("SELECT id, position FROM queue_items WHERE song_id = ?", (song_id,)).fetchone()
            item_id = str(existing["id"]) if existing is not None else f"q-{uuid4().hex}"
            if existing is not None:
                connection.execute("DELETE FROM queue_items WHERE id = ?", (item_id,))
                _compact_queue(connection)
            max_position = int(connection.execute("SELECT COALESCE(MAX(position), -1) FROM queue_items").fetchone()[0])
            target = max_position + 1 if position is None else max(0, min(int(position), max_position + 1))
            offset = max_position + 2
            connection.execute("UPDATE queue_items SET position = position + ? WHERE position >= ?", (offset, target))
            connection.execute("UPDATE queue_items SET position = position - ? + 1 WHERE position >= ?", (offset, offset))
            connection.execute(
                "INSERT INTO queue_items (id, song_id, position, added_at) VALUES (?, ?, ?, ?)",
                (item_id, song_id, target, _now()),
            )
        return dict(self.database.query_one("SELECT * FROM queue_items WHERE id = ?", (item_id,)))  # type: ignore[arg-type]

    def order(self, item_ids: Iterable[str]) -> None:
        ids = list(item_ids)
        existing = [row["id"] for row in self.database.query_all("SELECT id FROM queue_items ORDER BY position, id")]
        if len(ids) != len(set(ids)) or set(ids) != set(existing):
            raise ValueError("队列顺序必须包含全部队列项且不能重复")
        with self.database.transaction() as connection:
            rowid_of = {row["id"]: row["rowid"] for row in connection.execute("SELECT rowid, id FROM queue_items")}
            _rewrite_positions(connection, "queue_items", [rowid_of[item_id] for item_id in ids])

    def remove_song(self, song_id: int) -> int:
        with self.database.transaction() as connection:
            rows = connection.execute("SELECT id FROM queue_items WHERE song_id = ? ORDER BY position", (song_id,)).fetchall()
            count = len(rows)
            for row in rows:
                connection.execute("DELETE FROM queue_items WHERE id = ?", (row["id"],))
            # 删除后重排，保证前端永远看到连续位置。
            _compact_queue(connection)
            return count

    def delete(self, item_id: str) -> bool:
        with self.database.transaction() as connection:
            row = connection.execute("SELECT position FROM queue_items WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                return False
            connection.execute("DELETE FROM queue_items WHERE id = ?", (item_id,))
            _compact_queue(connection)
            return True

    def clear(self) -> None:
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM queue_items")


class SessionRepository:
    """保存演出场次和播放时的歌曲快照。"""

    def __init__(self, database: Database) -> None:
        self.database = database

    def current(self) -> dict[str, Any] | None:
        return _dict(self.database.query_one("SELECT * FROM sessions WHERE ended_at IS NULL LIMIT 1"))

    def latest(self) -> dict[str, Any] | None:
        return _dict(self.database.query_one("SELECT * FROM sessions ORDER BY started_at DESC, id DESC LIMIT 1"))

    def start(self, *, session_id: str | None = None, started_at: str | None = None) -> dict[str, Any]:
        session_id = session_id or f"s-{uuid4().hex}"
        started_at = started_at or _now()
        with self.database.transaction() as connection:
            connection.execute("UPDATE sessions SET ended_at = ? WHERE ended_at IS NULL", (started_at,))
            connection.execute(
                "INSERT INTO sessions (id, started_at, ended_at) VALUES (?, ?, NULL)",
                (session_id, started_at),
            )
        return dict(self.database.query_one("SELECT * FROM sessions WHERE id = ?", (session_id,)))  # type: ignore[arg-type]

    def end_current(self, *, ended_at: str | None = None) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE sessions SET ended_at = ? WHERE ended_at IS NULL",
                (ended_at or _now(),),
            )
            return cursor.rowcount > 0

    def add_history(
        self,
        session_id: str,
        *,
        song_id: int | None,
        title: str,
        artist: str,
        played_at: str | None = None,
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO history (session_id, song_id, title, artist, played_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, song_id, title, artist, played_at or _now()),
            )
            history_id = int(cursor.lastrowid)
        return dict(self.database.query_one("SELECT * FROM history WHERE id = ?", (history_id,)))  # type: ignore[arg-type]

    def list_history(self, session_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.database.query_all(
                "SELECT * FROM history WHERE session_id = ? ORDER BY played_at DESC, id DESC LIMIT ?",
                (session_id, limit),
            )
        ]


class SettingsRepository:
    """以字符串存储少量设置，JSON 值由调用方决定是否编码。"""

    def __init__(self, database: Database) -> None:
        self.database = database

    def get(self, key: str, default: Any = None) -> Any:
        row = self.database.query_one("SELECT value FROM settings WHERE key = ?", (key,))
        if row is None:
            return default
        value = row["value"]
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return value

    def set(self, key: str, value: Any) -> None:
        encoded = json.dumps(value, ensure_ascii=False)
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, encoded, _now()),
            )


class PptBindingRepository:
    """保存文稿页码与歌曲的绑定，歌曲删除时保留页码但清空歌曲。"""

    def __init__(self, database: Database) -> None:
        self.database = database

    def get(self, app: str, document_id: str, slide: int) -> dict[str, Any] | None:
        return _dict(
            self.database.query_one(
                "SELECT app, document_id, slide, song_id FROM ppt_bindings WHERE app = ? AND document_id = ? AND slide = ?",
                (app, document_id, slide),
            )
        )

    def list(self, app: str, document_id: str) -> dict[int, int]:
        """这份文稿里绑了歌的页：{页码: 歌曲 id}。"""

        rows = self.database.query_all(
            "SELECT slide, song_id FROM ppt_bindings WHERE app = ? AND document_id = ? AND song_id IS NOT NULL",
            (app, document_id),
        )
        return {int(row["slide"]): int(row["song_id"]) for row in rows}

    def set(self, app: str, document_id: str, slide: int, song_id: int | None) -> dict[str, Any]:
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO ppt_bindings (app, document_id, slide, song_id) VALUES (?, ?, ?, ?)
                ON CONFLICT(app, document_id, slide) DO UPDATE SET song_id = excluded.song_id
                """,
                (app, document_id, slide, song_id),
            )
        return self.get(app, document_id, slide)  # type: ignore[return-value]
