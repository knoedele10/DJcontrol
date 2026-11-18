"""代理模式测试：容器只出界面，/api 与 /ws 转发给上游。

上游用一个真的 HTTP 服务和一个真的 WebSocket 服务代替，避免只测到 mock。
"""

import json
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastapi.testclient import TestClient
from websockets.sync.server import serve

from Main import create_app
from Proxy import normalize_upstream


class _UpstreamHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == '/api/health':
            self._reply(200, {'status': 'ok'})
            return
        if self.path.startswith("/api/missing"):
            self._reply(404, {"detail": "not found"})
            return
        self._reply(200, {"path": self.path, "method": "GET", "host": self.headers.get("Host")})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8")
        self._reply(201, {"path": self.path, "method": "POST", "body": body})

    def _reply(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:  # noqa: D102 - 测试里不需要访问日志
        pass


def _closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class ProxyHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _UpstreamHandler)
        cls.upstream = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def test_forwards_path_query_and_body(self) -> None:
        with TestClient(create_app(upstream=self.upstream)) as client:
            response = client.get("/api/songs?group=1")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["path"], "/api/songs?group=1")

            posted = client.post("/api/groups", json={"name": "返场"})
            self.assertEqual(posted.status_code, 201)
            self.assertEqual(posted.json()["method"], "POST")
            self.assertIn("返场", json.loads(posted.json()["body"])["name"])

    def test_upstream_error_status_passes_through(self) -> None:
        with TestClient(create_app(upstream=self.upstream)) as client:
            response = client.get("/api/missing")
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["detail"], "not found")

    def test_health_and_frontend_stay_local(self) -> None:
        with TestClient(create_app(upstream=self.upstream)) as client:
            health = client.get("/api/health")
            self.assertEqual(health.status_code, 200)
            self.assertEqual(health.json()["mode"], "proxy")
            self.assertEqual(health.json()["upstream"], self.upstream)

    def test_unreachable_upstream_returns_502(self) -> None:
        upstream = f"http://127.0.0.1:{_closed_port()}"
        with TestClient(create_app(upstream=upstream)) as client:
            response = client.get("/api/songs")
            self.assertEqual(response.status_code, 502)
            self.assertEqual(response.json()["detail"]["code"], "upstream_unavailable")

    def test_connection_probe_distinguishes_live_container_from_missing_windows_backend(self):
        upstream = f'http://127.0.0.1:{_closed_port()}'
        with TestClient(create_app(upstream=upstream)) as client:
            self.assertEqual(client.get('/api/health').status_code, 200)
            result = client.get('/api/connection')
            self.assertEqual(result.status_code, 200)
            self.assertFalse(result.json()['backend_connected'])
            self.assertEqual(result.json()['mode'], 'proxy')
            self.assertIn('Windows', result.json()['message'])

    def test_connection_probe_checks_real_upstream_health(self):
        with TestClient(create_app(upstream=self.upstream)) as client:
            result = client.get('/api/connection').json()
            self.assertTrue(result['backend_connected'])
            self.assertEqual(result['upstream'], self.upstream)

    def test_proxy_mode_has_no_local_database(self) -> None:
        with TestClient(create_app(upstream=self.upstream)) as client:
            self.assertFalse(hasattr(client.app.state, "db"))


class ProxyWebSocketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        def echo(connection) -> None:
            for message in connection:
                connection.send(message)

        cls.server = serve(echo, "127.0.0.1", 0)
        cls.port = cls.server.socket.getsockname()[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()

    def test_forwards_text_frames_both_ways(self) -> None:
        upstream = f"http://127.0.0.1:{self.port}"
        with TestClient(create_app(upstream=upstream)) as client:
            with client.websocket_connect("/ws/ppt?session=1") as socket:
                socket.send_text("ping")
                self.assertEqual(socket.receive_text(), "ping")


class NormalizeUpstreamTests(unittest.TestCase):
    def test_strips_trailing_slash(self) -> None:
        self.assertEqual(normalize_upstream(" http://host:8000/ "), "http://host:8000")

    def test_empty_means_local_mode(self) -> None:
        self.assertEqual(normalize_upstream(""), "")

    def test_rejects_value_without_scheme(self) -> None:
        for bad in ("host:8000", "ftp://host:8000", "http://"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                normalize_upstream(bad)


if __name__ == "__main__":
    unittest.main()
