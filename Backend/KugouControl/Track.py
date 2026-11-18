"""按歌名播放、跳转进度：都通过向酷狗投递鼠标键盘消息完成，结果用窗口标题和进度条核验。

酷狗搜索结果页是画出来的，界面自动化读不到文字，所以不能先看结果再选：
搜「歌名 歌手」后播单曲列表第一条，再看窗口标题是不是要的那首，不是就报错。
"""

from __future__ import annotations

import time

import win32con

from KugouControl import Input
from KugouControl.Profiles import POSITION_UNITS_PER_SECOND, SEARCH_LAYOUT, parse_title, same_track
from KugouControl.Version import discover


class TrackFailed(Exception):
    """已经操作了酷狗，但没核验到预期结果。"""


class TrackLoading(TrackFailed):
    """酷狗已经点开这首歌，但一直在连接，还没开始播放。"""


def _find(element, control_type: str, name: str, depth: int = 3):
    for child in element.children():
        if child.control_type == control_type and child.name == name:
            return child
        if depth:
            found = _find(child, control_type, name, depth - 1)
            if found:
                return found
    return None


def _root(hwnd: int):
    from pywinauto.uia_element_info import UIAElementInfo
    return UIAElementInfo(hwnd)


def _pattern(element, name: str):
    from pywinauto.uia_defines import IUIA
    dll = IUIA().UIA_dll
    raw = element.element.GetCurrentPattern(getattr(dll, f"UIA_{name}PatternId"))
    return raw.QueryInterface(getattr(dll, f"IUIAutomation{name}Pattern")) if raw else None


def _wait(check, seconds: float, step: float = 0.15):
    deadline = time.monotonic() + seconds
    while True:
        value = check()
        if value or time.monotonic() >= deadline:
            return value
        time.sleep(step)


def _settle(hwnd: int, area, scale: float, seconds: float, changed_from: bytes | None = None) -> bytes | None:
    """等结果列表的画面换掉旧内容并停稳（结果页读不到文字，只能看画面）；到时间还没等到就照常往下走。"""

    top, bottom = (area.top + offset * scale for offset in SEARCH_LAYOUT["rows"])
    deadline = time.monotonic() + seconds
    last = None
    while True:
        time.sleep(0.4)
        shot = Input.capture(hwnd, top, bottom)
        if (shot == last and shot != changed_from) or time.monotonic() >= deadline:
            return shot
        last = shot


def seek(hwnd: int, position: float) -> None:
    slider = _find(_root(hwnd), "Slider", "进度", depth=2)
    progress = _pattern(slider, "RangeValue") if slider else None
    if not progress or progress.CurrentMaximum <= 0:
        raise TrackFailed("没找到酷狗进度条，或当前没有可跳转的歌曲")
    maximum = float(progress.CurrentMaximum)
    target = min(max(position * POSITION_UNITS_PER_SECOND, 0.0), maximum * 0.995)
    box = slider.rectangle
    Input.click(hwnd, box.left + (box.right - box.left) * target / maximum, (box.top + box.bottom) // 2)
    # 进度条按像素取整，落点和目标会差一点；跳转后酷狗还要缓冲一两秒才继续走。
    tolerance = max(3 * POSITION_UNITS_PER_SECOND, maximum * 0.02)
    if not _wait(lambda: abs(float(progress.CurrentValue) - target) <= tolerance, 2):
        raise TrackFailed("已点击酷狗进度条，但进度没有跳到目标位置")


def _current(pid: int) -> tuple[str, str]:
    info = discover()
    return parse_title(info.get("window_title", "")) if info.get("pid") == pid else ("", "")


def play_track(hwnd: int, pid: int, title: str, artist: str, *, playlist: str = '',
               in_playlist: bool | None = None) -> dict:
    from KugouControl.Playlist import PlaylistMiss, PlaylistUnsupported, play_from_playlist
    missed = False
    if playlist and in_playlist is not False:
        try:
            play_from_playlist(hwnd, pid, playlist, title, artist)
            return {'via': 'playlist', 'in_playlist': True}
        except PlaylistMiss:
            missed = True
        except PlaylistUnsupported:
            pass  # 尚未点击歌曲且没有可靠入口，继续原搜索路径。
        except TrackFailed as exc:
            exc.via = 'playlist'
            raise
    try:
        _play_search(hwnd, pid, title, artist)
    except TrackFailed as exc:
        exc.via = 'search'
        exc.playlist_missed = missed
        raise
    return {'via': 'search', 'playlist_missed': missed}


def _play_search(hwnd: int, pid: int, title: str, artist: str) -> None:
    deadline = time.monotonic() + 24

    def budget(seconds):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TrackFailed('酷狗搜索播放超时，命令不会自动重试')
        return min(seconds, remaining)

    query = f"{title} {artist}".strip()
    if not title.strip():
        raise TrackFailed("歌曲没有歌名，无法在酷狗搜索")
    root = _root(hwnd)
    box = _find(root, "Edit", "搜索")
    text = _pattern(box, "Value") if box else None
    if not text:
        raise TrackFailed("没找到酷狗搜索框，请恢复酷狗主界面")
    edit = box.rectangle
    scale = (edit.bottom - edit.top) / SEARCH_LAYOUT["search_box_height"]

    # 已经停在上一次的搜索结果页：记下旧画面，回车后等它换成新结果，免得点到上一次搜出来的歌。
    shown = _find(root, "Tab", "搜索", depth=2)
    shown = _find(shown, "Custom", "内嵌页", depth=2) if shown else None
    old = Input.capture(hwnd, *(shown.rectangle.top + offset * scale for offset in SEARCH_LAYOUT["rows"]))         if shown and text.CurrentValue != query else None
    Input.click(hwnd, (edit.left + edit.right) / 2, (edit.top + edit.bottom) / 2)
    time.sleep(0.2)
    Input.press(hwnd, win32con.VK_END)
    Input.press(hwnd, win32con.VK_BACK, len(text.CurrentValue or "") + 2)
    if not _wait(lambda: not text.CurrentValue, budget(1.5)):
        raise TrackFailed("清不掉酷狗搜索框里原来的字，请手动清空后重试")
    Input.type_text(hwnd, query)
    if not _wait(lambda: text.CurrentValue == query, budget(1.5)):
        raise TrackFailed("搜索词没有写进酷狗搜索框，请恢复酷狗主界面后重试")
    before = _current(pid)
    Input.press(hwnd, win32con.VK_RETURN)

    tab = _wait(lambda: _find(root, "Tab", "搜索", depth=2), budget(3))
    page = _find(tab, "Custom", "内嵌页", depth=2) if tab else None
    if not page:
        raise TrackFailed("酷狗没有打开搜索结果页")
    area = page.rectangle
    if old is None:
        time.sleep(1.0)  # 结果页刚打开，先让它开始加载
    listed = _settle(hwnd, area, scale, budget(SEARCH_LAYOUT["results_wait"]), changed_from=old)
    tab_x, tab_y = SEARCH_LAYOUT["songs_tab"]
    Input.click(hwnd, area.left + tab_x * scale, area.top + tab_y * scale)
    _settle(hwnd, area, scale, budget(SEARCH_LAYOUT["songs_wait"]), changed_from=listed)
    row_x, row_y = SEARCH_LAYOUT["first_song"]
    row = (area.left + row_x * scale, area.top + row_y * scale)

    # 没缓存的歌要加载几秒到十几秒，这期间窗口标题是空的；标题出来后再判断是不是要播的那首。
    Input.click(hwnd, *row, double=True)
    started = time.monotonic()
    clicked_again = False
    while time.monotonic() - started < SEARCH_LAYOUT["play_wait"] and time.monotonic() < deadline:
        time.sleep(0.2)
        now = _current(pid)
        if same_track(*now, title, artist):
            return
        if now[0] and now != before:
            raise TrackFailed(f"酷狗搜索「{query}」的第一条是「{now[1]} - {now[0]}」，不是要播的歌；"
                              "请核对曲库里的歌名、歌手，或在酷狗里手动选")
        if now[0] and now == before and time.monotonic() - started > 3:
            # 标题一直没动：结果加载慢时第一次双击会落空，补点一次；再过几秒还没动就是没搜到。
            if clicked_again and time.monotonic() - started > 7:
                break
            if not clicked_again:
                Input.click(hwnd, *row, double=True)
                clicked_again = True
    if not _current(pid)[0]:
        # 标题一直是空的：酷狗点开了这首歌但停在"正在连接"。网络慢时要等二三十秒，也可能一直连不上。
        raise TrackLoading(f"酷狗还在连接「{query}」，没有开始播放；开始播放后面板会自动更新，"
                           "一直不响请检查网络或换一首（这首歌在酷狗可能受版权、会员限制）")
    raise TrackFailed(f"已在酷狗搜索「{query}」，但没有开始播放；请检查网络、搜索结果和酷狗弹窗")
