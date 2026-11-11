"""缓存播放栏的定位对象，每次重新读取属性；失效后重新定位。"""
from __future__ import annotations
import time

_bar = None
_hwnd = None
_cached_at = 0.0


def invalidate() -> None:
    global _bar
    _bar = None


def read_controls(hwnd: int) -> dict:
    global _bar, _hwnd, _cached_at
    from pywinauto.uia_element_info import UIAElementInfo
    from pywinauto.uia_defines import IUIA

    if _hwnd != hwnd or time.monotonic() - _cached_at > 2:
        _bar = None
        _hwnd = hwnd
    if _bar is None:
        root = UIAElementInfo(hwnd)
        for outer in root.children(control_type="Custom"):
            for bar in outer.children(control_type="Custom"):
                if any(c.name == "进度" for c in bar.children(control_type="Slider")):
                    _bar = bar
                    _cached_at = time.monotonic()
                    break
            if _bar is not None:
                break
    if _bar is not None:
        automation = IUIA()
        # 查找范围仅限播放栏，不扫描内嵌网页；属性每次读取 CurrentName。
        condition = automation.iuia.CreateOrCondition(
            automation.build_condition(control_type="Button", title="播放"),
            automation.build_condition(control_type="Button", title="暂停"),
        )
        element = _bar.element.FindFirst(automation.tree_scope["descendants"], condition)
        if element:
            name = element.CurrentName
            if element.CurrentIsEnabled and name in ("播放", "暂停"):
                return {"status": "playing" if name == "暂停" else "paused", "controls_ready": True,
                        **_read_progress(automation)}
    _bar = None
    return {"status": "unknown", "controls_ready": False}


def _read_progress(automation) -> dict:
    """只读"进度"滑块。读不到或数值不合理时不给进度，不影响播放状态。

    不调用 SetValue：真机上它只改滑块显示，不会真的跳转。
    """
    from KugouControl.Profiles import POSITION_UNITS_PER_SECOND

    empty = {"position": None, "duration": None}
    try:
        slider = _bar.element.FindFirst(
            automation.tree_scope["children"], automation.build_condition(control_type="Slider", title="进度"))
        if not slider:
            return empty
        raw = slider.GetCurrentPattern(automation.UIA_dll.UIA_RangeValuePatternId)
        if not raw:
            return empty
        pattern = raw.QueryInterface(automation.UIA_dll.IUIAutomationRangeValuePattern)
        value, maximum = float(pattern.CurrentValue), float(pattern.CurrentMaximum)
    except Exception:
        return empty
    if maximum <= 0 or not 0 <= value <= maximum:
        return empty
    return {"position": round(value / POSITION_UNITS_PER_SECOND, 2),
            "duration": round(maximum / POSITION_UNITS_PER_SECOND, 2)}
