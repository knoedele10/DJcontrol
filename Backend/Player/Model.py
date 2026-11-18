"""M3 播放器和队列请求结构。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QueueCreate(StrictModel):
    song_id: StrictInt = Field(ge=0)
    position: Literal["end", "next"] = "end"


class QueueOrder(StrictModel):
    item_ids: list[StrictStr] = Field(max_length=1000)


class PlayerCommand(StrictModel):
    action: Literal["play", "toggle", "next_in_queue", "previous", "seek", "media_next", "media_previous"]
    song_id: StrictInt | None = Field(default=None, ge=0)
    position: StrictFloat | StrictInt | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_arguments(self) -> "PlayerCommand":
        if self.action == "play" and self.song_id is None:
            raise ValueError("play 需要 song_id")
        if self.action == "seek" and self.position is None:
            raise ValueError("seek 需要 position")
        if self.action not in ("play", "seek") and (self.song_id is not None or self.position is not None):
            raise ValueError("当前 action 不接受附加参数")
        return self


class PlayerSettings(StrictModel):
    auto_next: StrictBool


class ControllerSettings(StrictModel):
    name: Literal["mock", "kugou"]
    playlist: StrictStr | None = Field(default=None, max_length=100)


class PlaylistAdd(StrictModel):
    song_id: StrictInt = Field(ge=0)


class TutorialProgress(StrictModel):
    """已看完的教程版本；0 表示从没看完，首次打开面板时会强制显示教程。"""

    completed_version: StrictInt = Field(ge=0, le=1000)

