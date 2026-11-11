"""PowerPoint 兼容对象模型；只连接已打开的软件，不自动启动进程。"""

from collections.abc import Callable
import os
from pathlib import Path
import tempfile
from typing import Any, TypeVar

from PptControl.Base import PptCommandError, PptController, PptError, PptState, PptUnavailable

T = TypeVar("T")
RUNNING, BLACK, DONE = 1, 3, 5


class ComPptController(PptController):
    prog_ids: tuple[str, ...]
    label: str

    def __init__(self) -> None:
        self._application: Any = None
        self._pythoncom: Any = None
        self._client: Any = None

    def _connect(self) -> Any:
        if self._pythoncom is None:
            try:
                import pythoncom
                import win32com.client
            except ImportError as exc:
                raise PptUnavailable("PPT 控制需要 Windows 和 pywin32，请安装后端依赖") from exc
            pythoncom.CoInitialize()
            self._pythoncom = pythoncom
            self._client = win32com.client
        if self._application is None:
            for prog_id in self.prog_ids:
                try:
                    application = self._client.GetActiveObject(prog_id)
                except Exception:
                    continue
                self._validate_application(application)
                self._application = application
                break
            if self._application is None:
                raise PptUnavailable(f"未连接到 {self.label}，请先打开演示文稿并确认 COM 功能可用")
        return self._application

    def _validate_application(self, application: Any) -> None:
        """允许各实现识别被其他软件接管的兼容 COM 注册。"""

    def _invoke(self, operation: Callable[[], T]) -> T:
        try:
            return operation()
        except PptError:
            raise
        except Exception as exc:
            # RPC 断开或软件忙碌时只重连读取，绝不自动重放控制命令。
            self._application = None
            raise PptUnavailable(f"{self.label} 暂时无法响应，请关闭弹窗或重新打开演示文稿") from exc

    def _target(self) -> tuple[Any, Any, Any]:
        application = self._connect()
        window = self._show_window(application)
        if window is not None:
            return application, window.Presentation, window.View
        if not application.Presentations.Count:
            return application, None, None
        return application, application.ActivePresentation, None

    def _show_window(self, application: Any) -> Any:
        windows = application.SlideShowWindows
        return windows.Item(1) if windows.Count else None

    def _read_state(self) -> PptState:
        application, presentation, view = self._target()
        if presentation is None:
            return PptState(app=self.app, connected=True)
        total = int(presentation.Slides.Count)
        running = view is not None and int(view.State) != DONE
        # SlideIndex 是文稿页码；CurrentShowPosition 在自定义放映中只是顺序号。
        current = int(view.Slide.SlideIndex) if running else self._editor_slide(application)
        if current is not None and not 1 <= current <= total:
            current = None
        return PptState(
            app=self.app,
            connected=True,
            document_id=str(presentation.FullName),
            file=str(presentation.Name),
            current_slide=current,
            total_slides=total,
            running=running,
            black=running and int(view.State) == BLACK,
        )

    @staticmethod
    def _editor_slide(application: Any) -> int | None:
        try:
            return int(application.ActiveWindow.View.Slide.SlideIndex)
        except Exception:
            # 缩略图浏览等视图可能没有单一当前页，不猜测为第一页。
            return None

    def get_state(self) -> PptState:
        return self._invoke(self._read_state)

    def export_slide(self, slide: int, width: int = 1280, document_id: str | None = None) -> bytes:
        def operation() -> bytes:
            _, presentation, _ = self._target()
            if presentation is None:
                raise PptCommandError("请先打开演示文稿")
            if document_id is not None and str(presentation.FullName) != document_id:
                raise PptCommandError("演示文稿已切换，请等待面板同步后重试")
            self._validate_slide(slide, int(presentation.Slides.Count))
            if not 160 <= width <= 1600:
                raise PptCommandError("预览尺寸不合法")
            slide_width = float(presentation.PageSetup.SlideWidth)
            slide_height = float(presentation.PageSetup.SlideHeight)
            if slide_width <= 0 or slide_height <= 0:
                raise PptCommandError("无法读取幻灯片尺寸")
            height = min(1600, max(1, round(width * slide_height / slide_width)))
            output_width = max(1, round(height * slide_width / slide_height))
            descriptor, filename = tempfile.mkstemp(prefix="kgdash-ppt-", suffix=".png")
            os.close(descriptor)
            path = Path(filename)
            try:
                path.unlink()  # Export 直接生成图片；不改变选中页或放映位置。
                presentation.Slides.Item(slide).Export(str(path), "PNG", output_width, height)
                content = path.read_bytes()
                if not content.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise PptCommandError("演示软件未生成有效的预览图片")
                return content
            finally:
                path.unlink(missing_ok=True)

        return self._invoke(operation)

    def _require_document(self) -> PptState:
        state = self._read_state()
        if not state.total_slides:
            raise PptCommandError("请先打开包含幻灯片的演示文稿")
        return state

    @staticmethod
    def _validate_slide(slide: int, total: int) -> None:
        if isinstance(slide, bool) or not isinstance(slide, int) or not 1 <= slide <= total:
            raise PptCommandError(f"页码必须在 1 到 {total} 之间")

    def _goto(self, slide: int) -> None:
        state = self._require_document()
        self._validate_slide(slide, state.total_slides)
        application, _, view = self._target()
        if state.running:
            view.GotoSlide(slide)
            view.State = RUNNING
        else:
            application.ActiveWindow.View.GotoSlide(slide)

    def goto_slide(self, slide: int) -> None:
        self._invoke(lambda: self._goto(slide))

    def _step(self, delta: int) -> None:
        state = self._require_document()
        if state.current_slide is None:
            raise PptCommandError("无法读取当前页，请先在演示软件中选中一页")
        target = state.current_slide + delta
        if not 1 <= target <= state.total_slides:
            raise PptCommandError("已是第一页" if delta < 0 else "已是最后一页")
        self._goto(target)

    def next(self) -> None:
        self._invoke(lambda: self._step(1))

    def previous(self) -> None:
        self._invoke(lambda: self._step(-1))

    def set_black(self, enabled: bool) -> None:
        def operation() -> None:
            state = self._require_document()
            if not state.running:
                raise PptCommandError("请先开始放映，再切换黑屏")
            _, _, view = self._target()
            view.State = BLACK if enabled else RUNNING

        self._invoke(operation)

    def start(self, slide: int | None = None) -> None:
        def operation() -> None:
            state = self._require_document()
            target = slide if slide is not None else state.current_slide or 1
            self._validate_slide(target, state.total_slides)
            if state.running:
                if slide is not None:
                    self._goto(target)
                return
            _, presentation, _ = self._target()
            window = presentation.SlideShowSettings.Run()
            window.View.GotoSlide(target)

        self._invoke(operation)

    def stop(self) -> None:
        def operation() -> None:
            _, _, view = self._target()
            if view is not None:
                view.Exit()

        self._invoke(operation)

    def close(self) -> None:
        # 不调用 Quit，面板退出后保留用户的演示软件和文稿。
        self._application = None
        self._client = None
        if self._pythoncom is not None:
            self._pythoncom.CoUninitialize()
            self._pythoncom = None
