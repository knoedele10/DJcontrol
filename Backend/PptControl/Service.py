"""串行 COM 操作和独立页码监听，面板以实际读取的状态为准。"""

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Any
from uuid import uuid4

from PptControl import PptApp, PptCommandError, PptController, PptError, PptState, PptUnavailable, create_controller
from PptControl.Model import PptCommand
from PptControl.PreviewCache import PptPreviewCache

logger = logging.getLogger(__name__)


class PptService:
    def __init__(
        self,
        app: PptApp = "powerpoint",
        poll_interval: float = 0.25,
        factory: Callable[[PptApp], PptController] = create_controller,
    ) -> None:
        self.app = app
        self.poll_interval = poll_interval
        self._factory = factory
        self._controller: PptController | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ppt-com")
        self._lock = asyncio.Lock()
        self._poller: asyncio.Task | None = None
        self._subscribers: set[asyncio.Queue] = set()
        self._revision = 0
        self._previews = PptPreviewCache()
        self.preview_session = uuid4().hex
        self.state = PptState(app=app, error="正在连接演示软件")
        # 页面绑定与翻页联动（PptControl/Link.py）挂在这两个钩子上；不挂时本服务只管 PPT 本身。
        self.extras: Callable[[], dict] | None = None
        self.on_change: Callable[[PptState, PptState], None] | None = None

    def _get_controller(self) -> PptController:
        if self._controller is None:
            self._controller = self._factory(self.app)
        return self._controller

    async def _run(self, operation: Callable[[], Any]) -> Any:
        return await asyncio.get_running_loop().run_in_executor(self._executor, operation)

    def snapshot(self) -> dict:
        return {"type": "ppt_state", "revision": self._revision, "state": asdict(self.state),
                "preview_session": self.preview_session, **(self.extras() if self.extras else {})}

    def touch(self) -> None:
        """PPT 状态没变但附带信息（绑定、联动开关、联动结果）变了：推一次新的快照。"""

        self._revision += 1
        for queue in self._subscribers:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(self.snapshot())

    def _publish(self, state: PptState) -> None:
        if state == self.state:
            return
        if (state.app, state.document_id, state.total_slides) != (
            self.state.app, self.state.document_id, self.state.total_slides
        ):
            self._previews.clear()
            self.preview_session = uuid4().hex
        previous, self.state = self.state, state
        if self.on_change:
            try:
                self.on_change(previous, state)
            except Exception:
                logger.exception("处理 PPT 状态变化失败")
        self._revision += 1
        for queue in self._subscribers:
            # 慢连接只保留最新状态，避免积压旧页码。
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(self.snapshot())

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._subscribers.add(queue)
        queue.put_nowait(self.snapshot())
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    async def _refresh_locked(self) -> None:
        try:
            state = await self._run(lambda: self._get_controller().get_state())
        except PptError as exc:
            state = PptState(app=self.app, error=str(exc))
        except Exception:
            logger.exception("读取 PPT 状态失败")
            state = PptState(app=self.app, error="读取 PPT 状态失败，请检查后端日志")
        self._publish(state)

    async def refresh(self) -> dict:
        async with self._lock:
            await self._refresh_locked()
            return self.snapshot()

    async def connect(self, app: PptApp) -> dict:
        async with self._lock:
            if self.app != app:
                await self._run(self._close_controller)
                self.app = app
            await self._refresh_locked()
            return self.snapshot()

    async def preview(
        self, app: PptApp, document: str, slide: int, width: int,
        version: int = 0, session: str = "",
    ) -> bytes:
        def validate() -> None:
            state = self.state
            if not state.connected:
                raise PptUnavailable(state.error or "演示软件未连接")
            if state.app != app or state.document_id != document or (session and session != self.preview_session):
                raise PptCommandError("演示文稿已切换，请等待面板同步后重试")
            if not 1 <= slide <= state.total_slides:
                raise PptCommandError("预览页码越界")

        # 命中缓存时直接提供文件，不排队访问 COM 或再次读取软件状态。
        if (self.state.connected and self.state.app == app and self.state.document_id == document
                and (not session or session == self.preview_session)):
            validate()
            cached = self._previews.get((app, document, slide, width, version))
            if cached is not None:
                return cached
        async with self._lock:
            await self._refresh_locked()
            validate()
            key = (app, document, slide, width, version)
            cached = self._previews.get(key)
            if cached is not None:
                return cached
            content = await self._run(lambda: self._get_controller().export_slide(slide, width, document))
            self._previews.put(key, content, max_entries=self.state.total_slides * 4 + 8)
            return content

    async def command(self, command: PptCommand) -> dict:
        def execute() -> None:
            controller = self._get_controller()
            if command.action == "goto":
                controller.goto_slide(command.slide)
            elif command.action == "black":
                controller.set_black(command.enabled)
            elif command.action == "start":
                controller.start(command.slide)
            else:
                getattr(controller, command.action)()

        async with self._lock:
            try:
                await self._run(execute)
            finally:
                # 成功和失败都重新读取；不会乐观修改或重试翻页。
                await self._refresh_locked()
            return self.snapshot()

    async def start(self) -> None:
        await self.refresh()
        self._poller = asyncio.create_task(self._poll())

    async def _poll(self) -> None:
        while True:
            await asyncio.sleep(self.poll_interval)
            await self.refresh()

    def _close_controller(self) -> None:
        if self._controller is not None:
            self._controller.close()
            self._controller = None

    async def close(self) -> None:
        if self._poller is not None:
            self._poller.cancel()
            await asyncio.gather(self._poller, return_exceptions=True)
        async with self._lock:
            await self._run(self._close_controller)
        self._executor.shutdown(wait=True)
        self._subscribers.clear()
        self._previews.close()
