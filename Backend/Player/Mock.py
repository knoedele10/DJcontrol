"""真实时间推进的模拟播放器，供 M3 联调和自动化测试使用。"""

from __future__ import annotations

import time

from Player.Base import PlayerController, PlayerReading


class MockPlayerController(PlayerController):
    name = "mock"

    def __init__(self) -> None:
        self._reading = PlayerReading(connected=True, status="stopped")
        self._last_tick = time.monotonic()

    def capabilities(self) -> list[dict]:
        return [
            {"name": "read_state", "label": "读取当前曲目", "supported": True, "verified": True, "note": "模拟控制器实时提供"},
            {"name": "play_pause", "label": "播放 / 暂停", "supported": True, "verified": True, "note": "模拟控制器"},
            {"name": "next", "label": "上一首 / 下一首", "supported": True, "verified": True, "note": "由后端队列执行"},
            {"name": "play_track", "label": "按歌名搜索并播放", "supported": True, "verified": True, "note": "模拟控制器"},
            {"name": "read_position", "label": "读取播放进度", "supported": True, "verified": True, "note": "模拟控制器实时提供"},
            {"name": "seek", "label": "跳转播放进度", "supported": True, "verified": True, "note": "模拟控制器"},
        ]

    def _tick(self) -> None:
        now = time.monotonic()
        elapsed = max(0.0, now - self._last_tick)
        self._last_tick = now
        if self._reading.status != "playing" or self._reading.position is None or self._reading.duration is None:
            return
        position = self._reading.position + elapsed
        if position >= self._reading.duration:
            position = self._reading.duration
            self._reading = PlayerReading(**{**self._reading.__dict__, "position": position, "status": "stopped"})
        else:
            self._reading = PlayerReading(**{**self._reading.__dict__, "position": position})

    def get_state(self) -> PlayerReading:
        self._tick()
        return self._reading

    def play_track(self, song: dict) -> None:
        self._last_tick = time.monotonic()
        self._reading = PlayerReading(
            connected=True, status="playing", song_id=int(song["id"]), title=str(song["title"]),
            artist=str(song["artist"]), position=0.0, duration=float(song["duration"]),
        )

    def toggle(self) -> None:
        self._tick()
        if self._reading.status == "playing":
            self._reading = PlayerReading(**{**self._reading.__dict__, "status": "paused"})
        elif self._reading.status in ("paused", "stopped") and self._reading.song_id is not None:
            self._last_tick = time.monotonic()
            self._reading = PlayerReading(**{**self._reading.__dict__, "status": "playing"})
        else:
            self._reading = PlayerReading(connected=True, status="stopped")

    def seek(self, position: float) -> None:
        self._tick()
        if self._reading.duration is None:
            return
        clamped = max(0.0, min(float(position), self._reading.duration))
        self._reading = PlayerReading(**{**self._reading.__dict__, "position": clamped})
        self._last_tick = time.monotonic()

    def close(self) -> None:
        self._reading = PlayerReading(connected=False, status="unknown", error="模拟播放器已关闭")
