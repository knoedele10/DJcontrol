"""检测加歌入口、核验选中目标、提交加歌并确认结果。"""
from __future__ import annotations

import time

import win32con

from KugouControl import Input
from KugouControl.Profiles import PLAYLIST_ADD_SOFT_TIMEOUT, PLAYLIST_LAYOUT, exact_track
from KugouControl.Track import TrackFailed, _current, _root

from .Errors import PlaylistUnsupported
from .Navigation import _find_entry, _nav_items
from .Page import _matching_members, inspect
from .Playback import _pause
from .Ui import _click, _click_clear, _clickable, _find, _pattern, _playbar, _unique, _visible, _walk


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
