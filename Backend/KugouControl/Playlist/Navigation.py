"""进入音乐页，在侧栏或加歌对话框中查找歌单项。"""
from __future__ import annotations

import time
import unicodedata

from KugouControl.Profiles import PLAYLIST_LAYOUT
from KugouControl.Track import _root

from .Errors import PlaylistUnsupported
from .Scrolling import _WheelScroll
from .Ui import _clear_span, _click, _clickable, _find, _unique, _visible


def _key(text):
    return "".join(unicodedata.normalize("NFKC", text or "").split()).casefold()


def _nav(root):
    found = [e for e in _find(root, "List", PLAYLIST_LAYOUT["nav_list"], 8) if _visible(e)]
    return found[0] if len(found) == 1 else None


def _ensure_nav(hwnd, deadline):
    root = _root(hwnd)
    nav = _nav(root)
    if nav is not None:
        return nav
    # 搜索结果页等页面没有左侧导航；面板搜歌播放后酷狗就停在搜索页，先回到顶部「音乐」页。
    tab = _unique((e for e in _find(root, "TabItem", PLAYLIST_LAYOUT["music_tab"], 4) if _visible(e)),
                  "找不到酷狗顶部的「音乐」页签，请恢复酷狗主界面后重新检测")
    _click(hwnd, tab)
    while time.monotonic() < deadline:
        time.sleep(0.2)
        nav = _nav(_root(hwnd))
        if nav is not None:
            return nav
    raise PlaylistUnsupported("已切到酷狗「音乐」页，但左侧导航没有出现，请在酷狗中打开「我的收藏」后重新检测")


def _nav_items(nav, children=None):
    """侧栏里已实例化的项：[(下标, 名字, 元素)]。下标在滚动前后不变，没实例化的项名字为空。"""
    if children is None:
        children = nav.children()
    return [(index, name, child) for index, child in enumerate(children) if (name := (child.name or '').strip())]


def _reveal_entry(scroller, nav, index, name, deadline, *, bottom=None):
    """把侧栏第 index 项滚到完整可见；半露在播放栏下面的项点中心会点到播放栏。"""
    for _ in range(30):
        view = nav.rectangle
        items = {i: (label, element) for i, label, element in _nav_items(nav)}
        label, item = items.get(index, (None, None))
        if item is not None:
            if label != name:
                raise PlaylistUnsupported('酷狗歌单列表在定位期间发生变化，请重新检测')
            if _clickable(item, view, bottom=bottom):
                return item
        if time.monotonic() >= deadline:
            break
        if item is not None:
            moved = scroller.nudge(1 if item.rectangle.bottom > _clear_span(item, view, bottom=bottom)[1] else -1,
                                    deadline)
        elif items and scroller.per_notch:
            # 名称唯一性已经证明。按当前槽位估算回跳距离，随后仍回读名称和可点击范围。
            middle = min(items, key=lambda i: abs((items[i][1].rectangle.top + items[i][1].rectangle.bottom) / 2
                                                   - (view.top + view.bottom) / 2))
            rect = items[middle][1].rectangle
            pixels = (index - middle) * (rect.bottom - rect.top)
            notches = int(pixels / scroller.per_notch) or (1 if pixels > 0 else -1)
            moved = scroller.nudge(max(-40, min(40, notches)), deadline)
        elif items:
            moved = scroller.down(-1 if index < min(items) else 1, deadline=deadline)
        else:
            break
        if not moved:
            break
    raise PlaylistUnsupported("歌单在酷狗侧栏里无法完整显示，请把酷狗窗口拉高后重新检测")


def _find_entry(hwnd, nav, wanted, deadline, *, exact_only=False, bottom=None, unique=True):
    """在侧栏找到歌单：名字完全相同优先，否则唯一包含匹配。返回 (侧栏项, 酷狗里的完整歌单名)。

    exact_only：加歌时只认完全同名，不能因为包含匹配把歌加进别的歌单。
    unique=False：点播时用。检测已经读完整个侧栏确认过没有重名，点播找到第一个完全同名项就停，
    否则每次点播都要把几十个歌单从头读到尾（真机约 11 秒），超出定位预算只能退回搜索。
    """
    fixed = PLAYLIST_LAYOUT["nav_fixed"]
    names = {}
    first = nav.children()
    count = len(first)
    live = {}

    def look(children=None):
        nonlocal live
        if children is None:
            children = nav.children()
        if len(children) != count:
            raise PlaylistUnsupported('酷狗歌单列表在定位期间发生变化，请重新检测')
        live = {index: name for index, name, _ in _nav_items(nav, children)}
        for index, name in live.items():
            if index in names and names[index] != name:
                raise PlaylistUnsupported('酷狗歌单列表在定位期间发生变化，请重新检测')
            names[index] = name

    def header():
        return min((index for index, name in names.items() if name == PLAYLIST_LAYOUT["own_header"]), default=None)

    def playlist_hits():
        start = header()
        return [] if start is None else [(index, name) for index, name in names.items()
                                         if index > start and name == wanted and name not in fixed]

    def covered():
        # 歌单都在「自建歌单」标题之后；标题之前是「发现音乐」「我的音乐」等固定入口，加歌对话框里还有
        # 始终隐藏、读不到名字的分组标题（2026-11-18 真机）。只要求标题之后的槽位全部读到名字。
        start = header()
        return start is not None and all(index in names for index in range(start + 1, count))

    def found():
        return not unique and bool(playlist_hits())

    scroller = _WheelScroll(hwnd, nav)
    own_header = PLAYLIST_LAYOUT["own_header"]
    look(first)
    # 先看当前位置。看不到自建歌单标题才回绕；看到标题即可停，无需继续试探固定入口所在的顶部。
    for rewind in (header() is None, True):
        if rewind and not covered() and not found():
            while own_header not in live.values() and scroller.nudge(-40, deadline):
                look()
        while not covered() and not found():
            if not scroller.down(fraction=0.95, deadline=deadline):
                break
            look()
        if covered() or time.monotonic() >= deadline or found():
            break
    hits = playlist_hits()
    if len(hits) > 1:
        raise PlaylistUnsupported(f"酷狗里有多个名为「{wanted}」的歌单，请改成不同的名字")
    if not covered() and not (hits and not unique):
        raise PlaylistUnsupported(f"酷狗歌单列表未完整读取，无法确认「{wanted}」是否唯一")
    if hits:
        index, full = hits[0]
    elif exact_only:
        raise PlaylistUnsupported(f"列表里找不到名为「{wanted}」的歌单")
    else:
        start = header()
        playlists = list(dict.fromkeys(name for index, name in sorted(names.items())
                                       if index > start and name not in fixed))
        matched = [name for name in playlists if _key(wanted) in _key(name)]
        indices = [index for index, name in names.items() if matched and name == matched[0]]
        if len(matched) == 1 and len(indices) == 1:
            index, full = indices[0], matched[0]
        elif len(matched) > 1:
            raise PlaylistUnsupported(f"有 {len(matched)} 个歌单名包含「{wanted}」：{'、'.join(matched[:8])}，请填写完整名称")
        elif len(matched) == 1:
            raise PlaylistUnsupported(f"酷狗里有多个名为「{matched[0]}」的歌单，请改成不同的名字")
        else:
            shown = "、".join(playlists[:12]) + ("…" if len(playlists) > 12 else "")
            raise PlaylistUnsupported(f"酷狗侧栏里没有名字包含「{wanted}」的歌单"
                                      + (f"。现有歌单：{shown}" if shown else "；如果「自建歌单」是收起的，请在酷狗里展开"))
    return _reveal_entry(scroller, nav, index, full, deadline, bottom=bottom), full
