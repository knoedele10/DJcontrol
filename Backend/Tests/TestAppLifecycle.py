"""应用生命周期与 M1 数据库集成测试。"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient

from Database import Database
from Main import create_app


class AppLifecycleTests(unittest.TestCase):
    def test_startup_initializes_injected_database_and_closes_it(self) -> None:
        database = Database(":memory:")
        ppt_service = Mock()

        async def start() -> None:
            return None

        async def close() -> None:
            return None

        ppt_service.start = start
        ppt_service.close = close
        with TestClient(create_app(ppt_service, database)) as client:
            self.assertEqual(client.get("/api/health").json(), {"status": "ok"})
            self.assertIs(client.app.state.db, database)
            self.assertEqual(database.query_one("SELECT COUNT(*) FROM songs")[0], 28)
            self.assertEqual(database.query_one("SELECT COUNT(*) FROM schema_migrations")[0], 2)
        with self.assertRaisesRegex(Exception, "closed"):
            database.query_one("SELECT 1")

    def test_serves_frontend_dist_when_configured(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd(), ignore_cleanup_errors=True) as directory:
            Path(directory, "index.html").write_text("<html>panel</html>", encoding="utf-8")
            os.environ["FRONTEND_DIST"] = directory
            self.addCleanup(os.environ.pop, "FRONTEND_DIST", None)

            database = Database(":memory:")
            ppt_service = Mock()

            async def start() -> None:
                return None

            async def close() -> None:
                return None

            ppt_service.start = start
            ppt_service.close = close
            with TestClient(create_app(ppt_service, database)) as client:
                self.assertEqual(client.get("/api/health").json(), {"status": "ok"})
                response = client.get("/")
                self.assertEqual(response.status_code, 200)
                self.assertIn("panel", response.text)

    def test_file_database_rebuilds_after_deletion_and_uses_wal(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd(), ignore_cleanup_errors=True) as directory:
            path = Path(directory) / "nested" / "dashboard.db"
            first = Database(path)
            first.connect()
            self.assertEqual(first.query_one("PRAGMA journal_mode")[0], "wal")
            self.assertEqual(first.query_one("SELECT COUNT(*) FROM songs")[0], 28)
            first.close()
            path.unlink()
            for suffix in ("-wal", "-shm"):
                sidecar = Path(f"{path}{suffix}")
                sidecar.unlink(missing_ok=True)

            second = Database(path)
            second.connect()
            self.assertEqual(second.query_one("SELECT COUNT(*) FROM schema_migrations")[0], 2)
            self.assertEqual(second.query_one("SELECT COUNT(*) FROM songs")[0], 28)
            second.close()


if __name__ == "__main__":
    unittest.main()
