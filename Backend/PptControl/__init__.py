"""统一 PPT 控制入口。"""

from PptControl.Base import PptApp, PptCommandError, PptController, PptError, PptState, PptUnavailable
from PptControl.PowerPoint import PowerPointController
from PptControl.Wps import WpsController


def create_controller(app: PptApp) -> PptController:
    if app == "powerpoint":
        return PowerPointController()
    if app == "wps":
        return WpsController()
    raise ValueError(f"未知 PPT 软件：{app}")


__all__ = [
    "PptApp", "PptController", "PptState", "PptError", "PptUnavailable",
    "PptCommandError", "PowerPointController", "WpsController", "create_controller",
]
