"""歌单点播、播放结果核验与暂停。"""
from __future__ import annotations

import time

from KugouControl.Profiles import PLAYLIST_LAYOUT, exact_track
from KugouControl.Track import TrackFailed, TrackLoading, _current, _root

from .Errors import PlaylistMiss, PlaylistUnsupported
from .Navigation import _nav
from .Page import (
    _collection, _current_page, _headers, _matching_members, _page, _row_track,
    _scan, _set_filter, _target_row, open_playlist,
)
from .Ui import _click, _click_clear, _clickable, _find, _list_bottom, _playbar, _row_blank_x, _unique, _visible


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
