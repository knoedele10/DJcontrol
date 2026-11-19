"""查找 UIA 控件、计算播放栏遮挡，以及安全点击的共用辅助。"""
from __future__ import annotations

from KugouControl import Input
from KugouControl.Profiles import PLAYLIST_LAYOUT
from KugouControl.Track import TrackFailed, _pattern as _get_pattern

from .Errors import PlaylistUnsupported


def _pattern(element, name):
    try:
        return _get_pattern(element, name)
    except Exception:
        # UIA_E_NOTSUPPORTED 是可选 pattern 缺失，不把它当成已经支持。
        return None


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
