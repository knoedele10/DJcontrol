"""真实幻灯片预览的接口与 COM 导出回归。"""

import base64
import unittest
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient

from PptControl import PowerPointController, PptCommandError, WpsController
from Database import Database
from Main import create_app
from PptControl.Service import PptService
from Tests.TestPpt import Collection, FakeApplication, FakeController

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aF+0AAAAASUVORK5CYII="
)


class PreviewController(FakeController):
    def __init__(self, app):
        super().__init__(app)
        self.exports = []

    def export_slide(self, slide, width=1280, document_id=None):
        self.get_state()
        self.exports.append((slide, width, document_id))
        return PNG


class PreviewApiTests(unittest.TestCase):
    def test_cached_page_does_not_access_office_and_browser_can_reuse_the_image(self):
        service = PptService(factory=PreviewController, poll_interval=3600)
        with TestClient(create_app(service, Database(":memory:"))) as client:
            snapshot = client.get("/api/ppt/state").json()
            params = {"app": "powerpoint", "document": "D:/show.pptx", "session": snapshot["preview_session"]}
            response = client.get("/api/ppt/preview/2", params=params)
            self.assertEqual(response.status_code, 200)
            self.assertIn("immutable", response.headers["cache-control"])
            service._controller.get_state = Mock(side_effect=AssertionError("缓存命中不应访问 Office"))
            response = client.get("/api/ppt/preview/2", params=params)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, PNG)
        self.assertFalse(service._previews.directory.exists())

    def test_whole_document_cache_is_not_evicted_after_32_pages(self):
        def factory(app):
            controller = PreviewController(app)
            controller.state = replace(controller.state, total_slides=40)
            return controller

        service = PptService(factory=factory, poll_interval=3600)
        with TestClient(create_app(service, Database(":memory:"))) as client:
            params = {"app": "powerpoint", "document": "D:/show.pptx"}
            for page in range(1, 41):
                self.assertEqual(client.get(f"/api/ppt/preview/{page}", params=params).status_code, 200)
            self.assertEqual(len(service._controller.exports), 40)
            client.get("/api/ppt/preview/1", params=params)
            self.assertEqual(len(service._controller.exports), 40)
            old_session = service.preview_session
            service._controller.state = replace(service._controller.state, document_id="D:/new.pptx")
            snapshot = client.get("/api/ppt/state").json()
            self.assertNotEqual(snapshot["preview_session"], old_session)
            self.assertEqual(list(service._previews.directory.iterdir()), [])
            self.assertEqual(client.get("/api/ppt/preview/1", params={**params, "session": old_session}).status_code, 409)

    def test_preview_serves_png_without_changing_current_page_and_caches_exports(self):
        controllers = []

        def factory(app):
            controller = PreviewController(app)
            controllers.append(controller)
            return controller

        with TestClient(create_app(PptService(factory=factory), Database(":memory:"))) as client:
            params = {"app": "powerpoint", "document": "D:/show.pptx"}
            for _ in range(2):
                response = client.get("/api/ppt/preview/3", params=params)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["content-type"], "image/png")
                self.assertEqual(response.content, PNG)
            self.assertEqual(len(controllers[0].exports), 1)
            self.assertEqual(controllers[0].state.current_slide, 1)
            client.get("/api/ppt/preview/3", params={**params, "version": 1})
            self.assertEqual(len(controllers[0].exports), 2)
            response = client.get("/api/ppt/preview/2", params={**params, "width": 240})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(controllers[0].exports[-1], (2, 240, "D:/show.pptx"))

    def test_preview_rejects_stale_document_and_invalid_pages(self):
        with TestClient(create_app(PptService(factory=PreviewController), Database(":memory:"))) as client:
            params = {"app": "powerpoint", "document": "D:/show.pptx"}
            self.assertEqual(client.get("/api/ppt/preview/5", params=params).status_code, 409)
            self.assertEqual(client.get("/api/ppt/preview/0", params=params).status_code, 422)
            self.assertEqual(client.get("/api/ppt/preview/2", params={**params, "width": 99999}).status_code, 422)
            self.assertEqual(client.get("/api/ppt/preview/2", params={**params, "document": "other"}).status_code, 409)
            self.assertEqual(client.get("/api/ppt/preview/2", params={**params, "app": "wps"}).status_code, 409)


class PreviewComTests(unittest.TestCase):
    def test_both_adapters_export_actual_slide_preserving_aspect_and_selection(self):
        for cls in (PowerPointController, WpsController):
            with self.subTest(app=cls.__name__):
                application = FakeApplication()
                application.document.PageSetup = SimpleNamespace(SlideWidth=960, SlideHeight=720)
                exports = []

                def export(path, kind, width, height):
                    exports.append((path, kind, width, height))
                    Path(path).write_bytes(PNG)

                application.document.Slides = Collection([SimpleNamespace(Export=export) for _ in range(4)])
                controller = cls()
                controller._application = application
                controller._pythoncom = Mock()
                image = controller.export_slide(3, document_id=application.document.FullName)
                self.assertEqual(image, PNG)
                self.assertEqual(exports[0][1:], ("PNG", 1280, 960))
                self.assertFalse(Path(exports[0][0]).exists())
                self.assertEqual(application.slide, 2)
                with self.assertRaises(PptCommandError):
                    controller.export_slide(3, document_id="another document")
