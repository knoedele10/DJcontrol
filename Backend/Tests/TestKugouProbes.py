"""只测探测隔离与按键确认边界，自动化测试不访问真实酷狗。"""

import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

PROBES = Path(__file__).resolve().parents[2] / "Probes"
sys.path.insert(0, str(PROBES))
import KugouCommon
import KugouMedia
import KugouSmtc


class KugouProbeTests(unittest.TestCase):
    def test_media_default_never_sends_or_queries_real_software(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["KugouMedia.py"]), \
                patch.object(KugouMedia, "send_keys") as send, \
                patch.object(KugouMedia, "processes") as running, \
                contextlib.redirect_stdout(output):
            KugouMedia.main()
        send.assert_not_called()
        running.assert_not_called()
        self.assertFalse(json.loads(output.getvalue())["data"]["sent"])

    def test_media_execution_cancelled_without_exact_confirmation(self):
        with patch.object(sys, "argv", ["KugouMedia.py", "--execute"]), \
                patch.object(KugouMedia, "require_windows"), \
                patch.object(KugouMedia, "processes", return_value=[{"pid": 1}]), \
                patch.object(KugouMedia, "confirm", return_value=False), \
                patch.object(KugouMedia, "send_keys") as send, \
                contextlib.redirect_stdout(io.StringIO()):
            KugouMedia.main()
        send.assert_not_called()
        self.assertFalse(KugouMedia.confirm(lambda _: "yes"))
        self.assertFalse(KugouMedia.confirm(lambda _: ""))
        self.assertTrue(KugouMedia.confirm(lambda _: "执行"))

    def test_media_send_is_never_reported_as_verified(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["KugouMedia.py", "--execute", "--action", "next"]), \
                patch.object(KugouMedia, "require_windows"), \
                patch.object(KugouMedia, "processes", return_value=[{"pid": 1}]), \
                patch.object(KugouMedia, "confirm", return_value=True), \
                patch.object(KugouMedia, "send_keys") as send, \
                contextlib.redirect_stdout(output):
            KugouMedia.main()
        send.assert_called_once_with([0xB0])
        result = json.loads(output.getvalue()[output.getvalue().index("{"):])
        self.assertTrue(result["data"]["sent"])
        self.assertFalse(result["data"]["verified"])

    def test_invalid_or_system_hotkeys_rejected(self):
        for key in ("a", "win+r", "alt+f4", "shift+a", "ctrl+ctrl+p", "ctrl+enter"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                KugouMedia.hotkey_codes(key)
        self.assertEqual(KugouMedia.hotkey_codes("alt+left"), [0x12, 0x25])

    def test_timeout_kills_worker_and_is_not_capability_failure(self):
        with patch.object(KugouCommon.subprocess, "run", side_effect=subprocess.TimeoutExpired("probe", 1)):
            result = KugouCommon.isolated("KugouUiaTree.py", [], 1)
        self.assertEqual(result["status"], "timeout")
        self.assertNotIn("supported", result)

    def test_broken_worker_output_does_not_become_success(self):
        completed = subprocess.CompletedProcess([], 1, "partial output", "failure")
        with patch.object(KugouCommon.subprocess, "run", return_value=completed):
            result = KugouCommon.isolated("KugouVersion.py", [], 1)
        self.assertEqual(result["status"], "error")

    def test_smtc_filters_other_players(self):
        self.assertTrue(KugouSmtc.is_kugou_source("C:\\KuGou\\KuGou.exe"))
        self.assertFalse(KugouSmtc.is_kugou_source("chrome.exe"))


if __name__ == "__main__":
    unittest.main()
