"""歌单操作：仅使用能回读的页面和歌曲身份；没有证据时不猜坐标或报告成功。

所有对象仅在 Worker 的 COM 线程使用，父进程只接收可序列化的快照。

酷狗 10.2.52 的真机结构（2026-11-18 探测）：
- 左侧导航只在顶部「音乐」页出现：Pane「导航」→ List「导航」。项名是完整歌单名（界面文字可能被截断），
  没有 ScrollPattern，滚出视口的项名字为空、矩形为零，只能投递鼠标滚轮滚动；UIA 的 Select() 不会让页面跳转。
- 歌单页的标题是 Text「歌单名」；歌曲在 Pane「单曲」→ List「单曲」的 ListItem 里，名字形如
  '<a 歌名>歌名</a>，歌手:甲、乙，专辑:…，时长:02:33'。列表同样只能滚轮滚动，末尾可能残留一行旧内容。
- 页面里有隐藏的 Text「歌单名」和「共 N 首歌曲」，用来确认成员是否读全。
"""
from __future__ import annotations

import re
import time
import unicodedata

import win32con

from KugouControl import Input
from KugouControl.Profiles import PLAYLIST_ADD_SOFT_TIMEOUT, PLAYLIST_LAYOUT, exact_track
from KugouControl.Track import TrackFailed, TrackLoading, _current, _pattern as _get_pattern, _root


def _pattern(element, name):
    try:
        return _get_pattern(element, name)
    except Exception:
        # UIA_E_NOTSUPPORTED 是可选 pattern 缺失，不把它当成已经支持。
        return None


class PlaylistMiss(TrackFailed):
    """完整读取或明确空结果证明该歌曲不在歌单内，可安全回退搜索。"""


class PlaylistUnsupported(TrackFailed):
    """尚未尝试播放：当前页面没有可靠定位方式，可沿用搜索。"""


def _walk(root, depth=10):
    yield root
    if depth:
        for child in root.children():
            yield from _walk(child, depth - 1)


def _find(root, control_type, name=None, depth=14):
    """按控件类型（和名字）查后代。真实 UIA 元素用一次 FindAll 条件查询，比逐层遍历快约 10 倍；测试替身逐层遍历。"""
    descendants = getattr(root, "descendants", None)
    if descendants is not None:
        return descendants(control_type=control_type, **({} if name is None else {"title": name}))
    return [e for e in _walk(root, depth) if e is not root and e.control_type == control_type
            and (name is None or e.name == name)]


def _visible(element):
    rect = element.rectangle
    return element.visible and rect.right > rect.left and rect.bottom > rect.top


def _unique(elements, message):
    found = list(elements)
    if len(found) != 1:
        raise PlaylistUnsupported(message)
    return found[0]


def _click(hwnd, element, *, double=False):
    if not _visible(element):
        raise TrackFailed("歌单目标已不可见，请重新检测")
    rect = element.rectangle
    Input.click(hwnd, (rect.left + rect.right) / 2, (rect.top + rect.bottom) / 2, double=double)


def _clear_span(element, view, *, bottom=None):
    """元素落在列表视口里、又避开下沿被播放栏进度条压住那一条的纵向范围。UIA 对半露的项仍报可见。"""
    rect = element.rectangle
    limit = view.bottom - PLAYLIST_LAYOUT["edge_margin"] if bottom is None else min(bottom, view.bottom)
    return max(rect.top, view.top), min(rect.bottom, limit)


def _clickable(element, view, *, bottom=None):
    """可点击部分至少占行高的 60%；列表滚到底时最后一行贴着下沿，也能点到它露出来的部分。"""
    rect = element.rectangle
    top, bottom = _clear_span(element, view, bottom=bottom)
    return (_visible(element) and rect.left >= view.left and rect.right <= view.right
            and bottom - top >= 0.6 * (rect.bottom - rect.top))


def _click_clear(hwnd, element, view, *, double=False, bottom=None, x=None):
    """点可点击部分的纵向中心；横向默认取中点，x 给定时按它点。"""
    rect = element.rectangle
    top, bottom = _clear_span(element, view, bottom=bottom)
    Input.click(hwnd, (rect.left + rect.right) / 2 if x is None else x, (top + bottom) / 2, double=double)


def _row_blank_x(row):
    """歌曲行最右端、时长右边的空白处。

    行的水平中点落在歌手列上，歌手名是链接：歌手名够长时双击中点会跳到歌手页而不是播放（2026-11-18 真机，
    「Toby Fox」）。时长是普通文字，它右边到行尾是空白，双击这里等于双击整行。
    """
    rect = row.rectangle
    return rect.right - max(8, (rect.right - rect.left) * PLAYLIST_LAYOUT["row_blank_right"])


def _key(text):
    return "".join(unicodedata.normalize("NFKC", text or "").split()).casefold()


# ---- 滚动：酷狗的列表没有 ScrollPattern，投递滚轮后等动画停下再读 ----

def _layout(container):
    """列表里已实例化的项（名字非空）及其位置；滚动后名字或位置会变。"""
    return tuple(((index, child.name), child.rectangle.top) for index, child in enumerate(container.children()) if child.name)


def _steady(read, seconds=1.2):
    last = read()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        time.sleep(0.08)
        now = read()
        if now == last:
            return now
        last = now
    return last


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

    def wheel(self, notches):
        """投递滚轮并等列表停稳；位置没有变化时返回 False，不能据此认定到达边界。"""
        before = _layout(self.container)
        rect = self.container.rectangle
        Input.wheel(self.hwnd, (rect.left + rect.right) / 2, (rect.top + rect.bottom) / 2, notches)
        # 滚轮是投递的消息，酷狗忙（刚切页、刚加载）时要过一会儿才处理；先等列表开始变化，
        # 否则马上连读两次都没变就会误判成「滚不动」，侧栏读不全（2026-11-18 真机连续检测时复现）。
        end = time.monotonic() + PLAYLIST_LAYOUT["wheel_start"]
        while _layout(self.container) == before:
            if time.monotonic() >= end:
                return False
            time.sleep(0.05)
        after = _steady(lambda: _layout(self.container))
        if after == before:
            return False
        tops = dict(before)
        shifts = [abs(tops[name] - top) for name, top in after if name in tops]
        if shifts and abs(notches) == 1:
            # 只用滚一格的观测，取最大值：估大了只是多滚几次，估小了（比如在列表边缘只滚了半格）才会跳过行。
            self.per_notch = max(self.per_notch, max(shifts))
        return True

    def top(self, deadline):
        while time.monotonic() < deadline and self.wheel(-40):
            pass

    def at_end(self):
        return False

    def down(self, direction=1):
        # 每次最多滚过视口的 3/4，相邻两屏有重叠，不会漏行；还没测出每格距离时先滚一格。
        view = self.container.rectangle
        notches = max(1, int((view.bottom - view.top) * 0.75 // self.per_notch)) if self.per_notch else 1
        return self.wheel(direction * notches)

    def nudge(self, notches):
        return self.wheel(notches)


# ---- 左侧导航：找到歌单项 ----

def _nav(root):
    found = [e for e in _find(root, "List", PLAYLIST_LAYOUT["nav_list"], 8) if _visible(e)]
    return found[0] if len(found) == 1 else None


def _ensure_nav(hwnd, deadline):
    nav = _nav(_root(hwnd))
    if nav is not None:
        return nav
    # 搜索结果页等页面没有左侧导航；面板搜歌播放后酷狗就停在搜索页，先回到顶部「音乐」页。
    tab = _unique((e for e in _find(_root(hwnd), "TabItem", PLAYLIST_LAYOUT["music_tab"], 4) if _visible(e)),
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
        items = {i: element for i, _, element in _nav_items(nav)}
        item = items.get(index)
        if item is not None:
            if (item.name or '').strip() != name:
                raise PlaylistUnsupported('酷狗歌单列表在定位期间发生变化，请重新检测')
            if _clickable(item, view, bottom=bottom):
                return item
        if time.monotonic() >= deadline:
            break
        if item is not None:
            moved = scroller.nudge(1 if item.rectangle.bottom > _clear_span(item, view, bottom=bottom)[1] else -1)
        elif items and index > max(items):
            moved = scroller.down()
        else:
            moved = scroller.nudge(-PLAYLIST_LAYOUT["scan_notches"])
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
    count = len(nav.children())

    def look():
        children = nav.children()
        if len(children) != count:
            raise PlaylistUnsupported('酷狗歌单列表在定位期间发生变化，请重新检测')
        for index, name, _ in _nav_items(nav, children):
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
    # 从当前位置读到尾，再从顶部补读。短期滚不动不能证明到尾；歌单段每个槽位都看到名字才能判断唯一。
    for rewind in (False, True):
        if rewind:
            scroller.top(deadline)
        look()
        while not covered() and time.monotonic() < deadline and not found():
            if not scroller.down():
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


# ---- 歌单页：确认是目标歌单，读出成员 ----

def _collection(page):
    lists = [e for kind in ("DataGrid", "Table", "List") for e in _find(page, kind) if _visible(e)]
    named = [e for e in lists if e.name in PLAYLIST_LAYOUT["song_lists"]]
    if named:
        return _unique(named, "歌单没有唯一可识别的歌曲列表")
    tables = [e for e in lists if e.control_type in ("DataGrid", "Table") and _track_columns(_headers(e)) is not None]
    return _unique(tables, "歌单没有唯一可识别的歌曲列表")


def _page(hwnd, name, nav):
    """右侧内容区里可见的标题 Text 等于完整歌单名，且同一区域里有唯一可见的歌曲列表，才算目标歌单页。"""
    right = nav.rectangle.right
    titles = [e for e in _find(_root(hwnd), "Text", name, 12) if _visible(e) and e.rectangle.left >= right]
    pages = []
    for title in titles:
        # 往上走到仍在侧栏右边的最外层容器，就是整块歌单页；再往上会把侧栏也包进来。
        area, current = None, title.parent
        while current is not None and _visible(current) and current.rectangle.left >= right:
            area, current = current, current.parent
        if area is None:
            continue
        try:
            collection = _collection(area)
        except PlaylistUnsupported:
            continue
        if title.rectangle.bottom <= collection.rectangle.top:
            pages.append(area)
    return _unique(pages, "无法回读唯一歌单正文，不能把侧栏选中状态当成页面已就绪")


def _current_page(hwnd, name):
    nav = _nav(_root(hwnd))
    if nav is None:
        raise PlaylistUnsupported('酷狗歌单页已切换，请重新操作')
    return _page(hwnd, name, nav)


def open_playlist(hwnd: int, name: str, deadline: float | None = None, *, exact_only=False, unique=True):
    """打开歌单页，返回 (页面区域, 酷狗里的完整歌单名)。

    unique=False（点播）：已经停在这个歌单页就直接用；否则找到第一个完全同名的侧栏项就打开。
    """
    wanted = (name or "").strip()
    if not wanted:
        raise PlaylistUnsupported("尚未配置演出歌单")
    deadline = deadline or time.monotonic() + PLAYLIST_LAYOUT["wait"]
    nav = _ensure_nav(hwnd, deadline)
    if not unique:
        try:
            return _page(hwnd, wanted, nav), wanted
        except PlaylistUnsupported:
            pass
    bottom = _list_bottom(_root(hwnd), nav.rectangle)
    entry, full = _find_entry(hwnd, nav, wanted, deadline, exact_only=exact_only, bottom=bottom, unique=unique)
    try:
        return _page(hwnd, full, nav), full
    except PlaylistUnsupported:
        pass
    if time.monotonic() >= deadline or not _clickable(entry, nav.rectangle, bottom=bottom):
        raise PlaylistUnsupported(f"歌单「{full}」未能在限定时间内定位到可点击位置")
    _click_clear(hwnd, entry, nav.rectangle, bottom=bottom)
    while time.monotonic() < deadline:
        try:
            return _page(hwnd, full, nav), full
        except PlaylistUnsupported:
            time.sleep(0.15)
    raise PlaylistUnsupported(f"歌单「{full}」页面无法可靠读取")


def _headers(collection):
    return [e.name.strip() for e in _find(collection, "HeaderItem", depth=3)]


def _track_columns(headers):
    title = [i for i, name in enumerate(headers) if name in PLAYLIST_LAYOUT["title_headers"]]
    artist = [i for i, name in enumerate(headers) if name in PLAYLIST_LAYOUT["artist_headers"]]
    return (title[0], artist[0]) if len(title) == len(artist) == 1 else None


def _labelled_row(name):
    """只认完整结构；缺时长的残留行或字段分界不明的行保持未知。"""
    if not name.startswith("<a ") or "</a>，歌手:" not in name:
        return None
    link, _, rest = name[3:].partition("</a>，歌手:")
    half = (len(link) - 1) // 2
    # 链接写成「<a 歌名>歌名」，歌名本身可能含 ">"，按前后两半相同来切。
    if not (len(link) % 2 and link[half] == '>' and link[:half] == link[half + 1:]):
        return None
    title = link[:half].strip()
    fields, separator, length = rest.rpartition('，时长:')
    if not separator or not re.fullmatch(r'(?:[0-9]+:)?[0-9]+:[0-5][0-9]', length.strip()):
        return None
    if fields.count('，专辑:') > 1:
        return None
    artist, has_album, album = fields.partition('，专辑:')
    if not title or not artist.strip():
        return None
    duration = 0
    for part in length.split(':'):
        duration = 60 * duration + int(part)
    track = {'title': title, 'artist': artist.strip(), 'duration': duration}
    if has_album:
        track['album'] = album.strip()
    return track


def _row_track(row, headers):
    labelled = _labelled_row(row.name or "")
    if labelled:
        return labelled
    cells = [e for e in row.children() if e.control_type in ("Text", "DataItem", "Custom")]
    # 只根据可读列标题确定列含义，不猜第一列一定是歌名。
    columns = _track_columns(headers)
    if columns is not None and len(cells) == len(headers):
        title, artist = (cells[index].name.strip() for index in columns)
        if title and artist:
            return {"title": title, "artist": artist}
    # 一些 provider 将列名直接放在单元格名称前。
    values = {}
    for cell in cells:
        label, separator, value = cell.name.partition("：")
        if not separator:
            label, separator, value = cell.name.partition(":")
        if separator and value.strip():
            if label in PLAYLIST_LAYOUT["title_headers"]:
                values["title"] = value.strip()
            elif label in PLAYLIST_LAYOUT["artist_headers"]:
                values["artist"] = value.strip()
    return values if set(values) == {"title", "artist"} else None


def _empty(page):
    return any(e.name.strip() in PLAYLIST_LAYOUT["empty_names"] and _visible(e) for e in _find(page, "Text"))


def _empty_playlist(page):
    # 酷狗 10.2.52 空歌单页画的是插图加「这里没内容显示~」和「发现更多音乐」按钮（2026-11-18 真机）。
    return any(e.name.strip() in PLAYLIST_LAYOUT['empty_playlist_names'] and _visible(e) for e in _find(page, 'Text'))


def _total(page, name):
    """页面里与歌单名放在一起的「共 N 首歌曲」。只认和本歌单标题同在一组的那个，避免读到上一个歌单的残留数字。"""
    counts = set()
    for text in _find(page, "Text"):
        match = re.fullmatch(r"共\s*(\d+)\s*首(?:歌曲)?", (text.name or "").strip())
        group = text.parent if match else None
        if group is not None and any(child.control_type == "Text" and (child.name or "").strip() == name
                                     for child in group.children()):
            counts.add(int(match.group(1)))
    return counts.pop() if len(counts) == 1 else None


def _rows(collection):
    view = collection.rectangle
    return [row for row in _row_slots(collection) if _in_view(row, view)]


def _row_slots(collection):
    return [row for row in collection.children() if row.control_type in ("DataItem", "ListItem")]


def _in_view(row, view):
    rect = row.rectangle
    return (_visible(row) and view.left < rect.right and rect.left < view.right
            and view.top < rect.bottom and rect.top < view.bottom)


def _scroller(hwnd, collection):
    scroll = _pattern(collection, "Scroll")
    if scroll is not None:
        return _PatternScroll(scroll) if scroll.CurrentVerticallyScrollable else None
    return _WheelScroll(hwnd, collection)


def _target_row(collection, headers, target):
    matches = [row for row in _rows(collection)
               if (track := _row_track(row, headers)) and exact_track(track["title"], track["artist"], *target)]
    if len(matches) > 1:
        # 同一屏内发现多个同身份版本也不盲选。
        raise TrackFailed("歌单内有多个同名版本，请在酷狗中只保留目标版本")
    return matches[0] if matches else None


def _reveal_row(scroller, collection, headers, target, deadline, *, index=None, bottom=None):
    for _ in range(60):
        view = collection.rectangle
        row = _target_row(collection, headers, target)
        if row is not None and _clickable(row, view, bottom=bottom):
            return row, view
        if scroller is None or time.monotonic() >= deadline:
            break
        if row is not None:
            moved = scroller.nudge(1 if row.rectangle.bottom > _clear_span(row, view, bottom=bottom)[1] else -1)
        elif isinstance(scroller, _WheelScroll) and index is not None:
            visible = [i for i, item in enumerate(_row_slots(collection)) if _in_view(item, view)]
            moved = scroller.down(-1 if visible and index < min(visible) else 1)
        else:
            break
        if not moved:
            break
    raise PlaylistUnsupported("歌单里的目标歌曲无法完整显示，保留搜索播放")


def _scan(hwnd, page, deadline, target=None, name="", *, verify_page=None):
    """读歌单成员；只在确认没有遗漏或同身份第二行后返回可点击的目标。"""
    if verify_page is not None:
        page = verify_page()
    if not _unfiltered(page):
        return [], False, None
    collection = _collection(page)
    headers = _headers(collection)
    scroller = _scroller(hwnd, collection)
    if scroller is not None:
        scroller.top(deadline)
    loading_until = min(deadline, time.monotonic() + PLAYLIST_LAYOUT["load_wait"])
    while True:
        total = _total(page, name) if name else None
        rows = _row_slots(collection)
        empty = total == 0 and not rows and _empty_playlist(page)
        if empty or any(_row_track(row, headers) for row in _rows(collection)) or time.monotonic() >= loading_until:
            break
        time.sleep(0.2)
        if verify_page is not None:
            page = verify_page()
            if _collection(page) != collection or not _unfiltered(page):
                return [], False, None

    slots, labels, locations, references, last_visible = {}, {}, {}, {}, None
    wheel = isinstance(scroller, _WheelScroll)
    stable = True
    coverage = False
    size = len(rows)
    while True:
        view = collection.rectangle
        observed = set()
        if wheel and len(rows) != size:
            stable = False
        for index, row in enumerate(rows):
            if not _in_view(row, view):
                continue
            key = index
            if isinstance(scroller, _PatternScroll):
                runtime_id = getattr(row, 'runtime_id', None)
                if runtime_id == 0:
                    scroller.contiguous = False
                key = (tuple(runtime_id) if runtime_id else ('element', id(row)))
                if not runtime_id:
                    references[key] = row
            observed.add(key)
            track = _row_track(row, headers)
            if track is not None:
                label = row.name
                if key in labels and (labels[key] != label or slots[key] != track):
                    stable = False
                labels[key] = label
            if track is not None or key not in slots:
                slots[key] = track
            if isinstance(scroller, _PatternScroll):
                locations.setdefault(key, scroller.position())
        if wheel:
            # 末尾可能残留一条只有歌名链接的行；仅在真正的槽位和总数吻合时排除这种已知残留。
            trailing_name = (rows[-1].name or '') if rows else ''
            trailing = (total is not None and size == total + 1 and trailing_name.startswith('<a ')
                        and trailing_name.endswith('</a>') and slots.get(total) is None)
            coverage = total is not None and (size == total or trailing) and all(slots.get(i) for i in range(total))
        elif scroller is None:
            coverage = len(slots) == size and not any(e.control_type == "ScrollBar" for e in _walk(collection, 2))
        else:
            if last_visible and observed and not last_visible.intersection(observed):
                scroller.contiguous = False
            last_visible = observed
            coverage = scroller.at_end() and scroller.contiguous
        if coverage or scroller is None or time.monotonic() >= deadline or not scroller.down():
            break
        rows = _row_slots(collection)

    latest = verify_page() if verify_page is not None else page
    if not stable or _collection(latest) != collection or not _unfiltered(latest):
        return [], False, None
    stable_count = not name or total == _total(latest, name)
    known = [track for track in slots.values() if track is not None]
    tracks = list({(track['title'], track['artist']): track for track in known}.values())
    if not wheel and any(track is None for track in slots.values()):
        coverage = False
    covered = stable_count and coverage and (not name or total is None or len(known) == total)
    covered = covered and time.monotonic() < deadline and not (known and _empty(latest))
    if not known:
        empty = empty and stable_count and not _row_slots(collection) and _empty_playlist(latest)
        return [], empty and covered, None

    if target:
        matches = [key for key, track in slots.items() if track and exact_track(track['title'], track['artist'], *target)]
        if len(matches) > 1:
            raise TrackFailed('歌单内有多个同名版本，请在酷狗中只保留目标版本')
        if covered and matches:
            matched = matches[0]
            if isinstance(scroller, _PatternScroll) and _target_row(collection, headers, target) is None:
                scroller.restore(locations[matched])
            bottom = _list_bottom(_root(hwnd), collection.rectangle) if verify_page is not None else None
            row = _reveal_row(scroller, collection, headers, target, deadline,
                              index=matched if wheel else None, bottom=bottom)
            if row[0].name != labels[matched] or (wheel and _row_slots(collection)[matched:matched + 1] != [row[0]]):
                raise PlaylistUnsupported('歌单歌曲行在定位期间发生变化，请重新检测')
            return tracks, False, row
    return tracks, covered and len(tracks) == len(known), None


def _filters(page):
    return [e for e in _find(page, 'Edit') if _visible(e) and e.name in PLAYLIST_LAYOUT['filter_names']]


def _unfiltered(page):
    edits = _filters(page)
    if not edits:
        return True
    value = _pattern(edits[0], 'Value') if len(edits) == 1 else None
    return value is not None and (value.CurrentValue or '') == ''


def _filter(page):
    return _unique(_filters(page), "没有可回读的歌单内搜索框")


def _set_filter(hwnd, page, query, deadline):
    edit = _filter(page)
    value = _pattern(edit, "Value")
    if not value:
        raise PlaylistUnsupported("歌单内搜索框不支持回读")
    _click(hwnd, edit)
    Input.press(hwnd, win32con.VK_END)
    Input.press(hwnd, win32con.VK_BACK, len(value.CurrentValue or '') + 2)
    end = min(deadline, time.monotonic() + 1)
    while value.CurrentValue and time.monotonic() < end:
        time.sleep(0.05)
    if value.CurrentValue:
        raise TrackFailed("无法清空歌单内搜索框")
    Input.type_text(hwnd, query)
    end = min(deadline, time.monotonic() + 1)
    while value.CurrentValue != query and time.monotonic() < end:
        time.sleep(0.05)
    if value.CurrentValue != query:
        raise TrackFailed("歌单筛选词没有写入")
    time.sleep(min(PLAYLIST_LAYOUT['filter_wait'], max(0, deadline - time.monotonic())))


def inspect(hwnd, name, *, deadline=None, exact_only=False, unique=True):
    # 部分名称要把侧栏从头到尾读一遍，比播放时按完整名定位慢，单独给预算。
    if deadline is None:
        deadline = time.monotonic() + PLAYLIST_LAYOUT['inspect_wait']
    requested = (name or '').strip()
    state = {"name": requested, "requested": requested, "route": None, "supported": False, "can_add": False,
             "complete": False, "tracks": [], "note": "", "add_note": "尚未检测加歌菜单"}
    try:
        page, full = open_playlist(hwnd, requested, deadline, exact_only=exact_only, unique=unique)
        state['name'] = full
        matched = f'已匹配酷狗歌单「{full}」；' if full != requested else ''
        try:
            _set_filter(hwnd, page, '', deadline)
        except PlaylistUnsupported:
            pass
        try:
            tracks, complete, _ = _scan(hwnd, page, deadline, name=full,
                                        verify_page=lambda: _current_page(hwnd, full))
        except PlaylistUnsupported:
            tracks, complete = [], False
        if tracks or complete:
            state.update(route='A', supported=True, tracks=tracks, complete=complete,
                         note=matched + f'通过歌曲列定位，读到 {len(tracks)} 首'
                         + ('；列表已完整读取' if complete else '；仅确认已读成员，未读部分保持未知'))
        else:
            try:
                _filter(page)
                first = PLAYLIST_LAYOUT['first_song']
                if first is None:
                    raise PlaylistUnsupported('歌曲行不可读；歌单内搜索已发现，但第一行位置尚未真机验证')
                if not _pattern(_filter(page), 'Value'):
                    raise PlaylistUnsupported('歌单内搜索无法回读')
            except PlaylistUnsupported as exc:
                raise PlaylistUnsupported(matched + str(exc)) from exc
            state.update(route='B', supported=True, note=matched + '歌单内筛选，播放后核验')
    except PlaylistUnsupported as exc:
        state['note'] = str(exc)
    return state


def _playbar(root):
    return _unique((element for element in _walk(root, 3)
                    if element.control_type == 'Custom' and _visible(element)
                    and any(child.control_type == 'Slider' and child.name == '进度' and _visible(child)
                            for child in element.children())), '无法唯一定位酷狗播放栏')


def _list_bottom(root, view, *, require_bar=False):
    try:
        bar = _playbar(root)
    except PlaylistUnsupported:
        if require_bar:
            raise
        return view.bottom - PLAYLIST_LAYOUT['edge_margin']
    overlap = [element.rectangle.top for element in _walk(bar, 1)
               if _visible(element) and (element is bar or element.control_type == 'Slider')
               and element.rectangle.left < view.right and element.rectangle.right > view.left
               and element.rectangle.bottom > view.top and element.rectangle.top < view.bottom]
    return min(overlap, default=view.bottom)


def _pause(hwnd, deadline=None):
    from KugouControl.Uia import invalidate, read_controls
    invalidate()
    state = read_controls(hwnd)
    if state['status'] == 'playing':
        bar = _playbar(_root(hwnd))
        button = _unique((e for e in _find(bar, 'Button', '暂停', 4) if _visible(e)), '无法唯一定位酷狗暂停按钮')
        _click(hwnd, button)
        end = time.monotonic() + 1.5
        if deadline is not None:
            end = min(end, deadline)
        while time.monotonic() < end:
            invalidate()
            if read_controls(hwnd)['status'] == 'paused':
                return
            time.sleep(0.1)
        raise TrackFailed('试听后无法核验酷狗已暂停，请在酷狗中手动暂停')
    if state['status'] != 'paused':
        raise TrackFailed('无法确认酷狗已暂停')


def play_from_playlist(hwnd, pid, name, title, artist):
    from KugouControl.Uia import invalidate, read_controls
    deadline = time.monotonic() + PLAYLIST_LAYOUT['wait']
    before = _current(pid)
    page, full = open_playlist(hwnd, name, deadline, exact_only=True, unique=False)
    try:
        _set_filter(hwnd, page, '', deadline)
    except PlaylistUnsupported:
        pass
    try:
        tracks, complete, row = _scan(hwnd, page, deadline, (title, artist), name=full,
                                      verify_page=lambda: _current_page(hwnd, full))
    except PlaylistUnsupported:
        tracks, complete, row = [], False, None
    if row:
        if time.monotonic() >= deadline:
            raise PlaylistUnsupported('歌单定位超过等待上限，保留搜索播放')
        original, _ = row
        expected = (original.name, _row_track(original, _headers(original.parent)))
        if exact_track(*_current(pid), title, artist):
            _pause(hwnd, deadline)
            invalidate()
        root = _root(hwnd)
        nav = _nav(root)
        if nav is None:
            raise PlaylistUnsupported('点击前无法确认目标歌单页面')
        collection = _collection(_page(hwnd, full, nav))
        headers = _headers(collection)
        fresh = _target_row(collection, headers, (title, artist))
        view = collection.rectangle
        bottom = _list_bottom(root, view, require_bar=True)
        if (fresh is None or (fresh.name, _row_track(fresh, headers)) != expected
                or not _clickable(fresh, view, bottom=bottom) or time.monotonic() >= deadline):
            raise PlaylistUnsupported('点击前无法重新确认目标歌曲行处于可点击范围')
        _click_clear(hwnd, fresh, view, bottom=bottom, double=True, x=_row_blank_x(fresh))
        deadline = time.monotonic() + PLAYLIST_LAYOUT['play_wait']  # 定位和播放核验分开计时，加载慢的歌也有时间核验
    elif complete:
        raise PlaylistMiss('歌曲不在演出歌单内')
    elif _matching_members(tracks, (title, artist)):
        raise TrackFailed('歌单尚未读全，无法确认目标歌曲是否有多个版本；请刷新歌单后再试')
    else:
        raise PlaylistUnsupported('无法在歌单内唯一定位可点击的目标歌曲，保留搜索播放')
    while time.monotonic() < deadline:
        now = _current(pid)
        invalidate()
        status = read_controls(hwnd)['status']
        if exact_track(*now, title, artist) and status == 'playing':
            return
        if now[0] and now != before and not exact_track(*now, title, artist) and status == 'playing':
            raise TrackFailed(f'歌单播放的是「{now[1]} - {now[0]}」，与目标版本不符')
        time.sleep(0.15)
    if not _current(pid)[0]:
        raise TrackLoading('歌单歌曲仍在加载，尚未核验播放成功')
    raise TrackFailed('已操作歌单，但没有核验到目标歌曲开始播放')


# ---- 加歌：播放栏「更多」→「添加到」对话框 →「选择位置」列表里选歌单 →「确定」 ----
# 真机结构（2026-11-18）：「更多」是独立的顶层窗口，「添加到」是其中的 Button；点它弹出标题为「添加到」的对话框，
# 歌单在虚拟列表 List「选择位置」里（同样没有 ScrollPattern，只能滚轮），底部是「确定」「取消」。
# 弹出窗口是另一个 HWND，点击和滚轮都要投递给它自己。

def _process_windows(pid):
    import ctypes
    import win32gui
    import win32process

    found = []

    def visit(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32process.GetWindowThreadProcessId(hwnd)[1] == pid:
            found.append(hwnd)
        return True

    # 同 Version.discover：先清掉线程 LastError，避免 EnumWindows 误抛旧错误码。
    ctypes.WinDLL("kernel32", use_last_error=False).SetLastError(0)
    win32gui.EnumWindows(visit, None)
    return found


def _popup(pid, title, known, deadline):
    import win32gui

    while True:
        found = [h for h in _process_windows(pid) if h not in known and win32gui.GetWindowText(h) == title]
        if len(found) == 1:
            return found[0]
        if time.monotonic() >= deadline:
            raise PlaylistUnsupported(f"酷狗没有弹出「{title}」窗口")
        time.sleep(0.1)


def _places(dialog):
    return _unique((element for element in _find(_root(dialog), 'List', '选择位置') if _visible(element)),
                   '「添加到」对话框里没有歌单列表')


def _destination(hwnd, pid, name, deadline, known, opened, *, check_source=None):
    """打开当前歌曲的「添加到」对话框，选中唯一匹配的歌单。"""
    bar = _playbar(_root(hwnd))
    more = _unique((e for e in _walk(bar, 3) if e.control_type == 'Button'
                   and e.name in ('更多', '更多操作', '更多功能') and _visible(e)), '播放栏没有可识别的「更多」按钮')
    if check_source is not None:
        check_source()
    if time.monotonic() >= deadline:
        raise PlaylistUnsupported('没有足够时间核验加歌对话框')
    _click(hwnd, more)
    menu = _popup(pid, '更多', known, deadline)
    opened[menu] = '更多'
    add = _unique((e for e in _find(_root(menu), 'Button', depth=4) if e.name in ('添加到', '添加到歌单')
                   and _visible(e)), '「更多」菜单里没有「添加到」')
    if check_source is not None:
        check_source()
    if time.monotonic() >= deadline:
        raise PlaylistUnsupported('没有足够时间核验加歌对话框')
    _click(menu, add)
    dialog = _popup(pid, '添加到', known | {menu}, deadline)
    opened[dialog] = '添加到'
    places = _places(dialog)
    view = places.rectangle
    _find_entry(dialog, places, name, deadline, exact_only=True, bottom=view.bottom)
    index, item = _unique(((index, element) for index, label, element in _nav_items(places)
                           if label == name and _visible(element)), f'无法重新确认歌单「{name}」的位置')
    count = len(places.children())
    if time.monotonic() >= deadline or not _clickable(item, view, bottom=view.bottom):
        raise PlaylistUnsupported(f'「添加到」对话框里无法可靠点击歌单「{name}」')
    _click_clear(dialog, item, view, bottom=view.bottom)
    selection = _pattern(item, 'SelectionItem')
    end = min(deadline, time.monotonic() + 1)
    while not (selection and selection.CurrentIsSelected) and time.monotonic() < end:
        time.sleep(0.1)
    if not (selection and selection.CurrentIsSelected):
        raise PlaylistUnsupported(f'「添加到」对话框里选不中歌单「{name}」')
    return pid, dialog, name, index, count


def _selected_destination(places, name, index, count):
    children = places.children()
    if len(children) != count or not 0 <= index < count:
        return False
    target = children[index]
    if (not _visible(target) or (target.name or '').strip() != name
            or sum((child.name or '').strip() == name for child in children) != 1):
        return False
    selection = _pattern(target, 'SelectionItem')
    if selection is None or not selection.CurrentIsSelected:
        return False
    group = _pattern(places, 'Selection')
    if group is not None and not group.CurrentCanSelectMultiple:
        return True
    for position, child in enumerate(children):
        if position == index or child.control_type not in ('ListItem', 'DataItem'):
            continue
        other = _pattern(child, 'SelectionItem')
        if other is None or other.CurrentIsSelected:
            return False
    return True


def _confirm(destination, deadline, *, check_source, mark_committed):
    """点击前复核当前歌曲和所选歌单，再等待对话框关闭。"""
    import win32gui

    pid, dialog, name, index, count = destination
    check_source()
    if dialog not in _process_windows(pid) or win32gui.GetWindowText(dialog) != '添加到':
        raise PlaylistUnsupported('加歌对话框不再有效，未点击「确定」')
    ok = _unique((e for e in _find(_root(dialog), 'Button', '确定') if _visible(e)), '「添加到」对话框里没有「确定」')
    if not _selected_destination(_places(dialog), name, index, count):
        raise PlaylistUnsupported('加歌目标已变化或无法确认唯一选中，未点击「确定」')
    if time.monotonic() >= deadline:
        raise PlaylistUnsupported('预留的核验时间不足，未点击「确定」')
    mark_committed()
    _click(dialog, ok)
    while win32gui.IsWindow(dialog) and win32gui.IsWindowVisible(dialog):
        if time.monotonic() >= deadline:
            raise TrackFailed('点了「确定」但「添加到」对话框没有关闭，请在酷狗中检查')
        time.sleep(0.1)


def _dismiss(pid, opened, *, deadline=None):
    """只取消本次已识别的窗口；不接管另一个新出现的同名对话框。"""
    import win32gui

    def live_windows():
        return [window for window in _process_windows(pid)
                if window in opened and win32gui.GetWindowText(window) == opened[window]]

    windows = live_windows() if opened else []
    if not windows:
        return
    for window in windows:
        Input.press(window, win32con.VK_ESCAPE)
    end = time.monotonic() + 1
    if deadline is not None:
        end = min(end, deadline)
    while live_windows():
        if time.monotonic() >= end:
            raise TrackFailed('无法确认加歌弹窗已取消，请在酷狗中检查')
        time.sleep(0.1)


def inspect_add(hwnd, pid, state):
    if not state['supported']:
        state['add_note'] = '无法核验加入后的歌单成员；请手动维护歌单'
        return state
    if not state['complete']:
        state['add_note'] = '尚未完整读取歌单，无法排除重复添加；请刷新歌单后再试'
        return state
    known = set(_process_windows(pid))
    opened = {}
    try:
        # 只打开对话框、找到并选中目标歌单，然后取消，不会加歌。
        _destination(hwnd, pid, state['name'], time.monotonic() + PLAYLIST_LAYOUT['add_wait'], known, opened)
        state.update(can_add=True, add_note='演出前逐首试听核验，再加入指定歌单；完成后暂停')
    except PlaylistUnsupported as exc:
        state['add_note'] = str(exc)
    finally:
        try:
            _dismiss(pid, opened)
        except TrackFailed as exc:
            state.update(can_add=False, add_note=str(exc))
    return state


def _matching_members(tracks, target):
    return [track for track in tracks if exact_track(track['title'], track['artist'], *target)]


def _audition_duration(hwnd, pid, target):
    from KugouControl.Uia import invalidate, read_controls

    invalidate()
    state = read_controls(hwnd)
    if state['status'] != 'playing' or not exact_track(*_current(pid), *target):
        raise TrackFailed('当前播放歌曲与试听目标不一致，未确认加歌')
    return state.get('duration')


def _unverified(message):
    return {'status': 'unverified', 'message': message, 'in_playlist': None}


def add_to_playlist(hwnd, pid, name, title, artist):
    from KugouControl.Track import _play_search

    deadline = time.monotonic() + PLAYLIST_ADD_SOFT_TIMEOUT
    verify_by = deadline - 4
    commit_by = verify_by - 7
    # 搜索已有 24 秒上限；允许正常探测先完成，若试听耗完了提交预算就只做清理。
    audition_by = verify_by - 24
    target = (title, artist)
    # 加歌前后两次读歌单只需要按完整名打开它；真正决定加到哪里的是「添加到」对话框，
    # 那一步（_destination）仍然读完整个列表确认目标歌单唯一。
    state = inspect(hwnd, name, deadline=audition_by, exact_only=True, unique=False)
    if not state['supported']:
        raise PlaylistUnsupported(state['note'])
    if state['name'] != name:
        return _unverified('无法确认原来设置的完整歌单名，未执行加歌；请刷新歌单后再试')
    matches = _matching_members(state['tracks'], target)
    if not state['complete'] or len(matches) > 1:
        return _unverified('无法确认歌单内是否已有唯一对应的歌曲，未执行加歌')
    if matches:
        return {'status': 'already_present', 'message': '这首歌已经在演出歌单内', 'in_playlist': True}
    if time.monotonic() >= audition_by:
        return _unverified('没有足够时间试听及核验加歌，未执行加歌')
    known = set(_process_windows(pid))
    opened = {}
    commit_attempted = False
    result = None

    def mark_committed():
        nonlocal commit_attempted
        commit_attempted = True

    try:
        if exact_track(*_current(pid), *target):
            _pause(hwnd, audition_by)
        if time.monotonic() >= audition_by:
            raise TrackFailed('没有足够时间试听及核验加歌，未执行加歌')
        _play_search(hwnd, pid, *target)
        if time.monotonic() >= commit_by:
            raise TrackFailed('试听完成时已没有足够时间确认和核验加歌，未执行加歌')
        duration = _audition_duration(hwnd, pid, target)

        def check_source():
            current_duration = _audition_duration(hwnd, pid, target)
            if duration is not None and current_duration != duration:
                raise TrackFailed('当前播放版本与试听版本不一致，未确认加歌')

        dialog_by = min(commit_by, time.monotonic() + PLAYLIST_LAYOUT['add_wait'])
        destination = _destination(hwnd, pid, name, dialog_by, known, opened, check_source=check_source)
        _confirm(destination, dialog_by, check_source=check_source, mark_committed=mark_committed)
        after = inspect(hwnd, name, deadline=verify_by, exact_only=True, unique=False)
        added = _matching_members(after['tracks'], target)
        if (not after['supported'] or not after['complete'] or after['name'] != name
                or len(after['tracks']) != len(state['tracks']) + 1 or len(added) != 1
                or (duration is not None and added[0].get('duration') is not None
                    and abs(added[0]['duration'] - duration) >= 1)
                or time.monotonic() >= verify_by):
            raise TrackFailed('无法核验目标歌曲已加入指定歌单，请检查歌单；不会自动重试')
        result = {'status': 'added', 'message': '已加入演出歌单并核验', 'in_playlist': True}
    except TrackFailed as exc:
        result = _unverified(str(exc))
    except Exception:
        if not commit_attempted:
            raise
        result = _unverified('加歌确认可能已发送，无法核验结果，请检查歌单；不会自动重试')
    finally:
        cleanup = []
        try:
            _dismiss(pid, opened, deadline=deadline - 2)
        except Exception:
            cleanup.append('无法核验加歌弹窗已关闭')
        try:
            _pause(hwnd, deadline)
        except Exception:
            cleanup.append('无法核验试听已暂停，请在酷狗中检查并手动暂停')
        if cleanup and result is not None:
            result = _unverified('；'.join([result['message'], *cleanup]))
    if commit_attempted and result['status'] == 'unverified':
        result['retry_requires_refresh'] = True
    return result
