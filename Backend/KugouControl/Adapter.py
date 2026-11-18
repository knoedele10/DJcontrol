"""隔离阻塞的真机调用，超时杀掉子进程，下一次只读检测可自动恢复。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import subprocess
import sys
from typing import Callable

from Player.Base import CapabilityUnsupported, ControllerCommandFailed, ControllerCommandPending, ControllerTimeout, ControllerTrackLoading, PlayerController, PlayerReading, PlayerUnavailable
from KugouControl.Process import WorkerProcess
from KugouControl.Profiles import exact_track, same_track

logger = logging.getLogger(__name__)
PLAY_TRACK_TIMEOUT = 24


class KugouController(PlayerController):
    name = "kugou"

    def __init__(self, *, timeout: float = 4, runner: Callable | None = None) -> None:
        self.timeout = timeout
        self._runner = runner or WorkerProcess()
        self.info: dict = {}
        self._pending: tuple[str, dict] | None = None
        self._track: dict | None = None  # 面板最近一次指定播放的曲库歌曲，用来把酷狗标题对回曲库
        self._playlist = self._empty_playlist('')
        self._playlist_checked = False
        self.last_result: dict = {}
        self.play_result: dict = {}
        self._via: str | None = None

    @staticmethod
    def _empty_playlist(name):
        return {'name': name, 'route': None, 'supported': False, 'can_add': False,
                'tracks': [], 'complete': False, 'note': '尚未检测，请在设置页刷新歌单' if name else '未启用歌单',
                'add_note': '尚未检测加歌菜单'}

    def configure_playlist(self, name: str) -> None:
        if name != self._playlist['name']:
            self._playlist = self._empty_playlist(name)
            self._playlist_checked = False

    def playlist_snapshot(self) -> dict:
        return dict(self._playlist)

    def refresh_playlist(self) -> dict:
        name = self._playlist['name']
        self._playlist_checked = True
        self._playlist = self._empty_playlist(name)
        if name:
            try:
                self._exchange('playlist_refresh ' + json.dumps({'playlist': name}, ensure_ascii=False))
                state = self.last_result.get('playlist')
                if not isinstance(state, dict):
                    raise PlayerUnavailable('歌单探测没有返回有效结果')
                self._playlist = state
            except Exception as exc:
                self._playlist['note'] = str(exc)
                raise
        return self.playlist_snapshot()

    def add_to_playlist(self, song: dict) -> dict:
        if not self._playlist['can_add']:
            raise CapabilityUnsupported(self._playlist.get('add_note', 'add_to_playlist'))
        self._pending = self._track = None
        self._via = None
        self._exchange('playlist_add ' + json.dumps({'playlist': self._playlist['name'],
                       'title': song['title'], 'artist': song['artist']}, ensure_ascii=False))
        result = self.last_result.get('result', {'status': 'unverified', 'message': '加歌结果未核验', 'in_playlist': None})
        if result.get('status') == 'added':
            self._playlist['add_verified'] = True
        return result

    def _exchange(self, action: str) -> dict:
        # 搜歌要等结果页和歌曲加载，没缓存的歌最长等十几秒；其余操作一两秒内完成。
        playlist_play = action.startswith('play_track ') and bool(json.loads(action.partition(' ')[2]).get('playlist'))
        timeout = {"read": self.timeout, "play_track": 44 if playlist_play else max(self.timeout * 2, PLAY_TRACK_TIMEOUT),
                   'playlist_refresh': 20, 'playlist_add': 48}.get(
            action.partition(" ")[0], self.timeout * 2)
        try:
            child = self._runner(
                [sys.executable, "-X", "utf8", "-m", "KugouControl.Worker", action],
                cwd=str(Path(__file__).resolve().parents[1]), capture_output=True,
                text=True, encoding="utf-8", timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            payload = json.loads(child.stdout)
            if child.returncode or not isinstance(payload, dict):
                raise ValueError("worker failed")
            self.info = payload.get("data", {})
            self.last_result = payload
            if child.stderr:
                logger.debug("酷狗探测日志：%s", child.stderr)
            if payload.get("error") == "capability_unsupported":
                raise CapabilityUnsupported(payload.get('message', '当前版本未验证'))
            if payload.get("error") == "track_loading":
                raise ControllerTrackLoading(payload["message"])
            if payload.get("error") == "player_command_failed":
                raise ControllerCommandFailed(payload["message"])
            if payload.get("error") == "command_timeout":
                raise ControllerTimeout(payload["message"])
            if payload.get("error"):
                raise PlayerUnavailable(payload.get("message", "酷狗命令未核验"))
            return self.info
        except subprocess.TimeoutExpired as exc:
            message = ('加歌超时，结果和播放状态尚未核验，请在酷狗中检查并暂停；不会自动重试'
                       if action.startswith('playlist_add ') else '酷狗读取/操作超时，请检查窗口；命令不会自动重试')
            self.info = {"error": message}
            raise ControllerTimeout(self.info["error"]) from exc
        except (OSError, ValueError) as exc:
            logger.exception("酷狗隔离进程不可用")
            self.info = {"error": "酷狗控制进程不可用，请检查 Python 依赖"}
            raise PlayerUnavailable(self.info["error"]) from exc

    def capabilities(self) -> list[dict]:
        ready = bool(self.info.get("profile") and self.info.get("controls_ready") and not self.info.get("error"))
        # 自检没通过时，四项实读/媒体键能力都写同一个原因，设置页能直接看到为什么不可用。
        down = self.info.get("error") or "等待酷狗连接自检"
        return [
            {"name": name, "label": label, "supported": supported,
             "verified": supported and (self._playlist.get('play_verified', False) if name == 'play_from_playlist'
                                         else self._playlist.get('add_verified', False) if name == 'add_to_playlist' else True), "note": note}
            for name, label, supported, note in (
                ("read_state", "读取当前曲目", ready, "窗口标题与播放栏实读" if ready else down),
                ("play_pause", "播放 / 暂停", ready, "媒体键；每条命令执行后核验，不自动重试" if ready else down),
                ("next", "酷狗自身上一首 / 下一首", ready, "媒体键；控制酷狗自己的播放列表，与面板待播队列分开" if ready else down),
                ("read_position", "读取播放进度", ready, "播放栏进度条实读，精确到约半秒；切歌加载的几秒内暂无进度" if ready else down),
                ("seek", "跳转播放进度", ready, "向酷狗进度条投递点击，不抢焦点；跳转后核验进度" if ready else down),
                ("play_track", "按歌名搜索并播放", ready,
                 "在酷狗搜「歌名 歌手」播单曲第一条，按窗口标题核验；不抢焦点，一般 5–8 秒；网络慢时先提示‘还在连接’，播出来后面板自动更新" if ready else down),
                ("kugou_search", "酷狗搜索", True, "查酷狗的网络搜索接口，不操作酷狗窗口；结果可直接播、排队或收进曲库"),
                ('play_from_playlist', '歌单内直接播放', ready and self._playlist['supported'], self._playlist['note'] if ready else down),
                ('add_to_playlist', '加入演出歌单', ready and self._playlist['can_add'], self._playlist['add_note'] if ready else down),
            )
        ]

    def get_state(self) -> PlayerReading:
        try:
            info = self._exchange("read")
            if (not self._playlist_checked and self._playlist['name'] and not self._playlist['supported']
                    and info.get('controls_ready') and not info.get('error')):
                try:
                    self.refresh_playlist()
                    info = self.info
                except (CapabilityUnsupported, ControllerCommandFailed, ControllerTimeout, PlayerUnavailable) as exc:
                    # 歌单探测失败不影响已核验过的基本播放能力。
                    logger.warning('歌单初始化不可用：%s', exc)
                    self.info = info
            track = self._track
            matches = exact_track if self._via == 'playlist' else same_track
            if track and info.get("title") and not matches(info["title"], info.get("artist", ""), track["title"], track["artist"]):
                track = self._track = None  # 酷狗已经换歌，不再对应面板指定的那首
                self._via = None
            if track and self._via == 'playlist' and info.get('title') and info.get('status') == 'playing':
                self._playlist['play_verified'] = True
            return PlayerReading(connected=info.get("connected", False), status=info.get("status", "unknown"),
                                 title=info.get("title", ""), artist=info.get("artist", ""),
                                 song_id=track["id"] if track and info.get("title") else None,
                                 position=info.get("position"), duration=info.get("duration"), error=info.get("error"),
                                 via=self._via if track else None)
        except (ControllerTimeout, PlayerUnavailable) as exc:
            return PlayerReading(connected=False, status="unknown", error=str(exc))

    def play_track(self, song: dict) -> None:
        self._pending = None
        self._track = None
        self._via = None
        self.play_result = {}
        title, artist = song.get("title") or "", song.get("artist") or ""
        track = {"id": song.get("id"), "title": title, "artist": artist}
        options = {'title': title, 'artist': artist}
        if self._playlist['supported']:
            options.update(playlist=self._playlist['name'], in_playlist=song.get('in_playlist'))
        try:
            self._exchange("play_track " + json.dumps(options, ensure_ascii=False))
        except ControllerTrackLoading:
            self._track = track  # 还在连接：等标题出来，对得上就认这首
            self._via = self.last_result.get('result', {}).get('via', 'search')
            self.play_result = dict(self.last_result.get('result', {}))
            raise
        self._track = track
        self._via = self.last_result.get('result', {}).get('via', 'search')
        self.play_result = dict(self.last_result.get('result', {}))
        if self._via == 'playlist':
            self._playlist['play_verified'] = True

    def seek(self, position: float) -> None:
        self._pending = None
        self._exchange("seek " + json.dumps({"position": position}))

    def toggle(self) -> None:
        self._send("toggle")

    def media_next(self) -> None:
        self._send("media_next")

    def media_previous(self) -> None:
        self._send("media_previous")

    def _send(self, action: str) -> None:
        self._pending = None
        before = self._exchange(action)
        self._pending = (action, before)

    def verify_command(self) -> None:
        if self._pending is None:
            return
        action, before = self._pending
        after = self.info
        verified = (after.get("status") in ("playing", "paused") and after.get("status") != before.get("status")) if action == "toggle" else (
            bool(after.get("title")) and (after.get("title"), after.get("artist")) != (before.get("title"), before.get("artist")))
        healthy = after.get("connected") and not after.get("error")
        if healthy and not verified and action != "toggle" and (
                not after.get("title") or after.get("status") != before.get("status")):
            # 曲目名被清空或播放状态变了，说明酷狗收到了按键，正在加载下一首（未缓存的歌可能要几秒）。
            raise ControllerCommandPending("酷狗已响应切歌，但一直没有显示新曲目；请检查网络，或确认播放列表里不止一首歌")
        if not (healthy and verified):
            raise ControllerCommandFailed("按键已发送，但未核验到酷狗状态变化；请检查媒体快捷键设置和其他播放器")
        self._pending = None

    def close(self) -> None:
        if isinstance(self._runner, WorkerProcess):
            self._runner.close()
        self.info = {}
        self._pending = None
        self._track = None
