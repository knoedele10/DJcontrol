"""提供首次启动所需的演示数据，保持后端与前端原型使用同一份曲库。"""

from __future__ import annotations

import sqlite3
from datetime import datetime


LIBRARY_ROWS: tuple[tuple[str, str, int, int], ...] = (
    ("夜空中最亮的星", "逃跑计划", 96, 252),
    ("晴天", "周杰伦", 69, 269),
    ("平凡之路", "朴树", 85, 301),
    ("稻香", "周杰伦", 82, 223),
    ("光年之外", "邓紫棋", 78, 235),
    ("孤勇者", "陈奕迅", 140, 256),
    ("海阔天空", "Beyond", 148, 326),
    ("倔强", "五月天", 132, 260),
    ("离开地球表面", "五月天", 150, 251),
    ("Unstoppable", "Sia", 174, 217),
    ("起风了", "买辣椒也用券", 80, 325),
    ("小幸运", "田馥甄", 82, 265),
    ("后来", "刘若英", 76, 341),
    ("红豆", "王菲", 72, 253),
    ("野狼disco", "宝石Gem", 128, 249),
    ("最炫民族风", "凤凰传奇", 130, 287),
    ("恭喜发财", "刘德华", 120, 210),
    ("学猫叫", "小潘潘", 120, 214),
    ("运动员进行曲", "军乐团", 120, 150),
    ("拉德茨基进行曲", "维也纳爱乐", 112, 180),
    ("We Will Rock You", "Queen", 81, 122),
    ("我相信", "杨培安", 136, 268),
    ("超越梦想", "汪正正", 90, 270),
    ("奔跑", "羽泉", 145, 263),
    ("相亲相爱", "群星", 90, 284),
    ("We Are the Champions", "Queen", 64, 179),
    ("追梦赤子心", "GALA", 150, 302),
    ("Hall of Fame", "The Script", 85, 202),
)


GROUP_ROWS: tuple[tuple[str, str, str, tuple[tuple[str, str, str, tuple[int, ...]], ...]], ...] = (
    (
        "g1",
        "演唱会",
        "#ff3da6",
        (
            ("c1", "暖场", "#00e0a4", (0, 1, 2, 3, 4)),
            ("c2", "高潮", "#ff6a2b", (5, 6, 7, 8, 9)),
            ("c3", "慢歌", "#a66bff", (10, 11, 12, 13)),
            ("c4", "互动", "#ffc928", (14, 15, 16, 17)),
        ),
    ),
    (
        "g2",
        "运动会",
        "#2fb8ff",
        (
            ("c5", "入场式", "#2fb8ff", (18, 19, 26)),
            ("c6", "比赛进行中", "#ff6a2b", (20, 21, 23, 9, 27)),
            ("c7", "颁奖", "#ffc928", (25, 22, 6)),
            ("c8", "中场休息", "#00e0a4", (24, 14, 15, 3)),
        ),
    ),
)


def _now() -> str:
    """使用带时区的时间，保证后续接口可以直接返回 ISO 8601。"""

    return datetime.now().astimezone().isoformat()


def seed_database(connection: sqlite3.Connection) -> bool:
    """仅在业务表完全为空时写入原型种子，避免覆盖用户已有数据。"""

    tables = ("songs", "event_groups", "categories", "queue_items", "sessions", "history")
    has_data = any(connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() for table in tables)
    if has_data:
        return False

    now = _now()
    connection.executemany(
        """
        INSERT INTO songs (id, title, artist, bpm, duration, source, note, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'library', '', ?, ?)
        """,
        [(song_id, title, artist, bpm, duration, now, now)
         for song_id, (title, artist, bpm, duration) in enumerate(LIBRARY_ROWS)],
    )
    connection.executemany(
        """
        INSERT INTO event_groups (id, name, color, sort_order, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        [(group_id, name, color, order, now)
         for order, (group_id, name, color, _) in enumerate(GROUP_ROWS)],
    )

    category_rows: list[tuple[str, str, str, str, int]] = []
    membership_rows: list[tuple[str, int, int]] = []
    for group_id, _, _, categories in GROUP_ROWS:
        for category_order, (category_id, name, color, song_ids) in enumerate(categories):
            category_rows.append((category_id, group_id, name, color, category_order))
            membership_rows.extend((category_id, song_id, position) for position, song_id in enumerate(song_ids))
    connection.executemany(
        "INSERT INTO categories (id, group_id, name, color, sort_order) VALUES (?, ?, ?, ?, ?)",
        category_rows,
    )
    connection.executemany(
        "INSERT INTO category_songs (category_id, song_id, position) VALUES (?, ?, ?)",
        membership_rows,
    )
    connection.executemany(
        "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
        [("controller", "mock", now), ("auto_next", "true", now), ("link_music", "true", now)],
    )
    connection.commit()
    return True
