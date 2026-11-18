"""播放器控制器接口与能力声明。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal


class CapabilityUnsupported(Exception):
    code = "capability_unsupported"

    def __init__(self, capability: str) -> None:
        self.capability = capability
        super().__init__(f"当前控制器不支持：{capability}")


class PlayerUnavailable(Exception):
    """外部播放器或当前窗口不可用。"""


class ControllerTimeout(Exception):
    """操作可能已执行，禁止自动重试。"""


class ControllerCommandFailed(Exception):
    """已经发送，但没有观察到预期变化。"""


class ControllerCommandPending(ControllerCommandFailed):
    """已经看到播放器开始响应，预期结果还没出现；值得多等一会儿再判失败。"""


class ControllerTrackLoading(ControllerCommandFailed):
    """播放器已经点开指定歌曲但还在加载；之后读到这首歌在播，才算播放成功。"""


@dataclass(frozen=True)
class PlayerReading:
    connected: bool
    status: Literal["playing", "paused", "stopped", "unknown"]
    title: str = ""
    artist: str = ""
    song_id: int | None = None
    position: float | None = None
    duration: float | None = None
    error: str | None = None
    via: Literal["playlist", "search"] | None = None


class PlayerController(ABC):
    name: Literal["mock", "kugou"]

    @abstractmethod
    def capabilities(self) -> list[dict]: ...

    @abstractmethod
    def get_state(self) -> PlayerReading: ...

    def play_track(self, song: dict) -> None:
        raise CapabilityUnsupported("play_track")

    def toggle(self) -> None:
        raise CapabilityUnsupported("play_pause")

    def seek(self, position: float) -> None:
        raise CapabilityUnsupported("read_position")

    def media_next(self) -> None:
        raise CapabilityUnsupported("next")

    def media_previous(self) -> None:
        raise CapabilityUnsupported("next")

    def verify_command(self) -> None:
        """服务刷新后核验上一次命令，模拟控制器无需额外核验。"""

    def configure_playlist(self, name: str) -> None:
        """仅保存配置；界面探测由显式刷新触发。"""

    def playlist_snapshot(self) -> dict:
        return {"name": "", "route": None, "supported": False, "can_add": False,
                "complete": False, "tracks": [], "note": "请切换到酷狗控制器"}

    def refresh_playlist(self) -> dict:
        raise CapabilityUnsupported("play_from_playlist")

    def add_to_playlist(self, song: dict) -> dict:
        raise CapabilityUnsupported("add_to_playlist")

    @abstractmethod
    def close(self) -> None: ...
