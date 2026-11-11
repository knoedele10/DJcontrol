"""曲库业务服务：把仓储操作串行化，并向多个面板推送变更通知。"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
from typing import Any

from Database import Database, LibraryRepository, SongRepository

PALETTE = ("#00e0a4", "#ff6a2b", "#a66bff", "#ff3da6", "#ffc928", "#2fb8ff", "#3df0e0", "#d36bff")
_SEPARATOR = re.compile(r"\s+(?:-|—|–)\s+")
logger = logging.getLogger(__name__)
KUGOU_SEARCH_WAIT = 8.0   # 酷狗搜索最多等这么久，超时只返回曲库结果
KUGOU_KEY_TTL = 600       # 搜索结果的 key 保留 10 分钟，用于「收进曲库」


def _public_song(song: dict[str, Any]) -> dict[str, Any]:
    """只向接口暴露契约字段，时间戳留在仓储内部用于审计。"""

    return {key: song[key] for key in ("id", "title", "artist", "bpm", "duration", "source", "note")}


class LibraryError(Exception):
    code = "library_error"


class LibraryNotFound(LibraryError):
    code = "not_found"


class LibraryConflict(LibraryError):
    code = "conflict"


class KugouUnavailable(LibraryError):
    code = "kugou_unavailable"


class LibraryService:
    """所有 SQLite I/O 使用一个线程，保证共享连接的访问顺序可预测。"""

    def __init__(self, database: Database, *, kugou_search: Callable[[str, int], list[dict]] | None = None) -> None:
        self.database = database
        # 酷狗搜索函数（阻塞，查网络）；None 表示不接酷狗搜索。
        self._kugou_search = kugou_search
        self._kugou_results: dict[str, tuple[float, dict[str, Any]]] = {}
        self._kugou_queries: dict[str, tuple[float, list[dict]]] = {}  # 同一个词 10 分钟内不重复查网络
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="library-db")
        self._lock = asyncio.Lock()
        self._subscribers: set[asyncio.Queue] = set()
        self.revision = 0

    async def _run(self, operation: Callable[[], Any]) -> Any:
        return await asyncio.get_running_loop().run_in_executor(self._executor, operation)

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._subscribers.add(queue)
        # 初始快照不携带数据，使用 groups 作为兼容契约的唤醒信号；前端随后读取两个资源。
        queue.put_nowait({"type": "library_changed", "revision": self.revision, "scope": "groups"})
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def _publish(self, scope: str) -> None:
        self.revision += 1
        event = {"type": "library_changed", "revision": self.revision, "scope": scope}
        for queue in self._subscribers:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

    async def close(self) -> None:
        self._subscribers.clear()
        self._executor.shutdown(wait=True)

    async def songs(self, source: str | None = None) -> list[dict[str, Any]]:
        return await self._run(lambda: [_public_song(song) for song in SongRepository(self.database).list(source=source)])

    async def groups(self) -> list[dict[str, Any]]:
        return await self._run(lambda: LibraryRepository(self.database).list_groups())

    async def search(self, query: str, limit: int = 30) -> list[dict[str, Any]]:
        tokens = [token.casefold() for token in query.split() if token.strip()]

        def read() -> list[dict[str, Any]]:
            songs = SongRepository(self.database).list()
            if not tokens:
                return []

            def score(song: dict[str, Any]) -> tuple[int, int, int]:
                title = str(song["title"]).casefold()
                artist = str(song["artist"]).casefold()
                exact = int(title == " ".join(tokens) or artist == " ".join(tokens))
                title_hit = int(all(token in title for token in tokens))
                return (-exact, -title_hit, int(song["id"]))

            return sorted(
                (song for song in songs if all(token in f"{song['title']} {song['artist']}".casefold() for token in tokens)),
                key=score,
            )[:limit]

        return [_public_song(song) for song in await self._run(read)]

    async def create_song(self, values: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            def create() -> dict[str, Any]:
                try:
                    return SongRepository(self.database).create(**values)
                except Exception as exc:
                    if "UNIQUE constraint failed: songs.title, songs.artist" in str(exc):
                        raise LibraryConflict("曲库中已有同名歌曲") from exc
                    raise

            song = _public_song(await self._run(create))
            self._publish("songs")
            return song

    async def update_song(self, song_id: int, values: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            def update() -> dict[str, Any]:
                try:
                    song = SongRepository(self.database).update(song_id, **values)
                except Exception as exc:
                    if "UNIQUE constraint failed: songs.title, songs.artist" in str(exc):
                        raise LibraryConflict("曲库中已有同名歌曲") from exc
                    raise
                if song is None:
                    raise LibraryNotFound("歌曲不存在")
                return song

            song = _public_song(await self._run(update))
            self._publish("songs")
            return song

    async def delete_song(self, song_id: int) -> None:
        async with self._lock:
            deleted = await self._run(lambda: SongRepository(self.database).delete(song_id))
            if not deleted:
                raise LibraryNotFound("歌曲不存在")
            self._publish("songs")

    async def import_songs(self, text: str, category_ids: list[str]) -> dict[str, Any]:
        # 先解析和去重，避免半行数据进入数据库。
        rows: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        skipped = 0
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            parts = _SEPARATOR.split(line, maxsplit=1)
            if len(parts) != 2 or not all(parts):
                skipped += 1
                continue
            key = (parts[0].strip(), parts[1].strip())
            if key in seen:
                skipped += 1
                continue
            seen.add(key)
            rows.append(key)

        async with self._lock:
            def write() -> tuple[list[dict[str, Any]], int]:
                songs_repo = SongRepository(self.database)
                library_repo = LibraryRepository(self.database)
                groups = library_repo.list_groups()
                categories = {category["id"] for group in groups for category in group["categories"]}
                missing_categories = [category_id for category_id in category_ids if category_id not in categories]
                if missing_categories:
                    raise LibraryNotFound("指定的分类不存在")
                existing = {(str(song["title"]), str(song["artist"])) for song in songs_repo.list()}
                added: list[dict[str, Any]] = []
                local_skipped = 0
                for title, artist in rows:
                    if (title, artist) in existing:
                        local_skipped += 1
                        continue
                    try:
                        song = songs_repo.create(title, artist)
                    except Exception as exc:
                        if "UNIQUE constraint failed: songs.title, songs.artist" in str(exc):
                            local_skipped += 1
                            continue
                        raise
                    added.append(song)
                    existing.add((title, artist))
                    for category_id in category_ids:
                        library_repo.add_song(category_id, int(song["id"]))
                return added, local_skipped

            added, local_skipped = await self._run(write)
            if added:
                self._publish("songs")
                if category_ids:
                    self._publish("groups")
            return {"added": len(added), "skipped": skipped + local_skipped, "songs": [_public_song(song) for song in added]}

    async def search_kugou(self, query: str, limit: int = 30) -> tuple[list[dict[str, Any]], bool]:
        """返回（酷狗结果，酷狗搜索这次是否可用）。曲库里已有的、重复的结果去掉。"""

        if self._kugou_search is None:
            return [], False
        if not query.strip():
            return [], True
        word, now = query.strip(), time.monotonic()
        self._kugou_queries = {key: item for key, item in self._kugou_queries.items() if item[0] > now}
        if word.casefold() in self._kugou_queries:
            found = self._kugou_queries[word.casefold()][1]
        else:
            try:
                found = await asyncio.wait_for(asyncio.to_thread(self._kugou_search, word, 30), KUGOU_SEARCH_WAIT)
            except Exception as exc:  # 超时、断网、接口变了：都只算这次没搜到
                logger.warning("酷狗搜索失败：%s", exc or type(exc).__name__)
                return [], False
            self._kugou_queries[word.casefold()] = (now + KUGOU_KEY_TTL, found)
        same = lambda song: (str(song["title"]).casefold(), str(song["artist"]).casefold())
        seen = {same(song) for song in await self._run(lambda: SongRepository(self.database).list())}
        self._kugou_results = {key: item for key, item in self._kugou_results.items() if item[0] > now}
        results = []
        for item in found:
            if same(item) in seen:
                continue
            seen.add(same(item))
            key = "kg-" + hashlib.sha1("|".join((item["title"], item["artist"])).encode()).hexdigest()[:20]
            result = {"key": key, "title": item["title"], "artist": item["artist"], "bpm": None,
                      "duration": int(item.get("duration") or 0)}
            self._kugou_results[key] = (now + KUGOU_KEY_TTL, result)
            results.append(result)
        return results[:limit], True

    async def import_kugou(self, key: str) -> dict[str, Any]:
        if self._kugou_search is None:
            raise KugouUnavailable("酷狗搜索未启用，不能收录该结果")
        cached = self._kugou_results.get(key)
        if cached is None or cached[0] <= time.monotonic():
            raise LibraryNotFound("这条酷狗搜索结果已过期，请重新搜索")
        result = cached[1]
        async with self._lock:
            def create() -> dict[str, Any]:
                songs = SongRepository(self.database)
                for song in songs.list():  # 已经收过（或手动加过同名歌）就直接用那一首
                    if (song["title"].casefold(), song["artist"].casefold()) == (result["title"].casefold(), result["artist"].casefold()):
                        return song
                return songs.create(result["title"], result["artist"], duration=result["duration"], source="kugou")
            song = _public_song(await self._run(create))
            self._publish("songs")
            return song

    async def create_group(self, name: str, color: str | None) -> dict[str, Any]:
        async with self._lock:
            def create() -> dict[str, Any]:
                repo = LibraryRepository(self.database)
                try:
                    return repo.create_group(name, color or PALETTE[len(repo.list_groups()) % len(PALETTE)])
                except Exception as exc:
                    if "UNIQUE constraint failed: event_groups.name" in str(exc):
                        raise LibraryConflict("活动组名称已存在") from exc
                    raise
            group = await self._run(create)
            self._publish("groups")
            return group

    async def update_group(self, group_id: str, values: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            def update() -> dict[str, Any]:
                repo = LibraryRepository(self.database)
                try:
                    group = repo.update_group(group_id, **values)
                except Exception as exc:
                    if "UNIQUE constraint failed: event_groups.name" in str(exc):
                        raise LibraryConflict("活动组名称已存在") from exc
                    raise
                if group is None:
                    raise LibraryNotFound("活动组不存在")
                return group
            group = await self._run(update)
            self._publish("groups")
            return group

    async def delete_group(self, group_id: str) -> None:
        async with self._lock:
            if not await self._run(lambda: LibraryRepository(self.database).delete_group(group_id)):
                raise LibraryNotFound("活动组不存在")
            self._publish("groups")

    async def reorder_groups(self, ids: list[str]) -> None:
        async with self._lock:
            try:
                await self._run(lambda: LibraryRepository(self.database).reorder_groups(ids))
            except ValueError as exc:
                raise LibraryConflict(str(exc)) from exc
            self._publish("groups")

    async def create_category(self, group_id: str, name: str, color: str | None, song_ids: list[int]) -> dict[str, Any]:
        async with self._lock:
            def create() -> dict[str, Any]:
                repo = LibraryRepository(self.database)
                if repo.get_group(group_id) is None:
                    raise LibraryNotFound("活动组不存在")
                if len(song_ids) != len(set(song_ids)):
                    raise LibraryConflict("分类歌曲不能重复")
                songs_repo = SongRepository(self.database)
                if any(songs_repo.get(song_id) is None for song_id in song_ids):
                    raise LibraryNotFound("指定的歌曲不存在")
                try:
                    group = repo.get_group(group_id)
                    if group is None:
                        raise LibraryNotFound("活动组不存在")
                    return repo.create_category(group_id, name, color or PALETTE[len(group["categories"]) % len(PALETTE)], song_ids=song_ids)
                except Exception as exc:
                    message = str(exc)
                    if "UNIQUE constraint failed: categories.group_id, categories.name" in message:
                        raise LibraryConflict("该活动组中已有同名分类") from exc
                    if "FOREIGN KEY constraint failed" in message:
                        raise LibraryNotFound("指定的歌曲不存在") from exc
                    raise
            category = await self._run(create)
            self._publish("groups")
            return category

    async def update_category(self, category_id: str, values: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            def update() -> dict[str, Any]:
                repo = LibraryRepository(self.database)
                try:
                    category = repo.update_category(category_id, **values)
                except Exception as exc:
                    if "UNIQUE constraint failed: categories.group_id, categories.name" in str(exc):
                        raise LibraryConflict("该活动组中已有同名分类") from exc
                    raise
                if category is None:
                    raise LibraryNotFound("分类不存在")
                return category
            category = await self._run(update)
            self._publish("groups")
            return category

    async def delete_category(self, category_id: str) -> None:
        async with self._lock:
            if not await self._run(lambda: LibraryRepository(self.database).delete_category(category_id)):
                raise LibraryNotFound("分类不存在")
            self._publish("groups")

    async def reorder_categories(self, group_id: str, ids: list[str]) -> None:
        async with self._lock:
            try:
                def reorder() -> None:
                    repo = LibraryRepository(self.database)
                    if repo.get_group(group_id) is None:
                        raise LibraryNotFound("活动组不存在")
                    repo.reorder_categories(group_id, ids)
                await self._run(reorder)
            except ValueError as exc:
                raise LibraryConflict(str(exc)) from exc
            self._publish("groups")

    async def category_song(self, category_id: str, song_id: int, add: bool) -> dict[str, Any]:
        async with self._lock:
            def change() -> dict[str, Any]:
                repo = LibraryRepository(self.database)
                if repo.get_category(category_id) is None:
                    raise LibraryNotFound("分类不存在")
                if SongRepository(self.database).get(song_id) is None:
                    raise LibraryNotFound("歌曲不存在")
                if add:
                    if not repo.add_song(category_id, song_id):
                        raise LibraryConflict("歌曲已在该分类")
                else:
                    repo.remove_song(category_id, song_id)
                return repo.get_category(category_id)  # type: ignore[return-value]
            category = await self._run(change)
            self._publish("groups")
            return category

    async def replace_category_songs(self, category_id: str, song_ids: list[int]) -> dict[str, Any]:
        if len(song_ids) != len(set(song_ids)):
            raise LibraryConflict("分类歌曲不能重复")
        async with self._lock:
            def replace() -> dict[str, Any]:
                repo = LibraryRepository(self.database)
                if repo.get_category(category_id) is None:
                    raise LibraryNotFound("分类不存在")
                if any(SongRepository(self.database).get(song_id) is None for song_id in song_ids):
                    raise LibraryNotFound("指定的歌曲不存在")
                repo.replace_category_songs(category_id, song_ids)
                return repo.get_category(category_id)  # type: ignore[return-value]
            category = await self._run(replace)
            self._publish("groups")
            return category
