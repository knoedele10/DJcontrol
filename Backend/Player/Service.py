"""M3 播放器服务：模拟控制器、持久化队列、场次和已播的统一状态。"""

from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Callable, Literal

from Player.Base import CapabilityUnsupported, ControllerCommandFailed, ControllerCommandPending, ControllerTimeout, ControllerTrackLoading, PlayerController, PlayerReading, PlayerUnavailable
from Player.Mock import MockPlayerController
from Database import Database, PlaylistRepository, QueueRepository, SessionRepository, SettingsRepository, SongRepository
from Player.Model import PlayerCommand

logger = logging.getLogger(__name__)

AUTO_NEXT_KEY = "player.auto_next"
CONTROLLER_KEY = "player.controller"
PLAYLIST_KEY = 'player.playlist'


class PlayerError(Exception):
    code = "player_error"


class PlayerNotFound(PlayerError):
    code = "not_found"


class PlayerConflict(PlayerError):
    code = "player_command_failed"


class PlayerUnsupported(PlayerConflict):
    code = "capability_unsupported"


class PlayerDisconnected(PlayerError):
    code = "player_unavailable"


class PlayerTimedOut(PlayerError):
    code = "command_timeout"


@dataclass(frozen=True)
class PlayerState:
    controller: Literal["mock", "kugou"] = "mock"
    connected: bool = False
    status: Literal["playing", "paused", "stopped", "unknown"] = "unknown"
    song_id: int | None = None
    title: str = ""
    artist: str = ""
    position: float | None = None
    duration: float | None = None
    auto_next: bool = True
    queue: tuple[dict[str, Any], ...] = ()
    session: dict[str, Any] | None = None
    recent_history: tuple[dict[str, Any], ...] = ()
    error: str | None = None
    capabilities: tuple[dict, ...] = ()
    via: Literal['playlist', 'search'] | None = None


class PlayerService:
    # 发出命令后补读状态的等待间隔（秒）；后一组只在播放器已开始响应时才用。
    verification_delays: tuple[float, ...] = (0, 0.15, 0.25, 0.4, 0.6, 0.8, 0.8)
    pending_delays: tuple[float, ...] = (1.0, 1.0, 1.0, 1.0, 1.0)

    def __init__(
        self,
        database: Database,
        *,
        controller_name: Literal["mock", "kugou"] = "mock",
        factory: Callable[[], PlayerController] | None = None,
        poll_interval: float = 0.5,
    ) -> None:
        if controller_name not in ("mock", "kugou"):
            raise ValueError("PLAYER_CONTROLLER 必须为 mock 或 kugou")
        self.database = database
        self.controller_name = controller_name
        self._factory = factory or self._factory_for(controller_name)
        self.poll_interval = poll_interval
        self._controller: PlayerController | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="player-control")
        self._lock = asyncio.Lock()
        self._poller: asyncio.Task | None = None
        self._subscribers: set[asyncio.Queue] = set()
        self.revision = 0
        self.state = PlayerState(controller=controller_name, error="正在连接播放器")
        # 自动接歌只在"这首歌播着播着结束了"那一刻触发一次：
        # 看到某首歌在播就记下它，之后看到同一首停下才接歌，接完或放弃都清掉。
        # 这样"播完停了很久再往队列加歌"不会被当成刚播完而立刻开播。
        self._armed_song: int | None = None
        # 连按"上一首"时在本场已播里逐条往回走；0 表示停在最新一条。正常播放会重置。
        self._back_steps = 0
        # 播放器点开了歌但还在加载（酷狗连接慢）：先不动队列和已播，读到这首歌真的在播再补记。
        # 第三项是这首歌在已播里的位置：新点的歌还没记进已播，记 -1。
        self._loading: tuple[int, Callable[[], None], int] | None = None
        self._playlist_cache = None
        self._playlist_config = None

    @staticmethod
    def _factory_for(name: str) -> Callable[[], PlayerController]:
        if name == "kugou":
            from KugouControl.Adapter import KugouController
            return KugouController
        return MockPlayerController

    async def _run(self, operation: Callable[[], Any]) -> Any:
        return await asyncio.get_running_loop().run_in_executor(self._executor, operation)

    def _controller_for_thread(self) -> PlayerController:
        if self._controller is None:
            self._controller = self._factory()
            self._playlist_config = None
        config = self._playlist_settings_version()
        if config != self._playlist_config:
            if self._playlist_config is not None:
                self._controller.configure_playlist('')
            self._controller.configure_playlist(config[0])
            self._playlist_config = config
            self._playlist_cache = None
        return self._controller

    def _ensure_session(self) -> dict[str, Any]:
        repository = SessionRepository(self.database)
        current = repository.current()
        return current or repository.start()

    @staticmethod
    def _public_queue(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
        return tuple({"id": row["id"], "song_id": int(row["song_id"]), "added_at": row["added_at"]} for row in rows)

    @staticmethod
    def _public_history(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
        return tuple({
            "song_id": row["song_id"], "title": row["title"], "artist": row["artist"], "played_at": row["played_at"],
        } for row in rows[:20])

    def _read_state(self) -> PlayerState:
        controller = self._controller_for_thread()
        config = self._playlist_config
        reading: PlayerReading = controller.get_state()
        self._accept_playlist_snapshot(controller.playlist_snapshot(), config)
        capabilities = controller.capabilities()
        if self._loading:
            song_id, commit, _ = self._loading
            if reading.song_id == song_id and reading.status == 'playing':
                self._loading = None
                commit()
            elif (reading.title and reading.song_id != song_id) or not reading.connected:
                self._loading = None  # 播出来的是别的歌，或播放器断开了
        if reading.status == "playing" and reading.song_id is not None:
            self._armed_song = reading.song_id
        session_repo = SessionRepository(self.database)
        session = session_repo.current() or session_repo.latest()
        queue = QueueRepository(self.database).list_items()
        history = SessionRepository(self.database).list_history(session["id"], limit=20) if session else []
        return PlayerState(
            controller=self.controller_name,
            connected=reading.connected,
            status=reading.status,
            song_id=reading.song_id,
            title=reading.title,
            artist=reading.artist,
            position=reading.position,
            duration=reading.duration,
            auto_next=self.state.auto_next if self.controller_name == "mock" else False,
            queue=self._public_queue(queue),
            session=session,
            recent_history=self._public_history(history),
            error=reading.error,
            capabilities=tuple(capabilities),
            via=reading.via,
        )

    def snapshot(self) -> dict:
        state = asdict(self.state)
        state["queue"] = list(self.state.queue)
        state["recent_history"] = list(self.state.recent_history)
        return {"type": "player_state", "revision": self.revision, "state": state}

    def _publish(self, state: PlayerState) -> None:
        if state == self.state:
            return
        self.state = state
        self.revision += 1
        event = self.snapshot()
        for queue in self._subscribers:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

    async def refresh(self) -> dict:
        async with self._lock:
            try:
                state = await self._run(self._read_state)
            except Exception as exc:
                logger.exception("读取播放器状态失败")
                state = PlayerState(
                    controller=self.controller_name,
                    auto_next=self.state.auto_next,
                    queue=self.state.queue,
                    session=self.state.session,
                    recent_history=self.state.recent_history,
                    error="读取播放器状态失败，请检查后端日志",
                )
            self._publish(state)
            return self.snapshot()

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._subscribers.add(queue)
        queue.put_nowait(self.snapshot())
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def _play_song(self, song_id: int, *, back_steps: int | None = None) -> None:
        """播放一首歌并移出队列。back_steps 用于"上一首"回放：歌已在已播里，不再重复记录，只记回退到第几条。"""

        songs = SongRepository(self.database)
        song = songs.get(song_id)
        if song is None:
            raise PlayerNotFound("歌曲不存在")
        controller = self._controller_for_thread()
        config = self._playlist_config
        playlist = config[0]
        song = {**song, 'in_playlist': PlaylistRepository(self.database).list(playlist).get(song_id)}
        result = {}

        def commit() -> None:
            current_playlist = playlist and config == self._playlist_settings_version()
            if current_playlist and result.get('via') == 'playlist':
                PlaylistRepository(self.database).set(playlist, song, True)
            elif current_playlist and result.get('playlist_missed'):
                PlaylistRepository(self.database).set(playlist, song, False)
            self._armed_song = song_id
            QueueRepository(self.database).remove_song(song_id)
            if back_steps is None:
                session = self._ensure_session()
                SessionRepository(self.database).add_history(
                    session["id"], song_id=song_id, title=song["title"], artist=song["artist"],
                )
            self._back_steps = back_steps or 0

        self._loading = None
        try:
            controller.play_track(song)
        except ControllerTrackLoading:
            self._loading = (song_id, commit, -1 if back_steps is None else back_steps)
            raise
        finally:
            result.update(getattr(controller, 'play_result', {}))
        commit()

    def _play_previous(self) -> None:
        session = self._ensure_session()
        # 刚点的歌还在加载、没记进已播时，「上一首」就是已播里最新的那条。
        target = (self._loading[2] if self._loading else self._back_steps) + 1
        history = SessionRepository(self.database).list_history(session["id"], limit=target + 50)
        current = self._controller_for_thread().get_state().song_id
        # 从目标位置往更早找第一条能播的：跳过歌曲已删除（song_id 为 null）的记录，
        # 也跳过正在播的这首（同一首歌之前播过时，不能"上一首"回到它自己）。
        for index in range(target, len(history)):
            song_id = history[index]["song_id"]
            if song_id is not None and song_id != current:
                self._play_song(int(song_id), back_steps=index)
                return
        raise PlayerConflict("没有更早的已播歌曲")

    def _command(self, command: PlayerCommand) -> None:
        controller = self._controller_for_thread()
        required = {"play": "play_track", "next_in_queue": "play_track", "previous": "play_track",
                    "toggle": "play_pause", "seek": "seek", "media_next": "next", "media_previous": "next"}[command.action]
        if command.action == "play":
            self._play_song(command.song_id)
        elif command.action == "next_in_queue":
            rows = QueueRepository(self.database).list_items()
            if not rows:
                raise PlayerConflict("队列为空，先加入歌曲")
            self._play_song(int(rows[0]["song_id"]))
        elif command.action == "previous":
            self._play_previous()
        elif command.action == "toggle":
            controller.toggle()
        elif command.action == "seek":
            controller.seek(float(command.position))
        elif command.action == "media_next":
            controller.media_next()
        elif command.action == "media_previous":
            controller.media_previous()

    def _auto_next_if_ended(self, state: PlayerState) -> PlayerState:
        """在轮询线程里调用：刚播完的那首如果开启了自动接歌且队列不空，就播队列第一首。"""

        armed = self._armed_song
        if armed is None or state.song_id != armed or state.status != "stopped":
            return state
        self._armed_song = None  # 只处理一次；没接上（关闭了自动接歌或队列为空）也不再等待
        if self.state.auto_next and state.queue:
            self._play_song(int(state.queue[0]["song_id"]))
            return self._read_state()
        return state

    async def command(self, command: PlayerCommand) -> dict:
        async with self._lock:
            try:
                await self._run(lambda: self._command(command))
            except CapabilityUnsupported as exc:
                raise PlayerUnsupported(str(exc)) from exc
            except ControllerTimeout as exc:
                raise PlayerTimedOut(str(exc)) from exc
            except PlayerUnavailable as exc:
                raise PlayerDisconnected(str(exc)) from exc
            except ControllerCommandFailed as exc:
                raise PlayerConflict(str(exc)) from exc
            finally:
                try:
                    self._publish(await self._run(self._read_state))
                except Exception as exc:
                    self._publish(PlayerState(
                        controller=self.controller_name, auto_next=self.state.auto_next,
                        queue=self.state.queue, session=self.state.session,
                        recent_history=self.state.recent_history, error=str(exc),
                    ))
            # 媒体键异步生效；状态读取很快时，需要给酷狗处理输入的时间。
            # 只等待并补读，不重发媒体键。外部读取失败时立即停止核验。
            # 播放器已经开始响应（例如正在加载未缓存的下一首）时，再多等几轮才判失败。
            delays = self.verification_delays + self.pending_delays
            for attempt, delay in enumerate(delays):
                if delay:
                    await asyncio.sleep(delay)
                    self._publish(await self._run(self._read_state))
                try:
                    await self._run(lambda: self._controller_for_thread().verify_command())
                    break
                except ControllerCommandFailed as exc:
                    out_of_time = attempt == len(delays) - 1 or (
                        attempt >= len(self.verification_delays) - 1 and not isinstance(exc, ControllerCommandPending))
                    if out_of_time or self.state.error or not self.state.connected:
                        raise PlayerConflict(str(exc)) from exc
            return self.snapshot()

    async def enqueue(self, song_id: int, position: Literal["end", "next"]) -> dict:
        async with self._lock:
            def add() -> None:
                if SongRepository(self.database).get(song_id) is None:
                    raise PlayerNotFound("歌曲不存在")
                QueueRepository(self.database).enqueue(song_id, position=0 if position == "next" else None)
            await self._run(add)
            self._publish(await self._run(self._read_state))
            return self.snapshot()

    async def remove_queue_item(self, item_id: str) -> dict:
        async with self._lock:
            removed = await self._run(lambda: QueueRepository(self.database).delete(item_id))
            if not removed:
                raise PlayerNotFound("队列项不存在")
            self._publish(await self._run(self._read_state))
            return self.snapshot()

    async def order_queue(self, item_ids: list[str]) -> dict:
        async with self._lock:
            try:
                await self._run(lambda: QueueRepository(self.database).order(item_ids))
            except ValueError as exc:
                raise PlayerConflict(str(exc)) from exc
            self._publish(await self._run(self._read_state))
            return self.snapshot()

    async def clear_queue(self) -> dict:
        async with self._lock:
            await self._run(lambda: QueueRepository(self.database).clear())
            self._publish(await self._run(self._read_state))
            return self.snapshot()

    async def set_auto_next(self, enabled: bool) -> dict:
        async with self._lock:
            if enabled and self.controller_name == "kugou":
                raise PlayerUnsupported("酷狗模式不支持自动接歌：酷狗播完一首会自己接着放，面板来不及接管；请用「播队列下一首」")
            await self._run(lambda: SettingsRepository(self.database).set(AUTO_NEXT_KEY, enabled))
            self._publish(PlayerState(**{**self.state.__dict__, "auto_next": enabled}))
            return self.snapshot()

    async def diagnostics(self) -> dict:
        async with self._lock:
            def collect() -> dict:
                controller = self._controller_for_thread()
                info = getattr(controller, "info", {})
                return {"controller": self.controller_name, "capabilities": controller.capabilities(),
                        'playlist': self._playlist_view(),
                        "kugou": {"running": info.get("running", False), "version": info.get("version"), "profile": info.get("profile"), "error": info.get("error")}}
            return await self._run(collect)

    async def switch_controller(self, name: Literal["mock", "kugou"], playlist: str | None = None) -> dict:
        if name not in ("mock", "kugou"):
            raise ValueError("播放器必须为 mock 或 kugou")
        if self._lock.locked():
            raise PlayerConflict('播放器正在执行其他操作，请稍后再保存播放器设置')
        async with self._lock:
            def switch() -> PlayerState:
                self._close_controller()
                self.controller_name = name
                self._factory = self._factory_for(name)
                self._armed_song = None
                self._back_steps = 0
                self._loading = None
                SettingsRepository(self.database).set(CONTROLLER_KEY, name)
                if playlist is not None:
                    configured = playlist.strip()
                    if configured != SettingsRepository(self.database).get(PLAYLIST_KEY, ''):
                        PlaylistRepository(self.database).clear()
                    SettingsRepository(self.database).set(PLAYLIST_KEY, configured)
                return self._read_state()
            self._publish(await self._run(switch))
            return self.snapshot()

    def _playlist_view(self) -> dict:
        status = self._controller_for_thread().playlist_snapshot()
        name = self._playlist_config[0]
        return {**{key: value for key, value in status.items() if key != 'tracks'}, 'name': name,
                'songs': PlaylistRepository(self.database).list(name)}

    def _playlist_settings_version(self) -> tuple[str, str | None]:
        row = self.database.query_one('SELECT value, updated_at FROM settings WHERE key = ?', (PLAYLIST_KEY,))
        if row is None:
            return '', None
        try:
            name = json.loads(row['value'])
        except ValueError:
            name = row['value']
        return name if isinstance(name, str) else '', row['updated_at']

    def _accept_playlist_snapshot(self, state: dict, config: tuple[str, str | None], *, refresh=False) -> None:
        from KugouControl.Profiles import exact_track
        configured, version = config
        resolved = (state.get('name') or '').strip()
        requested = (state.get('requested') or resolved).strip()
        if not state.get('supported') or not configured or not resolved:
            return
        if configured != requested and (refresh or configured != resolved):
            return
        tracks = state.get('tracks', [])
        token = (resolved, state.get('route'), state.get('complete'),
                 tuple((t['title'], t['artist']) for t in tracks))
        if not refresh and token == self._playlist_cache:
            return
        checked_at = datetime.now().astimezone().isoformat()
        members = []
        for song in SongRepository(self.database).list():
            present = any(exact_track(t['title'], t['artist'], song['title'], song['artist']) for t in tracks)
            if present or state.get('complete'):
                members.append((resolved, present, checked_at, song['id'], song['title'], song['artist']))
        with self.database.transaction() as connection:
            if self._playlist_settings_version() != config:
                return
            if configured != resolved:
                connection.execute('UPDATE settings SET value = ?, updated_at = ? WHERE key = ?',
                                   (json.dumps(resolved, ensure_ascii=False), checked_at, PLAYLIST_KEY))
            if refresh or configured != resolved:
                connection.execute('DELETE FROM playlist_tracks WHERE playlist IN (?, ?)', (configured, resolved))
            connection.executemany(
                'INSERT INTO playlist_tracks (playlist, song_id, title, artist, in_playlist, checked_at) '
                'SELECT ?, id, title, artist, ?, ? FROM songs WHERE id = ? AND title = ? AND artist = ? '
                'ON CONFLICT(playlist, song_id) DO UPDATE SET title = excluded.title, artist = excluded.artist, '
                'in_playlist = excluded.in_playlist, checked_at = excluded.checked_at', members)
        self._playlist_config = (resolved, checked_at if configured != resolved else version)
        self._playlist_cache = token

    async def playlist(self) -> dict:
        async with self._lock:
            return await self._run(self._playlist_view)

    async def _playlist_call(self, operation: Callable) -> dict:
        try:
            return await self._run(operation)
        except CapabilityUnsupported as exc:
            raise PlayerUnsupported(str(exc)) from exc
        except ControllerTimeout as exc:
            raise PlayerTimedOut(str(exc)) from exc
        except PlayerUnavailable as exc:
            raise PlayerDisconnected(str(exc)) from exc
        except ControllerCommandFailed as exc:
            raise PlayerConflict(str(exc)) from exc
        finally:
            try:
                self._publish(await self._run(self._read_state))
            except Exception:
                logger.exception('歌单操作后的状态读取失败')

    async def refresh_playlist(self) -> dict:
        if self._lock.locked():
            raise PlayerConflict('播放器正在执行其他操作，请稍后再刷新歌单')
        async with self._lock:
            def refresh():
                controller = self._controller_for_thread()
                config = self._playlist_config
                state = controller.refresh_playlist()
                self._accept_playlist_snapshot(state, config, refresh=True)
                return self._playlist_view()
            return await self._playlist_call(refresh)

    async def add_to_playlist(self, song_id: int) -> dict:
        # 不排队重放加歌请求：双击或并发请求应得到明确冲突。
        if self._lock.locked():
            raise PlayerConflict('播放器正在执行其他操作，请稍后再加入歌单')
        async with self._lock:
            def add():
                song = SongRepository(self.database).get(song_id)
                if song is None:
                    raise PlayerNotFound('歌曲不存在')
                controller = self._controller_for_thread()
                config = self._playlist_config
                status = controller.playlist_snapshot()
                name = config[0]
                if not name or not status.get('can_add'):
                    raise PlayerUnsupported(status.get('add_note', '请配置歌单并完成加歌能力检测'))
                self._loading = None
                self._armed_song = None
                PlaylistRepository(self.database).set(name, song, None)
                result = controller.add_to_playlist(song)
                if config == self._playlist_settings_version():
                    PlaylistRepository(self.database).set(name, song, result.get('in_playlist'))
                return {**result, 'playlist': self._playlist_view()}
            return await self._playlist_call(add)

    async def start_session(self) -> dict:
        async with self._lock:
            await self._run(lambda: SessionRepository(self.database).start())
            self._publish(await self._run(self._read_state))
            return self.snapshot()

    async def end_session(self) -> dict:
        async with self._lock:
            await self._run(lambda: SessionRepository(self.database).end_current())
            self._publish(await self._run(self._read_state))
            return self.snapshot()

    async def history(self, limit: int = 200) -> list[dict[str, Any]]:
        async with self._lock:
            session = await self._run(lambda: SessionRepository(self.database).current())
            if session is None:
                return []
            rows = await self._run(lambda: SessionRepository(self.database).list_history(session["id"], limit=limit))
            return [dict(row) for row in rows]

    async def start(self) -> None:
        await self._run(self._ensure_session)
        auto_next = await self._run(lambda: SettingsRepository(self.database).get(AUTO_NEXT_KEY, True))
        self.state = PlayerState(**{**self.state.__dict__, "auto_next": bool(auto_next)})
        await self.refresh()
        self._poller = asyncio.create_task(self._poll())

    async def _poll(self) -> None:
        while True:
            await asyncio.sleep(self.poll_interval)
            try:
                async with self._lock:
                    state = await self._run(lambda: self._auto_next_if_ended(self._read_state()))
                    self._publish(state)
            except Exception:
                logger.exception("播放器轮询失败")

    async def close(self) -> None:
        if self._poller is not None:
            self._poller.cancel()
            await asyncio.gather(self._poller, return_exceptions=True)
        async with self._lock:
            await self._run(self._close_controller)
        self._subscribers.clear()
        self._executor.shutdown(wait=True)

    def _close_controller(self) -> None:
        if self._controller is not None:
            self._controller.close()
            self._controller = None
