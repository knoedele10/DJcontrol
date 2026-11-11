"""M5 回归：用隔离进程替身和内存数据库验证安全边界，不操作真实软件。"""

import asyncio
from dataclasses import replace
import json
import subprocess
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from Player.Base import ControllerCommandFailed, ControllerCommandPending, ControllerTimeout, ControllerTrackLoading, PlayerReading, PlayerUnavailable
from KugouControl.Adapter import KugouController
from KugouControl.Profiles import match, parse_title, same_track
from KugouControl import Track
from KugouControl import Worker
from KugouControl import Uia
from KugouControl.Process import WorkerProcess
from Database import Database, QueueRepository, SongRepository
from Main import create_app
from Player.Model import PlayerCommand
from Player.Service import PlayerService, PlayerUnsupported, PlayerConflict


def observed(**kwargs):
    return {"connected": True, "running": True, "status": "paused", "title": "真实歌曲", "artist": "歌手",
            "profile": "kugou-10.2.52.25713", "version": "10.2.52.25713", "controls_ready": True,
            "error": None, **kwargs}


class KugouControllerTests(unittest.TestCase):
    def test_cached_locator_reads_live_state_instead_of_cached_name(self):
        button = SimpleNamespace(CurrentName="播放", CurrentIsEnabled=True)
        bar = MagicMock()
        bar.element.FindFirst.return_value = button
        automation = MagicMock()
        modules = {"pywinauto.uia_element_info": SimpleNamespace(UIAElementInfo=MagicMock()),
                   "pywinauto.uia_defines": SimpleNamespace(IUIA=lambda: automation)}
        with patch.dict(sys.modules, modules), patch.object(Uia, '_bar', bar), patch.object(Uia, '_hwnd', 123), \
                patch.object(Uia, '_cached_at', __import__('time').monotonic()):
            self.assertEqual(Uia.read_controls(123)['status'], 'paused')
            button.CurrentName = '暂停'
            self.assertEqual(Uia.read_controls(123)['status'], 'playing')
            Uia.invalidate()
            self.assertIsNone(Uia._bar)

    def test_persistent_transport_reuses_worker_and_cleans_up_on_eof(self):
        process = MagicMock()
        process.poll.return_value = None
        process.stdout = iter(['{"data":1}\n', '{"data":2}\n'])
        process.stderr = iter([])
        # 使用真实文件包装器模拟管道的 EOF/close 行为。
        import io
        process.stdout = io.StringIO('{"data":1}\n{"data":2}\n')
        process.stderr = io.StringIO('')
        transport = WorkerProcess()
        with patch('KugouControl.Process.subprocess.Popen', return_value=process) as start:
            self.assertEqual(json.loads(transport(['read'], cwd='.', timeout=1).stdout)['data'], 1)
            self.assertEqual(json.loads(transport(['toggle'], cwd='.', timeout=1).stdout)['data'], 2)
            with self.assertRaises(OSError): transport(['read'], cwd='.', timeout=1)
        start.assert_called_once()
        process.kill.assert_called_once()
        self.assertEqual(process.stdin.write.call_count, 3)

    def test_timeout_never_retries_and_later_read_recovers(self):
        calls = []
        def run(args, **kwargs):
            calls.append(args[-1])
            if len(calls) == 1:
                raise subprocess.TimeoutExpired(args, kwargs["timeout"])
            return subprocess.CompletedProcess(args, 0, json.dumps({"data": observed()}), "")
        controller = KugouController(runner=run)
        with self.assertRaises(ControllerTimeout):
            controller.toggle()
        self.assertEqual(calls, ["toggle"])
        self.assertTrue(controller.get_state().connected)
        self.assertTrue(controller.capabilities()[0]["supported"])

    def test_malformed_worker_clears_state_and_capabilities(self):
        controller = KugouController(runner=lambda *a, **kw: subprocess.CompletedProcess([], 1, "broken", "failure"))
        controller.info = observed()
        self.assertFalse(controller.get_state().connected)
        # 酷狗搜索查的是网络接口，不依赖酷狗窗口；其余能力都要酷狗能连上。
        self.assertEqual([cap["name"] for cap in controller.capabilities() if cap["supported"]], ["kugou_search"])

    def test_future_versions_rejected_and_title_keeps_internal_separators(self):
        self.assertIsNone(match("10.2.53.1"))
        self.assertEqual(parse_title("歌手 - 歌名 - Live - 酷狗音乐  "), ("歌名 - Live", "歌手"))
        self.assertEqual(parse_title("酷狗音乐"), ("", ""))

    def test_worker_blocks_unavailable_profile_and_popup_without_sending(self):
        for state in (observed(profile=None), observed(connected=False, error="未启动"),
                      observed(controls_ready=False, error="弹窗遮挡")):
            with self.subTest(state=state), patch.object(Worker, "read", return_value=state), \
                    patch("KugouControl.Media.send") as send:
                self.assertIn("error", Worker.operate("toggle"))
                send.assert_not_called()

    def test_worker_only_acknowledges_one_send(self):
        with patch.object(Worker, "read", return_value=observed()) as read, patch("KugouControl.Media.send") as send:
            result = Worker.operate("toggle")
            self.assertTrue(result["sent"])
            self.assertEqual(result["data"]["status"], "paused")
            read.assert_called_once()
            send.assert_called_once_with("toggle")

    def test_send_is_verified_only_after_new_snapshot(self):
        controller = KugouController(runner=lambda *a, **kw: subprocess.CompletedProcess([],0,json.dumps({"data":observed(),"sent":True}),""))
        controller.toggle()
        with self.assertRaises(ControllerCommandFailed): controller.verify_command()
        controller.info = observed(status="playing")
        controller.verify_command()
        self.assertIsNone(controller._pending)

    def test_track_change_in_progress_is_pending_not_failed(self):
        before = observed(status="paused", title="旧歌", artist="甲")
        controller = KugouController(runner=lambda *a, **kw: subprocess.CompletedProcess([],0,json.dumps({"data":before,"sent":True}),""))
        controller.media_next()
        # 没有任何变化：按键没生效。
        with self.assertRaises(ControllerCommandFailed) as unchanged: controller.verify_command()
        self.assertNotIsInstance(unchanged.exception, ControllerCommandPending)
        # 曲目名被清空，或同一首歌从暂停变成播放：酷狗已响应，新曲目还没出来。
        for loading in (observed(status="playing", title="", artist=""), observed(status="playing", title="旧歌", artist="甲")):
            controller.info = loading
            with self.subTest(loading=loading), self.assertRaises(ControllerCommandPending): controller.verify_command()
        # 读取出错时不算“进行中”。
        controller.info = observed(status="playing", title="", artist="", error="弹窗遮挡")
        with self.assertRaises(ControllerCommandFailed) as broken: controller.verify_command()
        self.assertNotIsInstance(broken.exception, ControllerCommandPending)
        controller.info = observed(status="playing", title="新歌", artist="乙")
        controller.verify_command()
        self.assertIsNone(controller._pending)

    def test_toggle_is_never_pending(self):
        controller = KugouController(runner=lambda *a, **kw: subprocess.CompletedProcess([],0,json.dumps({"data":observed(),"sent":True}),""))
        controller.toggle()
        controller.info = observed(title="")
        with self.assertRaises(ControllerCommandFailed) as ctx: controller.verify_command()
        self.assertNotIsInstance(ctx.exception, ControllerCommandPending)


    def _read_with_slider(self, value, maximum, *, broken=False):
        button = SimpleNamespace(CurrentName="暂停", CurrentIsEnabled=True)
        slider = MagicMock()
        pattern = slider.GetCurrentPattern.return_value.QueryInterface.return_value
        pattern.CurrentValue, pattern.CurrentMaximum = value, maximum
        if broken:
            slider.GetCurrentPattern.side_effect = OSError("控件已失效")
        bar = MagicMock()
        bar.element.FindFirst.side_effect = [button, slider]
        automation = MagicMock()
        modules = {"pywinauto.uia_element_info": SimpleNamespace(UIAElementInfo=MagicMock()),
                   "pywinauto.uia_defines": SimpleNamespace(IUIA=lambda: automation)}
        with patch.dict(sys.modules, modules), patch.object(Uia, '_bar', bar), patch.object(Uia, '_hwnd', 123),                 patch.object(Uia, '_cached_at', __import__('time').monotonic()):
            result = Uia.read_controls(123)
        slider.GetCurrentPattern.return_value.QueryInterface.return_value.SetValue.assert_not_called()
        return result

    def test_progress_slider_is_read_as_seconds(self):
        result = self._read_with_slider(2423.0, 17867.0)
        self.assertEqual((result["status"], result["position"], result["duration"]), ("playing", 24.23, 178.67))

    def test_unusable_progress_never_breaks_the_status_reading(self):
        for value, maximum, broken in ((0.0, 0.0, False), (500.0, 100.0, False), (-1.0, 100.0, False), (1.0, 100.0, True)):
            with self.subTest(value=value, maximum=maximum, broken=broken):
                result = self._read_with_slider(value, maximum, broken=broken)
                self.assertEqual((result["status"], result["controls_ready"]), ("playing", True))
                self.assertIsNone(result["position"])
                self.assertIsNone(result["duration"])

    def test_worker_hides_stale_progress_while_the_next_track_loads(self):
        window = {"hwnd": 1, "pid": 2, "version": "10.2.52.25713", "minimized": False, "blocked": False}
        controls = {"status": "playing", "controls_ready": True, "position": 0.0, "duration": 290.56}
        for title, expected in (("酷狗音乐", (None, None)), ("歌手 - 歌名 - 酷狗音乐", (0.0, 290.56))):
            with self.subTest(title=title), patch("KugouControl.Uia.read_controls", return_value=dict(controls)),                     patch.object(Worker, "discover", side_effect=lambda: {**window, "window_title": title}):
                result = Worker.read()
                self.assertEqual((result["position"], result["duration"]), expected)
                self.assertIsNone(result["error"])

    def test_worker_reports_quit_and_recovers_when_kugou_is_reopened(self):
        window = {"hwnd": 9, "pid": 8, "version": "10.2.52.25713", "minimized": False, "blocked": False,
                  "window_title": "歌手 - 歌名 - 酷狗音乐"}
        with patch.object(Worker, "discover", return_value={"error": "酷狗未运行"}):
            gone = Worker.read()
            self.assertEqual((gone["connected"], gone["running"], gone["error"]), (False, False, "酷狗未运行"))
            self.assertEqual(Worker.operate("toggle")["error"], "player_unavailable")
        with patch.object(Worker, "discover", side_effect=lambda: dict(window)),                 patch("KugouControl.Uia.read_controls", return_value={"status": "paused", "controls_ready": True}):
            back = Worker.read()
            self.assertEqual((back["connected"], back["title"], back["status"], back["error"]), (True, "歌名", "paused", None))

    def test_only_verified_capabilities_are_declared_supported(self):
        payload = json.dumps({"data": observed(status="playing", position=24.23, duration=178.67)}, ensure_ascii=False)
        controller = KugouController(runner=lambda *a, **kw: subprocess.CompletedProcess([], 0, payload, ""))
        reading = controller.get_state()
        self.assertEqual((reading.position, reading.duration), (24.23, 178.67))
        caps = {cap["name"]: cap for cap in controller.capabilities()}
        self.assertEqual({name for name, cap in caps.items() if cap["supported"]},
                         {"read_state", "play_pause", "next", "read_position", "seek", "play_track", "kugou_search"})
        self.assertTrue(caps["kugou_search"]["note"])
        controller.info = observed(connected=False, controls_ready=False, error="酷狗未运行")
        # 酷狗搜索查的是网络接口，不依赖酷狗窗口；其余能力都要酷狗能连上。
        self.assertEqual([cap["name"] for cap in controller.capabilities() if cap["supported"]], ["kugou_search"])
        for cap in controller.capabilities()[:6]:
            self.assertEqual(cap["note"], "酷狗未运行")

    def test_play_track_and_seek_go_through_the_worker_and_map_the_song_back(self):
        calls = []
        now = {"data": observed(status="playing", title="Showdown", artist="Britney Spears")}

        def runner(args, **kwargs):
            calls.append((args[-1], kwargs["timeout"]))
            return subprocess.CompletedProcess(args, 0, json.dumps(now, ensure_ascii=False), "")

        controller = KugouController(runner=runner)
        self.assertIsNone(controller.get_state().song_id)
        controller.play_track({"id": 7, "title": "Showdown", "artist": "Britney Spears"})
        action, _, raw = calls[-1][0].partition(" ")
        self.assertEqual((action, json.loads(raw)), ("play_track", {"title": "Showdown", "artist": "Britney Spears"}))
        self.assertGreaterEqual(calls[-1][1], 20)
        self.assertNotIn("\n", calls[-1][0])
        self.assertEqual(controller.get_state().song_id, 7)
        controller.verify_command()  # 结果已在工作进程里核验，这里不再判失败
        controller.seek(42.5)
        self.assertEqual(calls[-1][0].partition(" ")[::2], ("seek", json.dumps({"position": 42.5})))
        self.assertLess(calls[-1][1], 20)
        # 切歌加载中标题为空：先不报曲库歌曲，也不丢掉对应关系。
        now["data"] = observed(status="playing", title="", artist="")
        self.assertIsNone(controller.get_state().song_id)
        now["data"] = observed(status="playing", title="Showdown", artist="Britney Spears")
        self.assertEqual(controller.get_state().song_id, 7)
        # 酷狗自己换了歌：不再对应面板指定的那首，换回来也不算。
        now["data"] = observed(status="playing", title="7 rings", artist="Ariana Grande")
        self.assertIsNone(controller.get_state().song_id)
        now["data"] = observed(status="playing", title="Showdown", artist="Britney Spears")
        self.assertIsNone(controller.get_state().song_id)

    def test_failed_play_track_is_reported_and_maps_no_song(self):
        failed = {"error": "player_command_failed", "message": "第一条不是要播的歌", "data": observed(title="别的歌")}
        controller = KugouController(runner=lambda args, **kw: subprocess.CompletedProcess(
            args, 0, json.dumps(failed if args[-1] != "read" else {"data": failed["data"]}, ensure_ascii=False), ""))
        with self.assertRaisesRegex(ControllerCommandFailed, "第一条不是要播的歌"):
            controller.play_track({"id": 7, "title": "真实歌曲", "artist": "歌手"})
        self.assertIsNone(controller.get_state().song_id)

    def test_song_still_connecting_is_reported_and_mapped_once_it_shows_up(self):
        now = {"error": "track_loading", "message": "酷狗还在连接", "data": observed(status="playing", title="", artist="")}
        controller = KugouController(runner=lambda args, **kw: subprocess.CompletedProcess(
            args, 0, json.dumps(now if args[-1] != "read" else {"data": now["data"]}, ensure_ascii=False), ""))
        with self.assertRaisesRegex(ControllerTrackLoading, "还在连接"):
            controller.play_track({"id": 7, "title": "真实歌曲", "artist": "歌手"})
        self.assertIsNone(controller.get_state().song_id)
        now["data"] = observed(status="playing")
        self.assertEqual(controller.get_state().song_id, 7)

    def test_same_track_tolerates_versions_and_featured_artists(self):
        for got_title, got_artist, title, artist, expected in (
                ("Showdown", "Britney Spears", "showdown", "britney spears", True),
                ("Showdown (Live)", "Britney Spears", "Showdown", "Britney Spears", True),
                ("晴天", "周杰伦", "晴天", "周杰伦", True),
                ("凉凉", "张碧晨、杨宗纬", "凉凉", "杨宗纬/张碧晨", True),
                ("晴天", "周杰伦", "晴天", "", True),
                ("晴天", "刘瑞琦", "晴天", "周杰伦", False),
                ("Unstoppable Sia", "王安卿", "Unstoppable", "Sia", False),
                ("Lucky (feat. Colbie Caillat)", "Jason Mraz", "Lucky", "Colbie Caillat", True),
                ("雨天", "周杰伦", "晴天", "周杰伦", False),
                ("", "", "晴天", "周杰伦", False),
                ("晴天", "周杰伦", "", "周杰伦", False)):
            with self.subTest(got=(got_title, got_artist), want=(title, artist)):
                self.assertEqual(same_track(got_title, got_artist, title, artist), expected)

    def test_worker_routes_parameterised_commands_and_reports_failures(self):
        ready = observed(hwnd=11, pid=22)
        with patch.object(Worker, "read", return_value=ready), patch.object(Track, "play_track") as play, \
                patch.object(Track, "seek") as seek:
            result = Worker.operate('play_track {"title": "晴 天", "artist": "周杰伦"}')
            play.assert_called_once_with(11, 22, "晴 天", "周杰伦")
            self.assertNotIn("error", result)
            Worker.operate('seek {"position": 12.5}')
            seek.assert_called_once_with(11, 12.5)
            seek.side_effect = Track.TrackFailed("进度没有跳到目标位置")
            play.side_effect = Track.TrackLoading("还在连接")
            self.assertEqual(Worker.operate('play_track {"title": "a"}')["error"], "track_loading")
            failed = Worker.operate('seek {"position": 1}')
            self.assertEqual((failed["error"], failed["message"]), ("player_command_failed", "进度没有跳到目标位置"))
        # 酷狗在托盘或版本未验证时，一条消息都不投递。
        for state, code in ((observed(error="酷狗窗口已最小化或收起至托盘，请恢复窗口后控制"), "player_unavailable"),
                            (observed(profile=None), "capability_unsupported"),
                            ({"connected": False, "error": "酷狗未运行"}, "player_unavailable")):
            with self.subTest(code=code), patch.object(Worker, "read", return_value=state), \
                    patch.object(Track, "play_track") as play, patch.object(Track, "seek") as seek:
                self.assertEqual(Worker.operate('play_track {"title": "a"}')["error"], code)
                self.assertEqual(Worker.operate('seek {"position": 1}')["error"], code)
                play.assert_not_called(); seek.assert_not_called()


class FakeWindow:
    """替身酷狗窗口：记录投递的输入，按脚本决定搜索后播出什么。"""

    def __init__(self, *, plays=("歌名", "歌手"), box_text="上次的词", needs_clicks=1, typed_ok=True):
        self.text, self.plays, self.needs_clicks, self.typed_ok = box_text, plays, needs_clicks, typed_ok
        self.now = ("旧歌", "旧歌手")
        self.events, self.searched, self.double_clicks, self.captures = [], None, 0, []
        self.slider_value, self.slider_max, self.seek_works = 1000.0, 20000.0, True

    # Input 替身
    def click(self, hwnd, x, y, *, double=False):
        self.events.append(("double" if double else "click", round(x), round(y)))
        if double and self.searched is not None:
            self.double_clicks += 1
            if self.double_clicks >= self.needs_clicks and self.plays:
                self.now = self.plays
        if not double and 1015 <= y <= 1033 and self.seek_works:
            self.slider_value = (x - 4) / 1530 * self.slider_max

    def capture(self, hwnd, top, bottom):
        self.captures.append((round(top), round(bottom), self.searched))
        return str((self.searched, len(self.events))).encode()  # 每次操作后画面都会变，之后保持不动

    def press(self, hwnd, key, times=1):
        self.events.append(("key", key, times))
        if key == 0x08:
            self.text = self.text[:-times] if times < len(self.text) else ""
        if key == 0x0D:
            self.searched = self.text

    def type_text(self, hwnd, text):
        self.events.append(("type", text))
        if self.typed_ok:
            self.text += text

    # 界面元素替身
    def find(self, element, control_type, name, depth=3):
        rect = lambda l, t, r, b: SimpleNamespace(left=l, top=t, right=r, bottom=b)
        if (control_type, name) == ("Edit", "搜索"):
            return SimpleNamespace(kind="edit", rectangle=rect(619, 84, 841, 132))
        if (control_type, name) == ("Tab", "搜索"):
            return SimpleNamespace(kind="tab") if self.searched is not None else None
        if (control_type, name) == ("Custom", "内嵌页"):
            return SimpleNamespace(kind="page", rectangle=rect(4, 168, 1534, 1023))
        if (control_type, name) == ("Slider", "进度"):
            return SimpleNamespace(kind="slider", rectangle=rect(4, 1015, 1534, 1033))
        return None

    def pattern(self, element, name):
        window = self

        class Value:
            CurrentValue = property(lambda _: window.text)

        class Range:
            CurrentValue = property(lambda _: window.slider_value)
            CurrentMaximum = property(lambda _: window.slider_max)

        return Value() if name == "Value" else Range()

    def patches(self):
        return (patch.object(Track, "Input", self), patch.object(Track, "_find", self.find),
                patch.object(Track, "_pattern", self.pattern), patch.object(Track, "_root", lambda hwnd: None),
                patch.object(Track, "_current", lambda pid: self.now), patch.object(Track.time, "sleep", lambda s: None),
                patch.dict(Track.SEARCH_LAYOUT, {"play_wait": 0.3}))

    def run(self, call):
        from contextlib import ExitStack
        with ExitStack() as stack:
            for item in self.patches():
                stack.enter_context(item)
            return call()


class KugouTrackTests(unittest.TestCase):
    def test_search_replaces_old_text_then_plays_the_first_song(self):
        window = FakeWindow()
        window.run(lambda: Track.play_track(1, 2, "歌名", "歌手"))
        self.assertEqual(window.searched, "歌名 歌手")
        kinds = [event[0] for event in window.events]
        self.assertLess(kinds.index("type"), kinds.index("double"))
        # 页签和第一行按"内嵌页"左上角加偏移定位（搜索框高 48 时不缩放）。
        self.assertIn(("click", 204, 211), window.events)
        self.assertEqual([e for e in window.events if e[0] == "double"], [("double", 564, 429)])
        # 双击前看过结果列表的画面（内嵌页顶部往下 100–620），确认已经换成这次搜索的结果。
        self.assertTrue(window.captures)
        self.assertEqual(set(window.captures), {(268, 788, "歌名 歌手")})

    def test_wrong_first_result_is_reported_with_what_actually_played(self):
        window = FakeWindow(plays=("歌名", "别人"))
        with self.assertRaisesRegex(Track.TrackFailed, "别人 - 歌名"):
            window.run(lambda: Track.play_track(1, 2, "歌名", "歌手"))
        self.assertEqual(window.double_clicks, 1)

    def test_no_result_fails_without_endless_clicking(self):
        window = FakeWindow(plays=None)
        with self.assertRaisesRegex(Track.TrackFailed, "没有开始播放"):
            window.run(lambda: Track.play_track(1, 2, "歌名", "歌手"))
        self.assertLessEqual(window.double_clicks, 2)
        self.assertEqual(window.now, ("旧歌", "旧歌手"))

    def test_song_that_keeps_connecting_is_loading_not_a_plain_failure(self):
        window = FakeWindow(plays=("", ""))
        with self.assertRaisesRegex(Track.TrackLoading, "还在连接"):
            window.run(lambda: Track.play_track(1, 2, "歌名", "歌手"))
        self.assertEqual(window.double_clicks, 1)

    def test_nothing_is_searched_when_the_text_did_not_arrive(self):
        window = FakeWindow(typed_ok=False)
        with patch.dict(Track.SEARCH_LAYOUT, {}), self.assertRaisesRegex(Track.TrackFailed, "没有写进"):
            window.run(lambda: _fast_wait(lambda: Track.play_track(1, 2, "歌名", "歌手")))
        self.assertIsNone(window.searched)
        self.assertEqual(window.double_clicks, 0)
        with self.assertRaisesRegex(Track.TrackFailed, "没有歌名"):
            FakeWindow().run(lambda: Track.play_track(1, 2, "  ", "歌手"))

    def test_seek_clicks_the_matching_point_and_checks_the_result(self):
        window = FakeWindow()
        window.run(lambda: Track.seek(1, 50))  # 200 秒的歌跳到 50 秒 = 进度条四分之一处
        self.assertEqual(window.events, [("click", 386, 1024)])
        self.assertAlmostEqual(window.slider_value, 5000, delta=20)
        window.run(lambda: Track.seek(1, 9999))  # 超出时长时落在结尾前，不触发切歌
        self.assertLess(window.slider_value, window.slider_max)
        window.seek_works = False
        with self.assertRaisesRegex(Track.TrackFailed, "没有跳到"):
            window.run(lambda: _fast_wait(lambda: Track.seek(1, 150)))
        window.slider_max = 0.0
        with self.assertRaisesRegex(Track.TrackFailed, "没有可跳转"):
            window.run(lambda: Track.seek(1, 10))


def _fast_wait(call):
    """把 Track 里"等到条件成立"的超时缩到很短，失败用例不用真的等。"""
    original = Track._wait
    with patch.object(Track, "_wait", lambda check, seconds, step=0.15: original(check, 0.05, 0.01)):
        return call()


class FakeKugou(KugouController):
    def __init__(self):
        def never(*args, **kwargs):
            raise OSError("测试替身不得操作真机酷狗")
        super().__init__(runner=never)
        self.threads = []
        self.played, self.seeks, self.play_failure = [], [], None
        self.reading = PlayerReading(connected=True, status="paused", title="真实歌曲", artist="歌手")
        self.info = observed()
        self.failure = None

    def get_state(self):
        self.threads.append(threading.get_ident())
        return self.reading

    def toggle(self):
        self.threads.append(threading.get_ident())
        if self.failure:
            self.reading = replace(self.reading, connected=False, status="unknown", error="已断开")
            raise self.failure
        self.reading = replace(self.reading, status="playing" if self.reading.status == "paused" else "paused")

    def play_track(self, song):
        if self.play_failure:
            raise self.play_failure
        self.played.append(song["id"])
        self.reading = replace(self.reading, status="playing", title=song["title"], artist=song["artist"], song_id=song["id"])

    def seek(self, position):
        self.seeks.append(position)
        self.reading = replace(self.reading, position=position)

    def close(self):
        self.threads.append(threading.get_ident())


class FakePpt:
    state = SimpleNamespace(app="powerpoint", connected=False)
    async def start(self): pass
    async def close(self): pass


class KugouServiceTests(unittest.TestCase):
    def test_delayed_state_is_re_read_without_resending(self):
        class Delayed(FakeKugou):
            verifications = 0
            sends = 0
            def toggle(self):
                self.sends += 1
                super().toggle()
            def verify_command(self):
                self.verifications += 1
                if self.verifications < 5:
                    raise ControllerCommandFailed('酷狗正在加载')
        async def scenario():
            db = Database(':memory:', seed=False); db.connect()
            fake = Delayed()
            service = PlayerService(db, controller_name='kugou', factory=lambda: fake, poll_interval=100)
            await service.start()
            try:
                result = await service.command(PlayerCommand(action='toggle'))
                self.assertEqual(result['state']['status'], 'playing')
                self.assertEqual(fake.sends, 1)
                self.assertEqual(fake.verifications, 5)
            finally:
                await service.close(); db.close()
        asyncio.run(scenario())

    def test_slow_track_change_waits_longer_only_while_pending(self):
        class Slow(FakeKugou):
            def __init__(self, pending_rounds, exc):
                super().__init__(); self.rounds = pending_rounds; self.exc = exc; self.verifications = 0; self.sends = 0
            def media_next(self): self.sends += 1
            def verify_command(self):
                self.verifications += 1
                if self.verifications <= self.rounds: raise self.exc('未完成')
        async def run(fake):
            db = Database(':memory:', seed=False); db.connect()
            service = PlayerService(db, controller_name='kugou', factory=lambda: fake, poll_interval=100)
            service.verification_delays = (0, 0.01, 0.01); service.pending_delays = (0.01, 0.01, 0.01)
            await service.start()
            try:
                await service.command(PlayerCommand(action='media_next'))
            finally:
                await service.close(); db.close()
        # 加载较慢：超过常规等待，但在延长等待内完成，只发送一次。
        slow = Slow(4, ControllerCommandPending); asyncio.run(run(slow))
        self.assertEqual((slow.sends, slow.verifications), (1, 5))
        # 没有任何响应：常规等待结束就判失败，不占用延长等待。
        dead = Slow(99, ControllerCommandFailed)
        with self.assertRaises(PlayerConflict): asyncio.run(run(dead))
        self.assertEqual((dead.sends, dead.verifications), (1, 3))
        # 一直在加载：延长等待用完后判失败。
        stuck = Slow(99, ControllerCommandPending)
        with self.assertRaises(PlayerConflict): asyncio.run(run(stuck))
        self.assertEqual((stuck.sends, stuck.verifications), (1, 6))

    def test_commands_websocket_errors_and_capabilities(self):
        db = Database(":memory:", seed=False)
        fake = FakeKugou()
        service = PlayerService(db, controller_name="kugou", factory=lambda: fake, poll_interval=100)
        with TestClient(create_app(FakePpt(), db, service)) as client:
            self.assertFalse(client.get("/api/player/state").json()["state"]["auto_next"])
            with client.websocket_connect("/ws/player") as ws:
                ws.receive_json()
                response = client.post("/api/player/command", json={"action": "toggle"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(ws.receive_json()["state"]["status"], "playing")
                for error, status, code in [(PlayerUnavailable("未启动"), 503, "player_unavailable"),
                                            (ControllerTimeout("操作超时"), 504, "command_timeout"),
                                            (ControllerCommandFailed("未核验"), 409, "player_command_failed")]:
                    fake.failure = error
                    response = client.post("/api/player/command", json={"action": "toggle"})
                    self.assertEqual(response.status_code, status)
                    self.assertEqual(response.json()["detail"]["code"], code)
                    self.assertFalse(client.get("/api/player/state").json()["state"]["connected"])
            diag = client.get("/api/diagnostics").json()
            self.assertEqual(diag["kugou"]["version"], "10.2.52.25713")
            self.assertEqual(client.patch("/api/player/settings", json={"auto_next": True}).status_code, 409)
            self.assertEqual(client.post("/api/player/command", json={"action": "media_next", "song_id": 1}).status_code, 422)
        self.assertEqual(len(set(fake.threads)), 1)
        self.assertNotEqual(fake.threads[0], threading.get_ident())

    def test_queue_and_history_change_only_after_kugou_confirms_the_song(self):
        async def scenario():
            db = Database(":memory:", seed=False); db.connect()
            first = SongRepository(db).create("歌曲", "歌手", duration=10)
            second = SongRepository(db).create("第二首", "歌手", duration=10)
            fake = FakeKugou()
            service = PlayerService(db, controller_name="kugou", factory=lambda: fake, poll_interval=100)
            await service.start()
            try:
                await service.enqueue(first["id"], "end")
                await service.enqueue(second["id"], "end")
                # 酷狗没播出要的歌：报错，队列和已播都不动。
                fake.play_failure = ControllerCommandFailed("酷狗搜索的第一条不是要播的歌")
                for args in ({"action": "play", "song_id": first["id"]}, {"action": "next_in_queue"}):
                    with self.assertRaisesRegex(PlayerConflict, "不是要播的歌"):
                        await service.command(PlayerCommand(**args))
                self.assertEqual(len(QueueRepository(db).list_items()), 2)
                self.assertEqual(await service.history(), [])
                # 核验通过：出队、记已播、状态带上曲库歌曲。
                fake.play_failure = None
                result = await service.command(PlayerCommand(action="next_in_queue"))
                self.assertEqual((result["state"]["song_id"], result["state"]["status"]), (first["id"], "playing"))
                self.assertEqual([row["song_id"] for row in QueueRepository(db).list_items()], [second["id"]])
                self.assertEqual([row["song_id"] for row in await service.history()], [first["id"]])
                await service.command(PlayerCommand(action="play", song_id=second["id"]))
                await service.command(PlayerCommand(action="previous"))
                self.assertEqual(fake.played, [first["id"], second["id"], first["id"]])
                self.assertEqual(len(await service.history()), 2)
                # 酷狗还在连接：先报出来，队列和已播不动；之后读到这首歌在播，再补记。
                third = SongRepository(db).create("第三首", "歌手", duration=10)
                await service.enqueue(third["id"], "end")
                fake.play_failure = ControllerTrackLoading("酷狗还在连接「第三首 歌手」")
                fake.reading = replace(fake.reading, title="", artist="", song_id=None)
                with self.assertRaisesRegex(PlayerConflict, "还在连接"):
                    await service.command(PlayerCommand(action="next_in_queue"))
                self.assertEqual(len(QueueRepository(db).list_items()), 1)
                self.assertEqual(len(await service.history()), 2)
                fake.reading = replace(fake.reading, status="playing", title="第三首", artist="歌手", song_id=third["id"])
                await service.refresh()
                self.assertEqual(service.state.queue, ())
                self.assertEqual([row["song_id"] for row in await service.history()][0], third["id"])
                await service.refresh()
                self.assertEqual(len(await service.history()), 3)
                # 连接中的歌最后播出来的是别的：不补记。
                fake.reading = replace(fake.reading, title="", artist="", song_id=None)
                with self.assertRaisesRegex(PlayerConflict, "还在连接"):
                    await service.command(PlayerCommand(action="play", song_id=first["id"]))
                # 这首还在连接、没记进已播：「上一首」回到已播里最新的一条，不多跳。
                fake.play_failure = None
                await service.command(PlayerCommand(action="previous"))
                self.assertEqual(fake.played[-1], third["id"])
                fake.play_failure = ControllerTrackLoading("酷狗还在连接")
                fake.reading = replace(fake.reading, title="", artist="", song_id=None)
                with self.assertRaisesRegex(PlayerConflict, "还在连接"):
                    await service.command(PlayerCommand(action="play", song_id=first["id"]))
                fake.reading = replace(fake.reading, title="别的歌", artist="别人")
                await service.refresh()
                fake.reading = replace(fake.reading, title="歌曲", artist="歌手", song_id=first["id"])
                await service.refresh()
                self.assertEqual(len(await service.history()), 3)
                fake.play_failure = None
                await service.command(PlayerCommand(action="seek", position=42.5))
                self.assertEqual(fake.seeks, [42.5])
                self.assertFalse(service.state.auto_next)
                fake.reading = PlayerReading(connected=False, status="unknown", error="未启动")
                await service.refresh()
                self.assertFalse(service.state.connected)
                fake.reading = PlayerReading(connected=True, status="paused", title="重连")
                await service.refresh()
                self.assertTrue(service.state.connected)
                self.assertEqual(service.state.title, "重连")
            finally:
                await service.close(); db.close()
        asyncio.run(scenario())

    def test_switch_is_serial_and_persisted(self):
        async def scenario():
            from Database import SettingsRepository
            db = Database(":memory:", seed=False); db.connect()
            fake = FakeKugou()
            service = PlayerService(db, controller_name="kugou", factory=lambda: fake)
            await service.start()
            try:
                await service.switch_controller("mock")
                self.assertEqual(service.state.controller, "mock")
                self.assertEqual(SettingsRepository(db).get("player.controller"), "mock")
            finally:
                await service.close(); db.close()
            self.assertEqual(len(set(fake.threads)), 1)
        asyncio.run(scenario())
