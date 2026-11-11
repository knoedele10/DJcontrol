"""PPT 控制协议。页码在接口中统一从 1 开始。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

PptApp = Literal["powerpoint", "wps"]


class PptError(Exception):
    code = "ppt_error"


class PptUnavailable(PptError):
    code = "ppt_unavailable"


class PptCommandError(PptError):
    code = "ppt_command_failed"


@dataclass(frozen=True)
class PptState:
    app: PptApp
    connected: bool = False
    document_id: str = ""
    file: str = ""
    current_slide: int | None = None
    total_slides: int = 0
    running: bool = False
    black: bool = False
    error: str | None = None


class PptController(ABC):
    """所有方法由同一个工作线程调用，包括 close。"""

    app: PptApp

    @abstractmethod
    def get_state(self) -> PptState: ...

    @abstractmethod
    def export_slide(self, slide: int, width: int = 1280, document_id: str | None = None) -> bytes: ...

    @abstractmethod
    def next(self) -> None: ...

    @abstractmethod
    def previous(self) -> None: ...

    @abstractmethod
    def goto_slide(self, slide: int) -> None: ...

    @abstractmethod
    def set_black(self, enabled: bool) -> None: ...

    @abstractmethod
    def start(self, slide: int | None = None) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...
