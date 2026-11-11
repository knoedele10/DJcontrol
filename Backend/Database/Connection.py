"""SQLite 连接和迁移入口；业务代码通过这里获得已初始化的数据库。"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, Sequence

from Database.Seed import seed_database

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = BACKEND_ROOT / "Data" / "dashboard.db"
DEFAULT_MIGRATIONS_DIR = BACKEND_ROOT / "Database" / "Migrations"


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat()


class Database:
    """管理 SQLite 生命周期、迁移和事务，避免服务层拼接 SQL。"""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        migrations_dir: str | Path | None = None,
        seed: bool = True,
    ) -> None:
        configured = path if path is not None else os.environ.get("DB_PATH")
        self.path = ":memory:" if str(configured) == ":memory:" else Path(configured or DEFAULT_DB_PATH)
        self.migrations_dir = Path(migrations_dir or DEFAULT_MIGRATIONS_DIR)
        self.seed = seed
        self._connection: sqlite3.Connection | None = None
        self._closed = False
        self._lock = threading.RLock()

    @property
    def connection(self) -> sqlite3.Connection:
        """返回初始化后的连接；所有仓储调用都共享同一连接。"""

        return self.connect()

    def connect(self) -> sqlite3.Connection:
        """打开数据库、设置约束并按顺序执行尚未应用的迁移。"""

        with self._lock:
            if self._connection is not None:
                return self._connection
            if self._closed:
                # 关闭后不再悄悄重开：内存库会变成一个新的空库，文件库会在服务退出后被继续写入。
                raise sqlite3.ProgrammingError("Cannot operate on a closed database.")
            if self.path != ":memory:":
                Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(
                self.path,
                check_same_thread=False,
                isolation_level=None,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            if self.path != ":memory:":
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("PRAGMA synchronous = NORMAL")
            self._connection = connection
            try:
                self._migrate(connection)
                if self.seed:
                    seed_database(connection)
            except Exception:
                connection.close()
                self._connection = None
                raise
            return connection

    def _migrate(self, connection: sqlite3.Connection) -> None:
        """用文件名排序保证迁移可重复执行且不会跳过中间版本。"""

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        applied = {
            row[0] for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
        }
        for migration in sorted(self.migrations_dir.glob("*.sql")):
            if migration.name in applied:
                continue
            script = migration.read_text(encoding="utf-8")
            try:
                connection.execute("BEGIN")
                connection.executescript(script)
                connection.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (migration.name, _timestamp()),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """在锁内提供一个提交或回滚边界，仓储可组合多个 SQL 操作。"""

        connection = self.connect()
        with self._lock:
            try:
                connection.execute("BEGIN")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def execute(self, sql: str, parameters: Sequence[object] = ()) -> sqlite3.Cursor:
        """执行一条写入语句并提交事务。"""

        with self.transaction() as connection:
            return connection.execute(sql, parameters)

    def query_all(self, sql: str, parameters: Sequence[object] = ()) -> list[sqlite3.Row]:
        """执行查询并将行保留为可按列名访问的 SQLite Row。"""

        with self._lock:
            return self.connect().execute(sql, parameters).fetchall()

    def query_one(self, sql: str, parameters: Sequence[object] = ()) -> sqlite3.Row | None:
        """执行查询并返回一行或 None。"""

        with self._lock:
            return self.connect().execute(sql, parameters).fetchone()

    def close(self) -> None:
        """关闭连接，此后该实例不可再用；文件数据库的 WAL 检查点交给 SQLite 自己处理。"""

        with self._lock:
            self._closed = True
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def __enter__(self) -> "Database":
        self.connect()
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()
