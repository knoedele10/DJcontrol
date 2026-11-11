"""PPT HTTP 请求结构。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from PptControl import PptApp


class PptConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app: PptApp


class PptBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    song_id: int | None = Field(ge=0, strict=True)


class PptSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    link_music: bool = Field(strict=True)


class PptBindingImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bindings: dict[str, dict[str, int | None]]


class PptCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["next", "previous", "goto", "black", "start", "stop"]
    slide: int | None = Field(default=None, ge=1, strict=True)
    enabled: bool | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def validate_arguments(self) -> "PptCommand":
        if self.action == "goto" and self.slide is None:
            raise ValueError("跳页需要 slide 页码")
        if self.action == "black" and self.enabled is None:
            raise ValueError("黑屏需要 enabled 状态")
        if self.slide is not None and self.action not in ("goto", "start"):
            raise ValueError("只有 goto/start 接受 slide")
        if self.enabled is not None and self.action != "black":
            raise ValueError("只有 black 接受 enabled")
        return self
