"""确认歌单页面、解析歌曲行和筛选状态，并扫描歌单成员。"""
from __future__ import annotations

import re
import time

import win32con

from KugouControl import Input
from KugouControl.Profiles import PLAYLIST_LAYOUT, exact_track
from KugouControl.Track import TrackFailed, _root

from .Errors import PlaylistUnsupported
from .Navigation import _ensure_nav, _find_entry, _nav
from .Scrolling import _PatternScroll, _WheelScroll
from .Ui import _clear_span, _click, _click_clear, _clickable, _find, _list_bottom, _pattern, _unique, _visible, _walk


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


def _matching_members(tracks, target):
    return [track for track in tracks if exact_track(track['title'], track['artist'], *target)]
