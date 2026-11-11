"""PPT 页面绑定歌曲与翻页联动：绑定存数据库，翻页由后端触发播放，开多少个面板窗口都只播一次。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from Database import Database, PptBindingRepository, SettingsRepository, SongRepository
from PptControl import PptCommandError, PptState, PptUnavailable

logger = logging.getLogger(__name__)
LINK_MUSIC_KEY = "ppt.link_music"


class PptLink:
    """play(song_id) 负责真正播放：已经在播这首就什么都不做并返回 False，失败抛异常（消息给用户看）。"""

    def __init__(self, database: Database, ppt: Any, play: Callable[[int], Awaitable[bool]]) -> None:
        self.database = database
        self.ppt = ppt
        self._play = play
        self.link_music = bool(SettingsRepository(database).get(LINK_MUSIC_KEY, True))
        self._document: tuple[str, str] = ("", "")
        self._bindings: dict[int, int] = {}
        self._last: dict[str, Any] | None = None  # 最近一次联动的结果，随状态推给面板
        self._seq = 0
        self._wanted: tuple[int, int] | None = None  # 连续翻页时只播最后停下的那一页
        self._task: asyncio.Task | None = None
        ppt.extras = self.extras
        ppt.on_change = self.on_change

    def extras(self) -> dict:
        return {"bindings": {str(slide): song for slide, song in sorted(self._bindings.items())},
                "link_music": self.link_music, "link": self._last}

    def _load(self, state: PptState) -> None:
        self._document = (state.app, state.document_id)
        self._bindings = PptBindingRepository(self.database).list(*self._document) if state.document_id else {}

    def on_change(self, old: PptState, new: PptState) -> None:
        """PPT 实际状态每次变化时调用（面板翻页、翻页笔、直接在 PPT 里点都走这里）。"""

        same_document = bool(new.document_id) and (old.app, old.document_id) == (new.app, new.document_id)
        if not same_document or self._document != (new.app, new.document_id):
            self._load(new)
        # 首次连接、断线重连、换文稿都不算翻页：前一个状态必须是同一份文稿并且读得到页码。
        if not (same_document and old.connected and new.connected and new.running and self.link_music
                and old.current_slide is not None and new.current_slide is not None
                and old.current_slide != new.current_slide):
            return
        self._load(new)  # 歌被删掉后绑定会被清空，触发前按数据库里的为准
        song_id = self._bindings.get(new.current_slide)
        if song_id is None:
            return
        self._wanted = (new.current_slide, song_id)
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._run())

    def _report(self, slide: int, song_id: int, status: str, message: str = "") -> None:
        self._seq += 1
        self._last = {"seq": self._seq, "slide": slide, "song_id": song_id, "status": status, "message": message}
        self.ppt.touch()

    async def _run(self) -> None:
        while self._wanted is not None:
            slide, song_id = self._wanted
            self._wanted = None
            try:
                if not await self._play(song_id):
                    continue  # 这首已经在播
                self._report(slide, song_id, "played")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("翻到第 %s 页联动播放失败：%s", slide, exc)
                self._report(slide, song_id, "failed", str(exc) or "播放失败")

    def _current(self) -> PptState:
        state: PptState = self.ppt.state
        if not state.connected or not state.document_id:
            raise PptUnavailable(state.error or "没有打开的演示文稿，不能绑定歌曲")
        return state

    async def bind(self, slide: int, song_id: int | None) -> dict:
        state = self._current()
        if slide > state.total_slides:
            raise PptCommandError("绑定的页码超出文稿页数")
        if song_id is not None and SongRepository(self.database).get(song_id) is None:
            raise PptCommandError("歌曲不存在，可能已被删除")
        PptBindingRepository(self.database).set(state.app, state.document_id, slide, song_id)
        self._load(state)
        self.ppt.touch()
        return self.ppt.snapshot()

    async def set_link_music(self, enabled: bool) -> dict:
        SettingsRepository(self.database).set(LINK_MUSIC_KEY, enabled)
        self.link_music = enabled
        self.ppt.touch()
        return self.ppt.snapshot()

    async def import_bindings(self, bindings: dict[str, dict[str, int | None]]) -> dict:
        """把浏览器里旧的绑定一次性搬进来：后端已经有记录的页不覆盖，歌不存在的跳过。"""

        repo, songs, imported = PptBindingRepository(self.database), SongRepository(self.database), 0
        for key, slides in bindings.items():
            app, _, document = key.partition(":")
            if app not in ("powerpoint", "wps") or not document:
                continue
            for slide_text, song_id in slides.items():
                if song_id is None or not slide_text.isdigit() or int(slide_text) < 1:
                    continue
                if repo.get(app, document, int(slide_text)) is None and songs.get(song_id) is not None:
                    repo.set(app, document, int(slide_text), song_id)
                    imported += 1
        self._load(self.ppt.state)
        self.ppt.touch()
        return {"imported": imported, **self.ppt.snapshot()}

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
