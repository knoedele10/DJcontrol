"""Microsoft PowerPoint 的 Windows COM 实现。"""

from typing import Any

from PptControl.Com import ComPptController
from PptControl.Base import PptUnavailable


class PowerPointController(ComPptController):
    app = "powerpoint"
    label = "PowerPoint"
    prog_ids = ("PowerPoint.Application",)

    def _validate_application(self, application: Any) -> None:
        path = str(application.Path).replace("\\", "/").casefold()
        if "kingsoft" in path or "wps office" in path:
            raise PptUnavailable("PowerPoint 的兼容接口当前指向 WPS，请选择 WPS 演示或修复 Office 的 COM 注册")
