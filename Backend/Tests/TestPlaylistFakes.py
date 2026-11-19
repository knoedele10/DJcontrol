"""歌单测试共用的控件、滚动列表和酷狗页面替身。"""
from __future__ import annotations

from contextlib import ExitStack
import time
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import win32gui

from KugouControl import Uia
from KugouControl.Playlist import Add, Navigation, Page, Playback, Scrolling, Ui


class UnexpectedDesktopAccess(BaseException):
    """A missing test double must not be caught as a normal UIA failure."""


class IsolatedPlaylistTestCase(TestCase):
    def setUp(self):
        super().setUp()
        for module, names in (
            (Navigation, '_root'), (Page, '_root'), (Ui, '_get_pattern'),
            (Playback, '_root _current'), (Add, '_root _current'), (Uia, 'read_controls'),
            (win32gui, 'PostMessage ScreenToClient EnumWindows GetWindowDC GetWindowText IsWindow IsWindowVisible'),
        ):
            for name in names.split():
                self.enterContext(patch.object(module, name, side_effect=UnexpectedDesktopAccess(
                    f'歌单测试缺少替身：{module.__name__}.{name}')))


ZERO = SimpleNamespace(left=0, top=0, right=0, bottom=0)


class Element:
    def __init__(self, kind, name='', children=(), left=300, top=100, width=150, height=35, visible=True):
        self.control_type, self.name = kind, name
        self._children = list(children)
        self.parent = None
        self.visible = visible
        self.rectangle = SimpleNamespace(left=left, top=top, right=left + width, bottom=top + height) if visible else ZERO
        for child in self._children:
            child.parent = self

    def children(self):
        return self._children


def row(title, artist):
    return Element('DataItem', children=[Element('Text', title), Element('Text', artist)])


def page(rows, extra=()):
    header = Element('Header', children=[Element('HeaderItem', '歌曲'), Element('HeaderItem', '歌手')])
    for index, item in enumerate(rows):
        item.rectangle = SimpleNamespace(left=300, top=150 + 40 * index, right=450, bottom=185 + 40 * index)
    grid = Element('DataGrid', children=[header, *rows], top=100, height=900)
    return Element('Custom', '演出歌单', [grid, *extra]), grid


def kugou_row(title, artist):
    return f'<a {title}>{title}</a>，歌手:{artist}，专辑:某专辑，时长:03:00'


class VirtualList(Element):
    """酷狗 10.2.52 的虚拟列表替身：只有视口上下一行以内的项有名字和矩形，滚轮移动内容。"""

    def __init__(self, name, names, *, left, top, width, height, row):
        super().__init__('List', name, left=left, top=top, width=width, height=height)
        self.names, self.row, self.offset = list(names), row, 0
        self._children = [Element('ListItem') for _ in self.names]
        for item in self._children:
            item.parent = self
        self.layout()

    def layout(self):
        view = self.rectangle
        top = view.top - self.offset
        for item, name in zip(self._children, self.names):
            if name is None:
                # 始终隐藏、不占位置的槽位，例如「添加到」对话框顶部读不到名字的分组标题。
                item.name, item.visible, item.rectangle = '', False, ZERO
                continue
            realized = view.top - self.row <= top < view.bottom + self.row
            item.name, item.visible = (name if realized else ''), realized
            item.rectangle = (SimpleNamespace(left=view.left, top=top, right=view.right, bottom=top + self.row)
                              if realized else ZERO)
            top += self.row

    def scroll(self, pixels):
        shown = sum(name is not None for name in self.names)
        limit = max(0, shown * self.row - (self.rectangle.bottom - self.rectangle.top))
        self.offset = min(max(self.offset + pixels, 0), limit)
        self.layout()

    def at(self, x, y):
        view = self.rectangle
        return view.left <= x <= view.right and view.top <= y <= view.bottom


class FakeKugou:
    """酷狗界面替身：顶部页签、搜索页、音乐页（左侧导航 + 歌单页）和播放栏，滚轮和点击按坐标生效。

    侧栏和歌曲列表的下沿 8 像素被播放栏压住：点到那里算点到播放栏，不会打开歌单或播放。
    歌曲行中间的歌手名是链接（行宽 45%–55% 处）：双击到那里会跳到歌手页而不是播放。
    """

    NOTCH, PLAY_BAR = 70, 8

    def __init__(self, playlists, *, on_music=True, nav_offset=0, song_rows=5):
        self.playlists = dict(playlists)
        self.on_music, self.opened, self.song_rows = on_music, None, song_rows
        self.clicks, self.wheels, self.play_bar_hits, self.now = [], [], 0, ('旧歌', '旧歌手')
        self.artist_hits = 0
        names = ['我的收藏', '本地与下载', '默认列表', '自建歌单', *self.playlists]
        self.nav = VirtualList('导航', names, left=0, top=100, width=200, height=300, row=50)
        self.nav.scroll(nav_offset)
        self.songs = None
        self.tab = Element('TabItem', '音乐', left=300, top=10, width=60, height=30)
        self.rebuild()

    def rebuild(self):
        children = [Element('Custom', children=[self.tab, Element('Edit', '搜索', left=500, top=10, width=200, height=30)],
                            left=0, top=0, width=1000, height=60)]
        if self.on_music:
            children.append(Element('Pane', '导航', [self.nav], left=0, top=100, width=200, height=300))
            if self.opened:
                children.append(self.page())
        else:
            children.append(Element('Custom', '内嵌页', [Element('Document', 'PC搜索-酷狗音乐')],
                                    left=0, top=100, width=1000, height=500))
        self.root = Element('Window', '酷狗音乐', children, left=0, top=0, width=1000, height=700)

    def page(self):
        name, tracks = self.opened, self.playlists[self.opened]
        title = Element('Text', name, left=320, top=110, width=300, height=30)
        hidden = Element('Custom', children=[Element('Text', name, visible=False),
                                             Element('Text', f'共 {len(tracks)} 首歌曲', visible=False)], visible=False)
        copy = Element('Pane', '单曲', [Element('List', '单曲', visible=False)], visible=False)
        body = Element('Pane', '单曲', [self.songs], left=300, top=200, width=600, height=40 * self.song_rows)
        extra = [] if tracks else [Element('Text', '这里没内容显示~', left=500, top=260, width=200, height=30)]
        return Element('Custom', children=[Element('Custom', children=[title], left=310, top=105, width=500, height=60),
                                           hidden, copy, body, *extra], left=300, top=100, width=600, height=500)

    def open(self, name):
        tracks = self.playlists[name]
        self.opened = name
        self.songs = VirtualList('单曲', [kugou_row(*track) for track in tracks],
                                 left=300, top=200, width=600, height=40 * self.song_rows, row=40)
        self.rebuild()

    # Input 替身
    def wheel(self, hwnd, x, y, notches):
        self.wheels.append(notches)
        for target in (self.nav if self.on_music else None, self.songs if self.opened else None):
            if target is not None and target.at(x, y):
                target.scroll(notches * self.NOTCH)

    def click(self, hwnd, x, y, *, double=False):
        self.clicks.append((round(x), round(y), double))
        tab = self.tab.rectangle
        if tab.left <= x <= tab.right and tab.top <= y <= tab.bottom:
            self.on_music = True
            self.rebuild()
            return
        for target in (self.nav if self.on_music else None, self.songs if self.opened else None):
            if target is None or not target.at(x, y):
                continue
            if y > target.rectangle.bottom - self.PLAY_BAR:
                self.play_bar_hits += 1
                return
            hit = [item for item in target.children() if item.name and item.rectangle.top <= y < item.rectangle.bottom]
            if target is self.nav and hit and hit[0].name in self.playlists:
                self.open(hit[0].name)
            elif target is self.songs and hit and double:
                rect = hit[0].rectangle
                if rect.left + 0.45 * (rect.right - rect.left) <= x <= rect.left + 0.55 * (rect.right - rect.left):
                    self.artist_hits += 1  # 双击到歌手链接：跳到歌手页，不播放
                    return
                self.now = Page._labelled_row(hit[0].name)['title'], Page._labelled_row(hit[0].name)['artist']

    def press(self, *args, **kwargs):
        pass

    def type_text(self, *args, **kwargs):
        pass

    def patches(self):
        return (
            patch.object(Navigation, '_root', lambda hwnd: self.root),
            patch.object(Page, '_root', lambda hwnd: self.root),
            patch.object(Playback, '_root', lambda hwnd: self.root),
            patch.object(Ui, 'Input', self),
            patch.object(Scrolling, 'Input', self),
            patch.object(Page, 'Input', self),
            patch.object(time, 'sleep'),
            patch.object(Page, '_pattern', return_value=None),
        )

    def run(self, call):
        with ExitStack() as stack:
            for item in self.patches():
                stack.enter_context(item)
            return call()


SONGS = [('晴天', '周杰伦'), ('Memories', 'ＴＲＡ＄Ｈ'), ('凉凉', '张碧晨、杨宗纬')]


def show(**kwargs):
    playlists = {f'歌单{i}': [('歌', '人')] for i in range(10)}
    playlists.update({'总结环节': SONGS, '总结环节Lucy老师': [('别的歌', '别人')], '游戏环节Lucy老师': [('游戏', '人')]})
    return FakeKugou(playlists, **kwargs)


class FakePlaybackKugou(FakeKugou):
    def rebuild(self):
        super().rebuild()
        bottom = (self.songs if self.songs is not None else self.nav).rectangle.bottom
        top = bottom - self.PLAY_BAR
        slider = Element('Slider', '进度', left=0, top=top, width=1000, height=5)
        bar = Element('Custom', children=[slider], left=0, top=top, width=1000, height=50)
        bar.parent = self.root
        self.root._children.append(bar)


def _without_count(content):
    for child in content.children():
        child._children = [c for c in child.children() if not c.name.startswith('共')]
    return content
