"""M2 曲库、搜索、活动组和分类的严格请求结构。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SongCreate(StrictModel):
    title: StrictStr = Field(min_length=1, max_length=200)
    artist: StrictStr = Field(min_length=1, max_length=200)
    bpm: int | None = Field(default=None, ge=1, le=400, strict=True)
    duration: int = Field(default=0, ge=0, strict=True)
    note: StrictStr = Field(default="", max_length=1000)


class SongPatch(StrictModel):
    title: StrictStr | None = Field(default=None, min_length=1, max_length=200)
    artist: StrictStr | None = Field(default=None, min_length=1, max_length=200)
    bpm: int | None = Field(default=None, ge=1, le=400, strict=True)
    duration: int | None = Field(default=None, ge=0, strict=True)
    note: StrictStr | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def non_empty(self) -> "SongPatch":
        if not self.model_fields_set:
            raise ValueError("至少提供一个要修改的字段")
        return self


class ImportSongs(StrictModel):
    text: StrictStr = Field(min_length=1, max_length=100_000)
    category_ids: list[StrictStr] = Field(default_factory=list, max_length=100)


class KugouImport(StrictModel):
    key: StrictStr = Field(min_length=1, max_length=200)


class GroupCreate(StrictModel):
    name: StrictStr = Field(min_length=1, max_length=20)
    color: StrictStr | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class GroupPatch(StrictModel):
    name: StrictStr | None = Field(default=None, min_length=1, max_length=20)
    color: StrictStr | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")

    @model_validator(mode="after")
    def non_empty(self) -> "GroupPatch":
        if not self.model_fields_set:
            raise ValueError("至少提供一个要修改的字段")
        return self


class GroupOrderRequest(StrictModel):
    group_ids: list[StrictStr] = Field(min_length=0, max_length=500)


class CategoryOrderRequest(StrictModel):
    category_ids: list[StrictStr] = Field(min_length=0, max_length=500)


class CategoryCreate(StrictModel):
    name: StrictStr = Field(min_length=1, max_length=20)
    color: StrictStr | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    song_ids: list[StrictInt] = Field(default_factory=list, max_length=1000)


class CategoryPatch(StrictModel):
    name: StrictStr | None = Field(default=None, min_length=1, max_length=20)
    color: StrictStr | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")

    @model_validator(mode="after")
    def non_empty(self) -> "CategoryPatch":
        if not self.model_fields_set:
            raise ValueError("至少提供一个要修改的字段")
        return self


class CategorySong(StrictModel):
    song_id: StrictInt = Field(ge=0)


class CategorySongs(StrictModel):
    song_ids: list[StrictInt] = Field(max_length=1000)

