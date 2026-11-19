"""通过 ScrollPattern 或滚轮滚动，记录列表是否连续移动。"""
from __future__ import annotations

import time

from KugouControl import Input
from KugouControl.Profiles import PLAYLIST_LAYOUT

from .Errors import PlaylistUnsupported


def _layout(container):
    """列表里已实例化的项（名字非空）及其位置；滚动后名字或位置会变。"""
    return tuple(((index, child.name), child.rectangle.top) for index, child in enumerate(container.children()) if child.name)


def _steady(read, last, deadline):
    end = min(deadline, time.monotonic() + 1.2)
    while time.monotonic() < end:
        time.sleep(min(0.08, max(0, end - time.monotonic())))
        now = read()
        if now == last:
            return now
        last = now
    return None


def _unique_tops(layout):
    tops, repeated = {}, set()
    for (_, name), top in layout:
        if name in tops:
            repeated.add(name)
        tops[name] = top
    return {name: top for name, top in tops.items() if name not in repeated}


class _PatternScroll:
    """支持 ScrollPattern 的列表（其他 UIA 提供者）。"""

    def __init__(self, scroll):
        self.scroll = scroll
        self.contiguous = True

    def top(self, deadline):
        self.scroll.SetScrollPercent(-1, 0)
        time.sleep(0.1)
        if self.scroll.CurrentVerticalScrollPercent != 0:
            raise PlaylistUnsupported("歌单列表没有响应滚动，无法确认成员")

    def at_end(self):
        return self.scroll.CurrentVerticalScrollPercent >= 100

    def _step(self, fraction, limit):
        size = getattr(self.scroll, 'CurrentVerticalViewSize', 0)
        if not 0 < size <= 100:
            self.contiguous = False
            return limit
        return min(limit, fraction * size)

    def position(self):
        return self.scroll.CurrentVerticalScrollPercent

    def restore(self, position):
        self.scroll.SetScrollPercent(-1, position)
        time.sleep(0.1)

    def down(self):
        before = self.position()
        requested = min(100, before + self._step(0.75, 20))
        self.restore(requested)
        after = self.position()
        if after > requested + 0.001:
            self.contiguous = False
        return after > before

    def nudge(self, notches):
        before = self.position()
        self.restore(max(0, min(100, before + self._step(0.3, 5) * notches)))
        return self.position() != before


class _WheelScroll:
    """酷狗 10.2.52 的列表：没有 ScrollPattern，只能投递滚轮。"""

    def __init__(self, hwnd, container):
        self.hwnd, self.container, self.per_notch = hwnd, container, 0.0
        self.unsettled = False

    def wheel(self, notches, deadline=float('inf')):
        """投递滚轮并等列表停稳；位置没有变化时返回 False，不能据此认定到达边界。"""
        if time.monotonic() >= deadline:
            return False
        self.unsettled = False
        before = _layout(self.container)
        rect = self.container.rectangle
        Input.wheel(self.hwnd, (rect.left + rect.right) / 2, (rect.top + rect.bottom) / 2, notches)
        # 滚轮是投递的消息，酷狗忙（刚切页、刚加载）时要过一会儿才处理；先等列表开始变化，
        # 否则马上连读两次都没变就会误判成「滚不动」，侧栏读不全（2026-11-18 真机连续检测时复现）。
        end = min(deadline, time.monotonic() + PLAYLIST_LAYOUT["wheel_start"])
        while (changed := _layout(self.container)) == before:
            if time.monotonic() >= end:
                return False
            time.sleep(min(PLAYLIST_LAYOUT['wheel_poll'], max(0, end - time.monotonic())))
        after = _steady(lambda: _layout(self.container), changed, deadline)
        if after is None or after == before:
            self.unsettled = True
            return False
        if abs(notches) == 1:
            # 只用滚一格的观测，取最大值：估大了只是多滚几次，估小了（比如在列表边缘只滚了半格）才会跳过行。
            tops = _unique_tops(before)
            direction = 1 if notches > 0 else -1
            shifts = {(tops[name] - top) * direction for name, top in _unique_tops(after).items() if name in tops}
            if len(shifts) == 1:
                self.per_notch = max(self.per_notch, shifts.pop())
        return True

    def top(self, deadline):
        while self.wheel(-40, deadline):
            pass

    def down(self, direction=1, *, fraction=0.85, deadline=float('inf')):
        # 歌曲靠相邻视口的重叠证明连续；侧栏有稳定槽位，允许更靠近一屏。
        view = self.container.rectangle
        pixels = (view.bottom - view.top) * fraction
        notches = max(1, int(pixels // self.per_notch)) if self.per_notch else 1
        return self.wheel(direction * notches, deadline)

    def nudge(self, notches, deadline=float('inf')):
        return self.wheel(notches, deadline)
