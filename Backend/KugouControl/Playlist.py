"""歌单操作：仅使用能回读的页面和歌曲身份；没有证据时不猜坐标或报告成功。

所有对象仅在 Worker 的 COM 线程使用，父进程只接收可序列化的快照。
"""
from __future__ import annotations

import time

import win32con

from KugouControl import Input
from KugouControl.Profiles import PLAYLIST_LAYOUT, exact_track
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


def _page(hwnd, name, entry):
    root = _root(hwnd)
    pages = [e for e in _walk(root) if e.control_type in ("Pane", "Custom", "Group", "Tab")
             and e.name == name and _visible(e)]
    if len(pages) == 1:
        return pages[0]
    # 标题必须位于侧栏右边，避免把侧栏或播放队列当成歌单正文。
    headers = [e for e in _walk(root) if e.control_type == "Text" and e.name == name
               and _visible(e) and e.rectangle.left >= entry.rectangle.right]
    if len(headers) == 1:
        current = headers[0].parent
        for _ in range(3):
            if current is None or current.rectangle.left < entry.rectangle.right:
                break
            if any(e.control_type in ("DataGrid", "Table", "List", "Edit") for e in _walk(current, 4)):
                return current
            current = current.parent
    raise PlaylistUnsupported("无法回读歌单正文，不能把侧栏选中状态当成页面已就绪")


def open_playlist(hwnd: int, name: str, deadline: float | None = None):
    if not name:
        raise PlaylistUnsupported("尚未配置演出歌单")
    deadline = deadline or time.monotonic() + PLAYLIST_LAYOUT["wait"]
    root = _root(hwnd)
    entry = _unique((e for e in _walk(root) if e.control_type in ("TreeItem", "ListItem", "Button")
                     and e.name == name and _visible(e)), f"找不到唯一的歌单「{name}」，请展开自建歌单后重新检测")
    try:
        return _page(hwnd, name, entry)
    except PlaylistUnsupported:
        _click(hwnd, entry)
    while time.monotonic() < deadline:
        try:
            return _page(hwnd, name, entry)
        except PlaylistUnsupported:
            time.sleep(0.15)
    raise PlaylistUnsupported(f"歌单「{name}」页面无法可靠读取")


def _collection(page):
    return _unique((e for e in _walk(page) if e.control_type in ("DataGrid", "Table", "List")
                    and _visible(e)), "歌单没有唯一可识别的歌曲列表")


def _headers(collection):
    return [e.name.strip() for e in _walk(collection, 3) if e.control_type == "HeaderItem"]


def _row_track(row, headers):
    cells = [e for e in row.children() if e.control_type in ("Text", "DataItem", "Custom")]
    # 只根据可读列标题确定列含义，不猜第一列一定是歌名。
    title_indices = [i for i, name in enumerate(headers) if name in PLAYLIST_LAYOUT["title_headers"]]
    artist_indices = [i for i, name in enumerate(headers) if name in PLAYLIST_LAYOUT["artist_headers"]]
    if len(title_indices) == len(artist_indices) == 1 and len(cells) == len(headers):
        title, artist = cells[title_indices[0]].name.strip(), cells[artist_indices[0]].name.strip()
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
    return any(e.control_type == "Text" and e.name.strip() in PLAYLIST_LAYOUT["empty_names"]
               and _visible(e) for e in _walk(page))


def _rows(collection):
    return [e for e in collection.children() if e.control_type in ("DataItem", "ListItem") and _visible(e)]


def _scan(page, deadline, target=None):
    collection = _collection(page)
    headers = _headers(collection)
    scroll = _pattern(collection, "Scroll")
    if scroll and scroll.CurrentVerticallyScrollable:
        scroll.SetScrollPercent(-1, 0)
        time.sleep(0.1)
        if scroll.CurrentVerticalScrollPercent > 0.5:
            raise PlaylistUnsupported("歌单列表没有响应滚动，无法确认成员")
    seen, complete, chosen = {}, False, None
    for _ in range(40):
        rows = _rows(collection)
        parsed = [(row, _row_track(row, headers)) for row in rows]
        for row, track in parsed:
            if track:
                seen[(track['title'], track['artist'])] = track
                if target and exact_track(track['title'], track['artist'], *target):
                    chosen = row
        if chosen:
            # 同一窗口内发现多个同身份版本也不盲选。
            matches = [row for row, track in parsed if track and exact_track(track['title'], track['artist'], *target)]
            if len(matches) != 1:
                raise TrackFailed("歌单内有多个同名版本，请在酷狗中只保留目标版本")
            return list(seen.values()), False, chosen
        at_end = not scroll or not scroll.CurrentVerticallyScrollable or scroll.CurrentVerticalScrollPercent >= 99.5
        if at_end:
            # 没有 ScrollPattern 但存在滚动条时，不把当前可见部分当成全集。
            unknown_scroll = not scroll and any(e.control_type == "ScrollBar" for e in _walk(collection, 2))
            complete = not unknown_scroll and bool(rows or _empty(page)) and all(track for _, track in parsed)
            if not rows and _empty(page):
                complete = True
            break
        if time.monotonic() >= deadline:
            break
        before = scroll.CurrentVerticalScrollPercent
        scroll.SetScrollPercent(-1, min(100, before + 20))
        time.sleep(0.1)
        if scroll.CurrentVerticalScrollPercent <= before:
            break
    return list(seen.values()), complete, None


def _filter(page):
    return _unique((e for e in _walk(page) if e.control_type == "Edit" and _visible(e)
                    and e.name in PLAYLIST_LAYOUT["filter_names"]), "没有可回读的歌单内搜索框")


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


def inspect(hwnd, name):
    deadline = time.monotonic() + PLAYLIST_LAYOUT['wait']
    state = {"name": name, "route": None, "supported": False, "can_add": False,
             "complete": False, "tracks": [], "note": "", "add_note": "尚未检测加歌菜单"}
    try:
        page = open_playlist(hwnd, name, deadline)
        try:
            _set_filter(hwnd, page, '', deadline)
        except PlaylistUnsupported:
            pass
        try:
            tracks, complete, _ = _scan(page, deadline)
        except PlaylistUnsupported:
            tracks, complete = [], False
        if tracks or complete:
            state.update(route='A', supported=True, tracks=tracks, complete=complete,
                         note='通过歌曲列定位' + ('；列表已完整读取' if complete else '；仅确认已读成员，未读部分保持未知'))
        else:
            _filter(page)
            first = PLAYLIST_LAYOUT['first_song']
            if first is None:
                raise PlaylistUnsupported('歌曲行不可读；歌单内搜索已发现，但第一行位置尚未真机验证')
            if not _pattern(_filter(page), 'Value'):
                raise PlaylistUnsupported('歌单内搜索无法回读')
            state.update(route='B', supported=True, note='歌单内筛选，播放后核验')
    except PlaylistUnsupported as exc:
        state['note'] = str(exc)
    return state


def _pause(hwnd):
    from KugouControl.Uia import invalidate, read_controls
    invalidate()
    state = read_controls(hwnd)
    if state['status'] == 'playing':
        button = _unique((e for e in _walk(_root(hwnd), 4) if e.control_type == 'Button'
                          and e.name == '暂停' and _visible(e)), '无法唯一定位酷狗暂停按钮')
        _click(hwnd, button)
        end = time.monotonic() + 1.5
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
    page = open_playlist(hwnd, name, deadline)
    try:
        _set_filter(hwnd, page, '', deadline)
    except PlaylistUnsupported:
        pass
    try:
        tracks, complete, row = _scan(page, deadline, (title, artist))
    except PlaylistUnsupported:
        tracks, complete, row = [], False, None
    if row:
        if time.monotonic() >= deadline:
            raise PlaylistUnsupported('歌单定位超过等待上限，保留搜索播放')
        # 旧标题与目标相同时，先暂停再观察由本次双击触发的播放状态。
        if exact_track(*_current(pid), title, artist):
            _pause(hwnd)
        _click(hwnd, row, double=True)
    elif complete:
        raise PlaylistMiss('歌曲不在演出歌单内')
    else:
        try:
            _filter(page)
        except PlaylistUnsupported:
            raise PlaylistUnsupported('歌单成员未完整读取，保留搜索播放')
        if PLAYLIST_LAYOUT['first_song'] is None:
            raise PlaylistUnsupported('歌单第一行位置尚未真机验证，保留搜索播放')
        _set_filter(hwnd, page, f'{title} {artist}'.strip(), deadline)
        if _empty(page):
            raise PlaylistMiss('歌单筛选没有找到这首歌')
        # B 路线必须先暂停，避免空结果时沿用旧标题冒认成功。
        _pause(hwnd)
        x, y = PLAYLIST_LAYOUT['first_song']
        scale = (_filter(page).rectangle.bottom - _filter(page).rectangle.top) / PLAYLIST_LAYOUT['search_box_height']
        Input.click(hwnd, page.rectangle.left + x * scale, page.rectangle.top + y * scale, double=True)
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


def _menu_roots(hwnd, pid):
    from pywinauto import Desktop
    roots = [_root(hwnd)]
    for window in Desktop(backend='uia').windows(process=pid, visible_only=True):
        if window.handle != hwnd:
            roots.append(window.element_info)
    return roots


def _menu_item(hwnd, pid, names):
    return _unique((e for root in _menu_roots(hwnd, pid) for e in _walk(root, 6)
                    if e.control_type == 'MenuItem' and e.name.strip() in names and _visible(e)),
                   '无法唯一识别加歌菜单项')


def _invoke(element, *, expand=False):
    pattern = _pattern(element, 'ExpandCollapse' if expand else 'Invoke')
    if not pattern:
        raise PlaylistUnsupported('加歌菜单不支持可靠的语义操作')
    pattern.Expand() if expand else pattern.Invoke()
    time.sleep(0.15)


def _destination(hwnd, pid, name):
    # 入口限定在带进度条的播放栏，不使用搜索结果第一行的任意右键菜单。
    root = _root(hwnd)
    bars = [e for e in _walk(root, 3) if e.control_type == 'Custom'
            and any(c.control_type == 'Slider' and c.name == '进度' for c in e.children())]
    bar = _unique(bars, '无法定位播放栏的加歌入口')
    more = _unique((e for e in _walk(bar, 3) if e.control_type == 'Button'
                   and e.name in ('更多', '更多操作', '更多功能') and _visible(e)), '播放栏没有可识别的更多菜单')
    _click(hwnd, more)
    item = _menu_item(hwnd, pid, ('添加到', '添加到歌单', '添加到播放列表'))
    _invoke(item, expand=True)
    return _menu_item(hwnd, pid, (name,))


def inspect_add(hwnd, pid, state):
    if not state['supported']:
        state['add_note'] = '无法核验加入后的歌单成员；请手动维护歌单'
        return state
    try:
        item = _destination(hwnd, pid, state['name'])
        if not _pattern(item, 'Invoke'):
            raise PlaylistUnsupported('目标歌单菜单不支持语义操作')
        state.update(can_add=True, add_note='演出前逐首试听核验，再加入指定歌单；完成后暂停')
    except PlaylistUnsupported as exc:
        state['add_note'] = str(exc)
    finally:
        Input.press(hwnd, win32con.VK_ESCAPE, 2)
    return state


def add_to_playlist(hwnd, pid, name, title, artist):
    from KugouControl.Track import _play_search
    state = inspect_add(hwnd, pid, inspect(hwnd, name))
    if not state['can_add']:
        raise PlaylistUnsupported(state['add_note'])
    if any(exact_track(t['title'], t['artist'], title, artist) for t in state['tracks']):
        return {'status': 'already_present', 'message': '这首歌已经在演出歌单内', 'in_playlist': True}
    try:
        # B 或不完整列表不能证明不存在，先由歌单尝试核验，避免重复加入。
        if not state['complete']:
            try:
                play_from_playlist(hwnd, pid, name, title, artist)
                return {'status': 'already_present', 'message': '已从歌单核验，这首歌已经存在', 'in_playlist': True}
            except PlaylistMiss:
                pass
        _play_search(hwnd, pid, title, artist)
        if not exact_track(*_current(pid), title, artist):
            raise TrackFailed('试听版本与完整歌名、歌手不一致，未执行加歌')
        _invoke(_destination(hwnd, pid, name))
        # 从歌单重新定位/筛选并播放，不能沿用试听留下的标题来证明已加入。
        play_from_playlist(hwnd, pid, name, title, artist)
        return {'status': 'added', 'message': '已加入演出歌单并核验', 'in_playlist': True}
    except (TrackFailed, PlaylistUnsupported) as exc:
        return {'status': 'unverified', 'message': str(exc), 'in_playlist': None}
    finally:
        Input.press(hwnd, win32con.VK_ESCAPE, 2)
        _pause(hwnd)
