"""WPS 演示的 Windows COM 实现，是否开放 COM 取决于安装版本。"""

from typing import Any

from PptControl.Com import ComPptController


class WpsController(ComPptController):
    app = "wps"
    label = "WPS 演示"
    prog_ids = ("KWPP.Application", "WPP.Application")

    def _show_window(self, application: Any) -> Any:
        try:
            return super()._show_window(application)
        except Exception as exc:
            # 本机 WPS 12：Exit 后 Count 短暂为 1，Item(1) 已返回 E_BOUNDS。
            # 仅将这个已关闭窗口的边界错误视为没有放映，其他错误正常上报。
            info = getattr(exc, "excepinfo", None)
            if info and len(info) > 5 and info[5] == -2147483637:
                return None
            raise
