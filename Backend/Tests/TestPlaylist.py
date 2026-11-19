"""歌单状态、回退边界与准备试听隔离；所有桌面依赖均使用替身。"""
from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from Database import Database, PlaylistRepository, QueueRepository, SessionRepository, SettingsRepository, SongRepository
from KugouControl import Playlist, Track, Worker
from KugouControl.Adapter import KugouController
from KugouControl.Profiles import PLAYLIST_ADD_TIMEOUT, PLAYLIST_LAYOUT, exact_track
from Main import create_app
from Player.Base import CapabilityUnsupported, ControllerTimeout, ControllerTrackLoading, PlayerReading, PlayerUnavailable
from Player.Mock import MockPlayerController
from Player.Model import PlayerCommand
from Player.Service import PLAYLIST_KEY, PlayerConflict, PlayerDisconnected, PlayerService
from PptControl.Service import PptService
from Tests.TestDiagnostics import FakePptController

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
                self.now = Playlist._labelled_row(hit[0].name)['title'], Playlist._labelled_row(hit[0].name)['artist']

    def press(self, *args, **kwargs):
        pass

    def type_text(self, *args, **kwargs):
        pass

    def patches(self):
        return (patch.object(Playlist, '_root', lambda hwnd: self.root), patch.object(Playlist, 'Input', self),
                patch.object(Playlist.time, 'sleep'), patch.object(Playlist, '_pattern', return_value=None))

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


class PlaylistIdentityTests(unittest.TestCase):
    def test_exact_identity_preserves_versions_and_all_artists(self):
        self.assertTrue(exact_track('晴 天', '周杰伦', '晴天', '周杰伦'))
        self.assertTrue(exact_track('凉凉', '甲、乙', '凉凉', '乙/甲'))
        self.assertFalse(exact_track('晴天 (Live)', '周杰伦', '晴天', '周杰伦'))
        self.assertFalse(exact_track('晴天', '翻唱者', '晴天', '周杰伦'))
        self.assertFalse(exact_track('凉凉', '甲', '凉凉', '甲/乙'))
        # 酷狗里的全角字母和曲库里的半角写法是同一位歌手。
        self.assertTrue(exact_track('Memories', 'ＴＲＡ＄Ｈ', 'Memories', 'TRA$H'))

    def test_exact_identity_preserves_punctuation_and_normalizes_fullwidth_artist_separator(self):
        self.assertFalse(exact_track('C++', 'A-B', 'C', 'A-B'))
        self.assertFalse(exact_track('C++', 'A-B', 'C++', 'AB'))
        self.assertTrue(exact_track('Ｃ＋＋', '甲／乙', 'C++', '乙、甲'))

    def test_kugou_row_names_are_parsed_and_leftover_rows_are_unknown(self):
        self.assertEqual(Playlist._labelled_row('<a Memories>Memories</a>，歌手:ＴＲＡ＄Ｈ，专辑:Memories，时长:02:33'),
                         {'title': 'Memories', 'artist': 'ＴＲＡ＄Ｈ', 'album': 'Memories', 'duration': 153})
        self.assertEqual(Playlist._labelled_row('<a 明天，你好>明天，你好</a>，歌手:牛奶咖啡，专辑:Lost & Found去寻找，时长:04:31'),
                         {'title': '明天，你好', 'artist': '牛奶咖啡', 'album': 'Lost & Found去寻找', 'duration': 271})
        self.assertEqual(Playlist._labelled_row('<a a>b>a>b</a>，歌手:甲、乙，时长:01:00'),
                         {'title': 'a>b', 'artist': '甲、乙', 'duration': 60})
        # 列表末尾残留的旧行只有链接文字，没有歌手：不能当成一首歌。
        self.assertIsNone(Playlist._labelled_row('<a Memories>Memories</a>'))
        self.assertIsNone(Playlist._labelled_row('歌手 - 歌曲'))

    def test_labelled_rows_reject_partial_or_ambiguous_fields_without_shortening_artist(self):
        for label in ('<a 歌曲>歌曲</a>，歌手:歌手', '<a 旧歌>歌曲</a>，歌手:歌手，时长:03:00',
                      '<a 歌曲>歌曲</a>，歌手:甲，专辑:乙，专辑:某专辑，时长:03:00'):
            with self.subTest(label=label):
                self.assertIsNone(Playlist._labelled_row(label))
        track = Playlist._labelled_row('<a 歌曲>歌曲</a>，歌手:甲，时长:乙，专辑:某专辑，时长:03:00')
        self.assertEqual(track['artist'], '甲，时长:乙')

    def test_scan_does_not_infer_identity_from_an_unlabelled_row(self):
        target, _ = page([Element('DataItem', '歌手 - 歌曲')])
        with patch.object(Playlist, '_pattern', return_value=None), patch.object(Playlist, 'Input'), \
             patch.object(Playlist.time, 'sleep'), patch.dict(PLAYLIST_LAYOUT, load_wait=0):
            tracks, complete, _ = Playlist._scan(1, target, float('inf'))
        self.assertEqual(tracks, [])
        self.assertFalse(complete)

    def test_scan_virtual_list_reads_the_last_song_and_checks_scroll(self):
        names = [kugou_row(f'歌曲{i}', '歌手') for i in range(120)] + [kugou_row('末尾歌曲', '歌手')]
        target, scroll = self._pattern_page(names)
        with patch.object(Playlist, '_pattern', return_value=scroll), patch.object(Playlist.time, 'sleep'):
            tracks, complete, _ = Playlist._scan(1, target, float('inf'))
        self.assertTrue(complete)
        self.assertEqual(len(tracks), len(names))
        self.assertIn(('末尾歌曲', '歌手'), [(track['title'], track['artist']) for track in tracks])

    def _pattern_page(self, names, *, can_scroll=True):
        height, row_height = 160, 40
        songs = VirtualList('单曲', names, left=300, top=100, width=150, height=height, row=row_height)
        length = len(names) * row_height
        scroll = SimpleNamespace(CurrentVerticallyScrollable=True, CurrentVerticalScrollPercent=0,
                                 CurrentVerticalViewSize=100 * height / length)

        def set_percent(horizontal, value):
            if can_scroll:
                scroll.CurrentVerticalScrollPercent = value
                songs.scroll((length - height) * value / 100 - songs.offset)

        scroll.SetScrollPercent = set_percent
        return Element('Custom', '歌单', [songs]), scroll

    def test_pattern_stopping_before_the_end_keeps_absent_members_unknown(self):
        target, scroll = self._pattern_page([kugou_row(f'歌曲{i}', '歌手') for i in range(10)], can_scroll=False)
        with patch.object(Playlist, '_pattern', return_value=scroll), patch.object(Playlist.time, 'sleep'):
            tracks, complete, _ = Playlist._scan(1, target, float('inf'), ('歌曲9', '歌手'))
        self.assertEqual(len(tracks), 4)
        self.assertFalse(complete)

    def test_unreadable_row_on_an_earlier_viewport_keeps_members_unknown(self):
        target, scroll = self._pattern_page(['不可识别'] + [kugou_row(f'歌曲{i}', '歌手') for i in range(10)])
        with patch.object(Playlist, '_pattern', return_value=scroll), patch.object(Playlist.time, 'sleep'):
            tracks, complete, _ = Playlist._scan(1, target, float('inf'), ('不存在', '歌手'))
        self.assertEqual(scroll.CurrentVerticalScrollPercent, 100)
        self.assertIn(('歌曲9', '歌手'), [(track['title'], track['artist']) for track in tracks])
        self.assertFalse(complete)

    def test_positive_count_with_empty_indicator_does_not_prove_absence(self):
        target, _ = page([], [Element('Custom', children=[Element('Text', '演出歌单', visible=False),
                                                            Element('Text', '共 1 首歌曲', visible=False)]),
                              Element('Text', '没有搜索结果')])
        with patch.object(Playlist, '_pattern', return_value=None), patch.object(Playlist, 'Input'), \
             patch.object(Playlist.time, 'sleep'), patch.dict(PLAYLIST_LAYOUT, load_wait=0):
            tracks, complete, _ = Playlist._scan(1, target, float('inf'), name='演出歌单')
        self.assertEqual(tracks, [])
        self.assertFalse(complete)

    def test_active_filter_is_not_an_unfiltered_member_snapshot(self):
        filtered, _ = page([row('一首歌', '歌手')], [Element('Edit', '歌单内搜索')])
        with patch.object(Playlist, '_pattern', return_value=SimpleNamespace(CurrentValue='旧关键字')):
            self.assertEqual(Playlist._scan(1, filtered, float('inf')), ([], False, None))

    def test_replaced_collection_cannot_publish_stale_members(self):
        before, _ = page([row('旧歌', '歌手')])
        after, _ = page([row('新歌', '歌手')])
        with patch.object(Playlist, '_pattern', return_value=None), patch.object(Playlist, 'Input'), \
             patch.object(Playlist.time, 'sleep'):
            current_page = iter((before, after)).__next__
            self.assertEqual(Playlist._scan(1, before, float('inf'), verify_page=current_page), ([], False, None))

    def test_scroll_failure_keeps_absent_members_unknown(self):
        target, _ = page([row('一首歌', '歌手')])
        scroll = SimpleNamespace(CurrentVerticallyScrollable=True, CurrentVerticalScrollPercent=50, SetScrollPercent=lambda *args: None)
        with patch.object(Playlist, '_pattern', return_value=scroll), patch.object(Playlist.time, 'sleep'):
            with self.assertRaises(Playlist.PlaylistUnsupported):
                Playlist._scan(1, target, float('inf'))

    def test_wheel_that_does_not_move_is_not_proof_of_the_end(self):
        # 没有 ScrollPattern 只能滚轮；滚不动也可能是消息没送达，没有「共 N 首」就不认读全。
        target, grid = page([row('一首歌', '歌手')])
        grid._children.append(Element('ScrollBar'))
        with patch.object(Playlist, '_pattern', return_value=None), patch.object(Playlist, 'Input'), \
             patch.object(Playlist.time, 'sleep'):
            tracks, complete, _ = Playlist._scan(1, target, float('inf'))
        self.assertEqual(len(tracks), 1)
        self.assertFalse(complete)

    def test_probe_never_enables_unmeasured_filter_coordinates(self):
        target = Element('Custom', '演出歌单', [Element('Edit', '歌单内搜索')])
        with patch.object(Playlist, 'open_playlist', return_value=(target, '演出歌单')), patch.object(Playlist, '_set_filter'), \
             patch.object(Playlist, '_current_page', return_value=target), \
             patch.dict(PLAYLIST_LAYOUT, first_song=None):
            state = Playlist.inspect(1, '演出歌单')
        self.assertFalse(state['supported'])
        self.assertIn('尚未真机验证', state['note'])


class PlaylistNavigationTests(unittest.TestCase):
    """按 2026-11-18 真机结构：侧栏虚拟列表、搜索页没有侧栏、歌曲在 List「单曲」的 ListItem 名字里。"""

    def test_playlist_scrolled_out_of_the_sidebar_is_found_and_read_completely(self):
        # 真机根因：「总结环节」在侧栏视口之外，没实例化的项名字为空，旧代码直接报「找不到唯一的歌单」。
        ui = show()
        self.assertNotIn('总结环节', [item.name for item in ui.nav.children()])
        state = ui.run(lambda: Playlist.inspect(1, '总结环节'))
        self.assertEqual((state['name'], state['route'], state['supported'], state['complete']), ('总结环节', 'A', True, True))
        self.assertEqual([(track['title'], track['artist']) for track in state['tracks']], SONGS)
        self.assertEqual(ui.opened, '总结环节')  # 名字完全相同优先，没有打开「总结环节Lucy老师」
        self.assertNotIn('已匹配', state['note'])
        self.assertEqual(ui.play_bar_hits, 0)

    def test_search_page_switches_back_to_the_music_tab_first(self):
        ui = show(on_music=False)
        state = ui.run(lambda: Playlist.inspect(1, '总结环节'))
        self.assertTrue(state['supported'])
        self.assertEqual(ui.clicks[0], (330, 25, False))  # 先点顶部「音乐」页签

    def test_partially_hidden_entry_is_scrolled_fully_into_view_before_clicking(self):
        # 侧栏第 7 项半露在播放栏下沿：先滚进视口再点，不能点中心落到播放栏上。
        ui = FakeKugou({'厨神': [('歌', '人')], '心沉的小曲': [('歌', '人')], '总结环节': SONGS}, nav_offset=0)
        ui.nav.names[6:6] = []
        ui.nav.rectangle = SimpleNamespace(left=0, top=100, right=200, bottom=360)  # 视口高 260，第 6 项 350–400 半露
        ui.nav.layout()
        state = ui.run(lambda: Playlist.inspect(1, '总结环节'))
        self.assertTrue(state['supported'])
        self.assertEqual(ui.play_bar_hits, 0)
        x, y, _ = ui.clicks[-1]
        self.assertLessEqual(y, 360 - PLAYLIST_LAYOUT['edge_margin'])

    def test_unique_partial_name_resolves_to_the_full_playlist_name(self):
        ui = show()
        state = ui.run(lambda: Playlist.inspect(1, '总结环节Lucy'))
        self.assertEqual((state['name'], state['requested'], state['supported']), ('总结环节Lucy老师', '总结环节Lucy', True))
        self.assertIn('已匹配酷狗歌单「总结环节Lucy老师」', state['note'])
        self.assertEqual(ui.opened, '总结环节Lucy老师')

    def test_ambiguous_or_missing_names_list_the_candidates_without_opening_anything(self):
        for wanted, message in (('Lucy', '有 2 个歌单名包含「Lucy」：总结环节Lucy老师、游戏环节Lucy老师'),
                                ('不存在', '现有歌单：歌单0、歌单1')):
            with self.subTest(wanted=wanted):
                ui = show()
                state = ui.run(lambda: Playlist.inspect(1, wanted))
                self.assertFalse(state['supported'])
                self.assertIn(message, state['note'])
                self.assertIsNone(ui.opened)
                self.assertEqual(state['name'], wanted)

    def test_partial_name_is_not_guessed_before_the_whole_sidebar_is_read(self):
        ui = show()
        with patch.dict(PLAYLIST_LAYOUT, inspect_wait=0):
            state = ui.run(lambda: Playlist.inspect(1, '总结环节Lucy'))
        self.assertFalse(state['supported'])
        self.assertIsNone(ui.opened)

    def test_rewind_reads_the_top_viewport_before_scrolling_down_again(self):
        ui = FakeKugou({})
        ui.nav = VirtualList('导航', ['自建歌单', '最上面的歌单', *(f'歌单{i}' for i in range(12))],
                             left=0, top=100, width=200, height=150, row=50)
        ui.nav.scroll(1000)
        item, full = ui.run(lambda: Playlist._find_entry(1, ui.nav, '最上面的歌单', float('inf')))
        self.assertEqual((item.name, full), ('最上面的歌单', '最上面的歌单'))

    def test_ignored_wheel_cannot_prove_a_visible_name_is_unique(self):
        ui = FakeKugou({'演出甲': SONGS, **{f'歌单{i}': SONGS for i in range(9)}, '演出乙': SONGS})
        for requested in ('演出', '演出甲'):
            with self.subTest(requested=requested), patch.object(ui, 'wheel'):
                state = ui.run(lambda: Playlist.inspect(1, requested))
                self.assertFalse(state['supported'])
                self.assertIn('未完整读取', state['note'])
                self.assertIsNone(ui.opened)

    def test_duplicate_exact_names_are_rejected_across_viewports_even_with_page_open(self):
        ui = FakeKugou({'演出歌单': SONGS, **{f'歌单{i}': SONGS for i in range(10)}})
        ui.nav.names[-1] = '演出歌单'
        ui.nav.layout()
        ui.open('演出歌单')
        state = ui.run(lambda: Playlist.inspect(1, '演出歌单'))
        self.assertFalse(state['supported'])
        self.assertIn('多个名为', state['note'])
        self.assertEqual(ui.clicks, [])
        with self.assertRaisesRegex(Playlist.PlaylistUnsupported, '多个名为'):
            ui.run(lambda: Playlist._find_entry(1, ui.nav, '演出歌单', float('inf'), exact_only=True))

    def test_same_title_and_an_unrelated_list_do_not_prove_the_playlist_page(self):
        ui = FakeKugou({'演出歌单': SONGS})
        ui.open('演出歌单')
        ui.songs.name = '评论'
        with self.assertRaisesRegex(Playlist.PlaylistUnsupported, '唯一歌单正文'):
            ui.run(lambda: Playlist._page(1, '演出歌单', ui.nav))

    def test_stale_count_smaller_than_the_song_list_does_not_prove_membership(self):
        ui = FakeKugou({'演出歌单': SONGS})
        original = ui.page

        def stale_page():
            content = original()
            content.children()[1].children()[1].name = '共 1 首歌曲'
            return content

        ui.page = stale_page
        state = ui.run(lambda: Playlist.inspect(1, '演出歌单'))
        self.assertEqual(len(state['tracks']), len(SONGS))
        self.assertFalse(state['complete'])

    def test_song_with_same_title_and_artist_on_later_viewport_is_not_chosen(self):
        target = ('同名', '歌手')
        ui = FakeKugou({'演出歌单': [target, *((f'歌曲{i}', '歌手') for i in range(10)), target]}, song_rows=4)
        ui.open('演出歌单')
        ui.songs.names[-1] = ui.songs.names[-1].replace('某专辑', '另一张专辑')
        ui.songs.layout()
        with self.assertRaisesRegex(Track.TrackFailed, '多个同名版本'):
            ui.run(lambda: Playlist._scan(1, Playlist._current_page(1, '演出歌单'), float('inf'), target, name='演出歌单'))

    def test_long_playlist_is_read_screen_by_screen_without_gaps(self):
        songs = [(f'歌曲{i}', '歌手') for i in range(37)]
        ui = FakeKugou({'长歌单': songs}, song_rows=4)
        state = ui.run(lambda: Playlist.inspect(1, '长歌单'))
        self.assertTrue(state['complete'])
        self.assertEqual(len(state['tracks']), 37)

    def test_duplicate_rows_or_missing_count_keep_members_unknown(self):
        ui = FakeKugou({'重复': [('歌', '人'), ('歌', '人'), ('另一首', '人')]})
        state = ui.run(lambda: Playlist.inspect(1, '重复'))
        self.assertTrue(state['supported'])
        self.assertFalse(state['complete'])  # 共 3 首，只认出 2 首不同的歌
        ui = show()
        ui.page = lambda original=ui.page: _without_count(original())
        state = ui.run(lambda: Playlist.inspect(1, '总结环节'))
        self.assertFalse(state['complete'])

    def test_count_of_another_playlist_is_not_trusted(self):
        target, grid = page([row('一首歌', '歌手')])
        target._children.append(Element('Custom', children=[Element('Text', '别的歌单', visible=False),
                                                            Element('Text', '共 1 首歌曲', visible=False)], visible=False))
        self.assertIsNone(Playlist._total(target, '演出歌单'))

    def test_play_double_clicks_a_fully_visible_row(self):
        songs = [(f'歌曲{i}', '歌手') for i in range(12)]
        ui = FakePlaybackKugou({'演出歌单': songs}, song_rows=4)
        with patch.object(Playlist, '_current', side_effect=lambda pid: ui.now), \
             patch('KugouControl.Uia.invalidate'), patch('KugouControl.Uia.read_controls', return_value={'status': 'playing'}):
            ui.run(lambda: Playlist.play_from_playlist(1, 2, '演出歌单', '歌曲9', '歌手'))
        self.assertEqual(ui.now, ('歌曲9', '歌手'))
        x, y, double = ui.clicks[-1]
        self.assertTrue(double)
        view = ui.songs.rectangle
        self.assertTrue(view.top <= y <= view.bottom - PLAYLIST_LAYOUT['edge_margin'])
        self.assertEqual(ui.play_bar_hits, 0)


    def test_kugou_empty_playlist_text_proves_zero_songs(self):
        # 真机：酷狗空歌单页显示的是「这里没内容显示~」，没有「暂无歌曲」。
        ui = FakeKugou({'空歌单': []})
        state = ui.run(lambda: Playlist.inspect(1, '空歌单'))
        self.assertEqual((state['supported'], state['complete'], state['tracks']), (True, True, []))

    def test_play_opens_the_first_exact_match_without_reading_the_whole_sidebar(self):
        # 检测已读完侧栏确认没有重名；点播只按完整名找到第一个就打开，侧栏不用从头读到尾。
        ui = FakePlaybackKugou({'演出歌单': SONGS, **{f'歌单{i}': SONGS for i in range(10)}})
        with patch.object(Playlist, '_current', side_effect=lambda pid: ui.now), \
             patch('KugouControl.Uia.invalidate'), patch('KugouControl.Uia.read_controls', return_value={'status': 'playing'}):
            ui.run(lambda: Playlist.play_from_playlist(1, 2, '演出歌单', '晴天', '周杰伦'))
        self.assertEqual(ui.now, ('晴天', '周杰伦'))
        self.assertEqual(ui.nav.offset, 0)
        ui = FakeKugou({'演出歌单': SONGS, **{f'歌单{i}': SONGS for i in range(10)}})
        ui.run(lambda: Playlist.inspect(1, '演出歌单'))
        self.assertGreater(ui.nav.offset, 0)


class FakePlaybackKugou(FakeKugou):
    def rebuild(self):
        super().rebuild()
        bottom = (self.songs if self.songs is not None else self.nav).rectangle.bottom
        top = bottom - self.PLAY_BAR
        slider = Element('Slider', '进度', left=0, top=top, width=1000, height=5)
        bar = Element('Custom', children=[slider], left=0, top=top, width=1000, height=50)
        bar.parent = self.root
        self.root._children.append(bar)


class PlaylistClickSafetyTests(unittest.TestCase):
    def test_partial_scan_with_possible_same_name_version_does_not_fall_back_to_search(self):
        ui = FakePlaybackKugou({'演出歌单': [('歌曲', '歌手'), ('加载中', '其他')]})
        ui.open('演出歌单')
        ui.songs.names[1] = '<a 加载中>加载中</a>，歌手:其他'
        ui.songs.layout()
        with patch.object(Playlist, '_current', side_effect=lambda pid: ui.now):
            with self.assertRaisesRegex(Playlist.TrackFailed, '无法确认目标歌曲是否有多个版本'):
                ui.run(lambda: Playlist.play_from_playlist(1, 2, '演出歌单', '歌曲', '歌手'))
        self.assertFalse(any(double for _, _, double in ui.clicks))

    def test_double_click_lands_right_of_the_duration_not_on_the_artist_link(self):
        # 真机：行中点落在「Toby Fox」歌手链接上，双击跳到了歌手页。
        ui = FakePlaybackKugou({'演出歌单': [('Finale', 'Toby Fox')]})
        with patch.object(Playlist, '_current', side_effect=lambda pid: ui.now), \
             patch('KugouControl.Uia.invalidate'), patch('KugouControl.Uia.read_controls', return_value={'status': 'playing'}):
            ui.run(lambda: Playlist.play_from_playlist(1, 2, '演出歌单', 'Finale', 'Toby Fox'))
        self.assertEqual((ui.now, ui.artist_hits), (('Finale', 'Toby Fox'), 0))
        row = ui.songs.rectangle
        self.assertGreater(ui.clicks[-1][0], row.left + 0.9 * (row.right - row.left))

    def test_row_click_uses_actual_playback_bar_boundary(self):
        songs = [(f'歌曲{i}', '歌手') for i in range(4)]
        ui = FakePlaybackKugou({'演出歌单': songs}, song_rows=4)
        ui.PLAY_BAR = 15
        with patch.object(Playlist, '_current', side_effect=lambda pid: ui.now), \
             patch('KugouControl.Uia.invalidate'), patch('KugouControl.Uia.read_controls', return_value={'status': 'playing'}):
            ui.run(lambda: Playlist.play_from_playlist(1, 2, '演出歌单', '歌曲3', '歌手'))
        self.assertEqual(ui.now, ('歌曲3', '歌手'))
        self.assertEqual(ui.clicks[-1][1], round(ui.songs.rectangle.bottom - (40 + ui.PLAY_BAR) / 2))
        self.assertFalse(ui.play_bar_hits)

    def test_pause_followed_by_page_change_stops_before_double_click(self):
        ui = FakePlaybackKugou({'演出歌单': [('歌曲', '歌手')], '另一歌单': [('别的歌', '歌手')]})
        ui.now = ('歌曲', '歌手')
        with patch.object(Playlist, '_current', side_effect=lambda pid: ui.now), \
             patch.object(Playlist, '_pause', side_effect=lambda *args: ui.open('另一歌单')) as pause, \
             patch('KugouControl.Uia.invalidate'):
            with self.assertRaises(Playlist.PlaylistUnsupported):
                ui.run(lambda: Playlist.play_from_playlist(1, 2, '演出歌单', '歌曲', '歌手'))
        pause.assert_called_once()
        self.assertFalse(any(double for _, _, double in ui.clicks))

    def test_pause_followed_by_replaced_same_name_row_stops_before_double_click(self):
        ui = FakePlaybackKugou({'演出歌单': [('歌曲', '歌手')]})
        ui.now = ('歌曲', '歌手')

        def replace(*args):
            ui.songs.names[0] = ui.songs.names[0].replace('某专辑', '另一专辑')
            ui.songs.layout()

        with patch.object(Playlist, '_current', side_effect=lambda pid: ui.now), \
             patch.object(Playlist, '_pause', side_effect=replace), patch('KugouControl.Uia.invalidate'):
            with self.assertRaisesRegex(Playlist.PlaylistUnsupported, '重新确认目标歌曲行'):
                ui.run(lambda: Playlist.play_from_playlist(1, 2, '演出歌单', '歌曲', '歌手'))
        self.assertFalse(any(double for _, _, double in ui.clicks))


class PlaylistAddDialogTests(unittest.TestCase):
    def test_add_dialog_only_accepts_the_exact_playlist_name(self):
        # 加歌对话框里只认完全同名：包含匹配可能把歌加进别的歌单。
        ui = FakeKugou({'总结环节Lucy老师': [('歌', '人')], '游戏环节': [('歌', '人')]})
        with self.assertRaisesRegex(Playlist.PlaylistUnsupported, '找不到名为「总结环节」的歌单'):
            ui.run(lambda: Playlist._find_entry(1, ui.nav, '总结环节', float('inf'), exact_only=True))
        item, full = ui.run(lambda: Playlist._find_entry(1, ui.nav, '游戏环节', float('inf'), exact_only=True))
        self.assertEqual((item.name, full), ('游戏环节', '游戏环节'))

    def test_hidden_group_header_in_the_add_dialog_does_not_block_an_exact_match(self):
        # 真机：「选择位置」第 0 项是始终隐藏、读不到名字的「我的音乐」，只要求「自建歌单」之后的歌单都读到。
        ui = FakeKugou({})
        ui.nav = VirtualList('选择位置', [None, '默认列表', '我喜欢', '自建歌单', '默认收藏',
                                           *(f'歌单{i}' for i in range(30))], left=0, top=100, width=200, height=300, row=50)
        ui.nav.scroll(600)
        item, full = ui.run(lambda: Playlist._find_entry(1, ui.nav, '默认收藏', float('inf'), exact_only=True))
        self.assertEqual((item.name, full), ('默认收藏', '默认收藏'))

    def test_probe_reports_the_dialog_result_and_always_cancels(self):
        state = {'name': '演出歌单', 'supported': True, 'complete': True, 'can_add': False, 'add_note': ''}
        with patch.object(Playlist, '_process_windows', return_value=[]), \
             patch.object(Playlist, '_destination') as destination, patch.object(Playlist, '_dismiss') as dismiss:
            result = Playlist.inspect_add(1, 2, dict(state))
            self.assertTrue(result['can_add'])
            self.assertEqual(destination.call_args.args[2], '演出歌单')
            destination.side_effect = Playlist.PlaylistUnsupported('「添加到」对话框里选不中歌单「演出歌单」')
            result = Playlist.inspect_add(1, 2, dict(state))
            self.assertFalse(result['can_add'])
            self.assertIn('选不中', result['add_note'])
            self.assertEqual(dismiss.call_count, 2)

    def test_add_probe_does_not_offer_unsafe_add_for_incomplete_membership(self):
        state = {'name': '演出歌单', 'supported': True, 'complete': False, 'can_add': False}
        with patch.object(Playlist, '_process_windows') as windows:
            result = Playlist.inspect_add(1, 2, state)
        self.assertFalse(result['can_add'])
        self.assertIn('排除重复添加', result['add_note'])
        windows.assert_not_called()

    def test_confirm_rechecks_the_fresh_selection_before_clicking(self):
        places = VirtualList('选择位置', ['演出歌单', '另一歌单'], left=0, top=50, width=210, height=100, row=40)
        dialog = Element('Window', '添加到', [places, Element('Button', '确定')])
        pattern = lambda element, name: (SimpleNamespace(CurrentIsSelected=element.name == '另一歌单')
                                         if name == 'SelectionItem' else None)
        with patch.object(Playlist, '_root', return_value=dialog), patch.object(Playlist, '_pattern', side_effect=pattern), \
             patch.object(Playlist, '_process_windows', return_value=[3]), patch('win32gui.GetWindowText', return_value='添加到'), \
             patch.object(Playlist.Input, 'click') as click:
            with self.assertRaisesRegex(Playlist.PlaylistUnsupported, '无法确认唯一选中'):
                Playlist._confirm((2, 3, '演出歌单', 0, 2), float('inf'), check_source=MagicMock(), mark_committed=MagicMock())
        click.assert_not_called()

    def test_confirm_does_not_click_when_post_commit_budget_has_elapsed(self):
        dialog = Element('Window', '添加到', [Element('List', '选择位置'), Element('Button', '确定')])
        attempted = MagicMock()
        with patch.object(Playlist, '_root', return_value=dialog), \
             patch.object(Playlist, '_selected_destination', return_value=True), \
             patch.object(Playlist, '_process_windows', return_value=[3]), patch('win32gui.GetWindowText', return_value='添加到'), \
             patch.object(Playlist.Input, 'click') as click:
            with self.assertRaisesRegex(Playlist.PlaylistUnsupported, '核验时间不足'):
                Playlist._confirm((2, 3, '演出歌单', 0, 2), 0, check_source=MagicMock(), mark_committed=attempted)
        click.assert_not_called()
        attempted.assert_not_called()

    def test_confirmation_refuses_a_replaced_add_window(self):
        with patch.object(Playlist, '_process_windows', return_value=[4]), patch.object(Playlist.Input, 'click') as click:
            with self.assertRaisesRegex(Playlist.PlaylistUnsupported, '对话框不再有效'):
                Playlist._confirm((2, 3, '演出歌单', 0, 2), float('inf'),
                                  check_source=MagicMock(), mark_committed=MagicMock())
        click.assert_not_called()

    def test_dismiss_only_closes_observed_add_windows(self):
        titles = {1: '酷狗音乐', 3: '更多', 4: '添加到', 5: '下载', 6: '添加到'}
        with patch.object(Playlist, '_process_windows', side_effect=[list(titles), [1, 5, 6]]), \
             patch('win32gui.GetWindowText', side_effect=titles.get), \
             patch.object(Playlist.Input, 'press') as press:
            Playlist._dismiss(2, {3: '更多', 4: '添加到', 5: '添加到'})
        self.assertCountEqual([call.args[0] for call in press.call_args_list], [3, 4])


def _without_count(content):
    for child in content.children():
        child._children = [c for c in child.children() if not c.name.startswith('共')]
    return content


class PlaylistRoutingTests(unittest.TestCase):
    def test_hit_never_runs_search(self):
        with patch.object(Playlist, 'play_from_playlist') as direct, patch.object(Track, '_play_search') as search:
            result = Track.play_track(1, 2, '歌曲', '歌手', playlist='演出歌单')
        self.assertEqual(result['via'], 'playlist')
        direct.assert_called_once()
        search.assert_not_called()

    def test_confirmed_miss_runs_search_once(self):
        with patch.object(Playlist, 'play_from_playlist', side_effect=Playlist.PlaylistMiss('不在')), \
             patch.object(Track, '_play_search') as search:
            result = Track.play_track(1, 2, '歌曲', '歌手', playlist='演出歌单')
        self.assertTrue(result['playlist_missed'])
        search.assert_called_once()

    def test_wrong_version_and_loading_do_not_fall_back(self):
        for error in (Track.TrackFailed('播错版本'), Track.TrackLoading('加载中')):
            with self.subTest(error=error), patch.object(Playlist, 'play_from_playlist', side_effect=error), \
                 patch.object(Track, '_play_search') as search:
                with self.assertRaises(type(error)):
                    Track.play_track(1, 2, '歌曲', '歌手', playlist='演出歌单')
                search.assert_not_called()

    def test_disabled_and_known_absent_skip_playlist(self):
        for options in ({}, {'playlist': '演出歌单', 'in_playlist': False}):
            with patch.object(Playlist, 'play_from_playlist') as direct, patch.object(Track, '_play_search') as search:
                self.assertEqual(Track.play_track(1, 2, '歌曲', '歌手', **options)['via'], 'search')
                direct.assert_not_called()
                search.assert_called_once()

    def test_current_title_alone_cannot_confirm_playback(self):
        ui = FakePlaybackKugou({'演出歌单': [('歌曲', '歌手')]})
        ui.now = ('歌曲', '歌手')
        with patch.object(Playlist, '_current', side_effect=lambda pid: ui.now), patch.object(Playlist, '_pause') as pause, \
             patch('KugouControl.Uia.invalidate'), patch('KugouControl.Uia.read_controls', return_value={'status': 'paused'}), \
             patch.dict(PLAYLIST_LAYOUT, wait=5, play_wait=0.01):
            with self.assertRaisesRegex(Track.TrackFailed, '没有核验到目标歌曲开始播放'):
                ui.run(lambda: Playlist.play_from_playlist(1, 2, '演出歌单', '歌曲', '歌手'))
            pause.assert_called_once()
            self.assertTrue(ui.clicks[-1][2])

    def test_worker_preserves_loading_route(self):
        error = Track.TrackLoading('仍在加载')
        error.via = 'playlist'
        with patch.object(Worker, 'read', return_value={'connected': True, 'profile': 'verified', 'controls_ready': True, 'hwnd': 1, 'pid': 2}), \
             patch.object(Track, 'play_track', side_effect=error):
            result = Worker.operate('play_track {"title":"歌曲","playlist":"演出歌单"}')
        self.assertEqual(result['result']['via'], 'playlist')

    def test_adapter_uses_combined_budget_and_keeps_route_after_reads(self):
        calls = []
        state = {'connected': True, 'status': 'playing', 'title': '歌曲', 'artist': '歌手', 'profile': 'p', 'controls_ready': True}
        def runner(args, **kwargs):
            calls.append(kwargs['timeout'])
            return subprocess.CompletedProcess(args, 0, json.dumps({'data': state, 'result': {'via': 'playlist'}}))
        controller = KugouController(runner=runner)
        controller.configure_playlist('演出歌单')
        controller._playlist['supported'] = True
        controller.play_track({'id': 1, 'title': '歌曲', 'artist': '歌手'})
        self.assertGreater(calls[0], 32)
        self.assertEqual(controller.get_state().via, 'playlist')
        self.assertEqual(controller.play_result['via'], 'playlist')

    def test_add_timeout_is_not_retried_and_reports_unverified_pause(self):
        calls = []
        def runner(args, **kwargs):
            calls.append(args[-1])
            self.assertEqual(kwargs['timeout'], PLAYLIST_ADD_TIMEOUT)
            raise subprocess.TimeoutExpired(args, kwargs['timeout'])
        controller = KugouController(runner=runner)
        controller.configure_playlist('演出歌单')
        controller._playlist['can_add'] = True
        with self.assertRaisesRegex(ControllerTimeout, '检查并暂停'):
            controller.add_to_playlist({'id': 1, 'title': '歌曲', 'artist': '歌手'})
        with self.assertRaisesRegex(CapabilityUnsupported, '先完整刷新歌单'):
            controller.add_to_playlist({'id': 1, 'title': '歌曲', 'artist': '歌手'})
        self.assertEqual(len(calls), 1)

    def test_uncertain_commit_blocks_repeat_until_complete_refresh(self):
        song = {'id': 1, 'title': '歌曲', 'artist': '歌手'}
        snapshot = {'name': '演出歌单', 'requested': '演出歌单', 'supported': True, 'can_add': True,
                    'complete': False, 'tracks': []}
        responses = iter([{'result': {'status': 'unverified', 'retry_requires_refresh': True}},
                          {'playlist': dict(snapshot)}, {'playlist': {**snapshot, 'complete': True}},
                          {'result': {'status': 'already_present', 'in_playlist': True}}])
        def runner(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, json.dumps(next(responses)))
        controller = KugouController(runner=runner)
        controller.configure_playlist('演出歌单')
        controller._playlist['can_add'] = True
        self.assertEqual(controller.add_to_playlist(song), {'status': 'unverified'})
        controller.refresh_playlist()
        with self.assertRaises(CapabilityUnsupported):
            controller.add_to_playlist(song)
        controller.refresh_playlist()
        self.assertEqual(controller.add_to_playlist(song)['status'], 'already_present')

    def test_refresh_keeps_previous_snapshot_until_valid_response(self):
        def runner(args, **kwargs):
            self.assertTrue(controller.playlist_snapshot()['supported'])
            return subprocess.CompletedProcess(args, 0, json.dumps({'playlist': {'name': '另一张歌单', 'supported': True}}))
        controller = KugouController(runner=runner)
        controller.configure_playlist('演出歌单')
        controller._playlist['supported'] = True
        before = controller.playlist_snapshot()
        with self.assertRaises(PlayerUnavailable):
            controller.refresh_playlist()
        self.assertEqual(controller.playlist_snapshot(), before)

    def test_probe_readiness_is_distinct_from_verified_playback(self):
        controller = KugouController(runner=lambda *args, **kwargs: None)
        controller.info = {'profile': 'verified-version', 'controls_ready': True}
        controller.configure_playlist('演出歌单')
        controller._playlist.update(supported=True, can_add=True)
        caps = {item['name']: item for item in controller.capabilities()}
        self.assertTrue(caps['play_from_playlist']['supported'])
        self.assertFalse(caps['play_from_playlist']['verified'])
        self.assertFalse(caps['add_to_playlist']['verified'])


class PlaylistRepositoryTests(unittest.TestCase):
    def test_tristate_scopes_invalidation_and_deleted_song(self):
        database = Database(':memory:', seed=False)
        try:
            song = SongRepository(database).create('歌曲', '歌手')
            repo = PlaylistRepository(database)
            for present in (None, True, False):
                repo.set('甲歌单', song, present)
                self.assertIs(repo.list('甲歌单')[song['id']], present)
            self.assertEqual(repo.list('乙歌单'), {})
            SongRepository(database).update(song['id'], title='新名称')
            self.assertEqual(repo.list('甲歌单'), {})
            repo.set('甲歌单', song, True)
            self.assertEqual(repo.list('甲歌单'), {})
            SongRepository(database).delete(song['id'])
            self.assertEqual(database.query_one('SELECT COUNT(*) FROM playlist_tracks')[0], 0)
        finally:
            database.close()

    def test_upgrade_existing_database_preserves_queue_history_and_settings(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            old = Path(directory) / 'old'
            old.mkdir()
            migration = Path(__file__).parents[1] / 'Database' / 'Migrations' / '001Init.sql'
            (old / migration.name).write_text(migration.read_text(encoding='utf-8'), encoding='utf-8')
            path = Path(directory) / 'upgrade.db'
            first = Database(path, migrations_dir=old)
            QueueRepository(first).add(1)
            SettingsRepository(first).set(PLAYLIST_KEY, '演出歌单')
            session = SessionRepository(first).start()
            SessionRepository(first).add_history(session['id'], song_id=1, title='晴天', artist='周杰伦')
            first.close()
            second = Database(path)
            try:
                self.assertEqual(QueueRepository(second).list_items()[0]['song_id'], 1)
                self.assertEqual(SettingsRepository(second).get(PLAYLIST_KEY), '演出歌单')
                self.assertEqual(second.query_one('SELECT COUNT(*) FROM schema_migrations')[0], 2)
                self.assertEqual(len(SessionRepository(second).list_history(session['id'])), 1)
                PlaylistRepository(second).set('演出歌单', SongRepository(second).get(1), True)
            finally:
                second.close()
            third = Database(path)
            try:
                self.assertTrue(PlaylistRepository(third).list('演出歌单')[1])
            finally:
                third.close()


class PlaylistAddTests(unittest.TestCase):
    song = {'title': '歌曲', 'artist': '歌手'}

    def test_add_refuses_to_open_or_audition_for_a_replacement_playlist_with_similar_name(self):
        ui = FakeKugou({'演出歌单（备份）': [('别的歌', '歌手')]})
        with patch.object(Track, '_play_search') as search:
            with self.assertRaisesRegex(Playlist.PlaylistUnsupported, '找不到名为「演出歌单」的歌单'):
                ui.run(lambda: Playlist.add_to_playlist(1, 2, '演出歌单', '歌曲', '歌手'))
        search.assert_not_called()
        self.assertEqual(ui.clicks, [])

    def run_add(self, *, before=None, after=None, audition=('歌曲', '歌手'), switch=None,
                inspect_delay=0, search_delay=0, invoke_error=None, dismiss_error=None):
        state = {'name': '演出歌单', 'supported': True, 'complete': True, 'tracks': []}
        before = {**state, **(before or {})}
        after = {**state, 'tracks': [self.song], **(after or {})}
        live = SimpleNamespace(now=('旧歌', '旧歌手'), clock=100.0, duration=180, examined=False, committed=False)

        def inspect(*args, **kwargs):
            if not live.examined:
                live.examined = True
                live.clock += inspect_delay
                return before
            return after

        def search(*args, **kwargs):
            live.clock += search_delay
            live.now = audition

        def destination(*args, check_source):
            check_source()
            if switch is not None:
                live.now, live.duration = switch
            return object()

        def confirm(*args, check_source, mark_committed):
            check_source()
            if invoke_error is not None:
                raise invoke_error
            mark_committed()
            live.committed = True

        with ExitStack() as stack:
            scan = stack.enter_context(patch.object(Playlist, 'inspect', side_effect=inspect))
            stack.enter_context(patch.object(Playlist, '_current', side_effect=lambda pid: live.now))
            menu = stack.enter_context(patch.object(Playlist, '_destination', side_effect=destination))
            stack.enter_context(patch.object(Playlist, '_process_windows', return_value=[]))
            stack.enter_context(patch.object(Playlist, '_dismiss', side_effect=dismiss_error))
            stack.enter_context(patch.object(Playlist.time, 'monotonic', side_effect=lambda: live.clock))
            stack.enter_context(patch('KugouControl.Uia.invalidate'))
            stack.enter_context(patch('KugouControl.Uia.read_controls',
                                      side_effect=lambda hwnd: {'status': 'playing', 'duration': live.duration}))
            auditioned = stack.enter_context(patch.object(Track, '_play_search', side_effect=search))
            play = stack.enter_context(patch.object(Playlist, 'play_from_playlist'))
            invoke = stack.enter_context(patch.object(Playlist, '_confirm', side_effect=confirm))
            pause = stack.enter_context(patch.object(Playlist, '_pause'))
            result = Playlist.add_to_playlist(1, 2, '演出歌单', '歌曲', '歌手')
        return SimpleNamespace(result=result, search=auditioned, play=play, invoke=invoke,
                               pause=pause, scan=scan, menu=menu, committed=live.committed)

    def test_present_song_does_not_audition_or_add(self):
        attempt = self.run_add(before={'tracks': [self.song]})
        self.assertEqual(attempt.result['status'], 'already_present')
        attempt.search.assert_not_called()
        attempt.invoke.assert_not_called()

    def test_exact_version_is_required_before_adding(self):
        attempt = self.run_add(audition=('歌曲 (Live)', '歌手'))
        self.assertEqual(attempt.result['status'], 'unverified')
        attempt.invoke.assert_not_called()
        attempt.pause.assert_called_once()

    def test_click_without_membership_verification_is_unverified(self):
        for after in ({'tracks': []}, {'name': '另一歌单'}, {'tracks': [self.song, self.song]}, {'complete': False}):
            with self.subTest(after=after):
                attempt = self.run_add(after=after)
                self.assertEqual(attempt.result['status'], 'unverified')
                self.assertIsNone(attempt.result['in_playlist'])
                self.assertTrue(attempt.result['retry_requires_refresh'])
                self.assertTrue(attempt.committed)
                attempt.invoke.assert_called_once()
                attempt.pause.assert_called_once()

    def test_success_requires_a_fresh_membership_scan_and_pauses_without_replay(self):
        attempt = self.run_add(inspect_delay=6)
        self.assertEqual(attempt.result['status'], 'added')
        self.assertEqual(attempt.scan.call_count, 2)
        attempt.search.assert_called_once()
        attempt.play.assert_not_called()
        attempt.invoke.assert_called_once()
        attempt.pause.assert_called_once()
        self.assertGreater(attempt.pause.call_args.args[1], attempt.scan.call_args.kwargs['deadline'])
        self.assertGreater(attempt.scan.call_args.kwargs['deadline'], attempt.invoke.call_args.args[1])

    def test_add_does_not_claim_success_if_count_or_duration_disagrees(self):
        other = {'title': '已有歌曲', 'artist': '歌手'}
        for before, after in (([other], [self.song]), ([], [{**self.song, 'duration': 220}])):
            with self.subTest(before=before, after=after):
                attempt = self.run_add(before={'tracks': before}, after={'tracks': after})
                self.assertEqual(attempt.result['status'], 'unverified')
                self.assertTrue(attempt.result['retry_requires_refresh'])

    def test_menu_failure_is_not_retried(self):
        attempt = self.run_add(invoke_error=Playlist.PlaylistUnsupported('菜单不可用'))
        self.assertEqual(attempt.result['status'], 'unverified')
        attempt.invoke.assert_called_once()
        self.assertEqual(attempt.scan.call_count, 1)
        self.assertNotIn('retry_requires_refresh', attempt.result)

    def test_incomplete_or_ambiguous_membership_is_not_added(self):
        for before in ({'complete': False}, {'tracks': [self.song, self.song]}):
            with self.subTest(before=before):
                attempt = self.run_add(before=before)
                self.assertEqual(attempt.result['status'], 'unverified')
                attempt.search.assert_not_called()
                attempt.invoke.assert_not_called()
                attempt.pause.assert_not_called()

    def test_source_change_while_selecting_destination_prevents_confirmation(self):
        for switch in ((('另一首歌', '歌手'), 180), (('歌曲', '歌手'), 200)):
            with self.subTest(switch=switch):
                attempt = self.run_add(switch=switch)
                self.assertEqual(attempt.result['status'], 'unverified')
                self.assertNotIn('retry_requires_refresh', attempt.result)
                self.assertFalse(attempt.committed)
                attempt.pause.assert_called_once()

    def test_slow_preflight_does_not_start_audition_without_cleanup_budget(self):
        attempt = self.run_add(inspect_delay=16)
        self.assertEqual(attempt.result['status'], 'unverified')
        attempt.search.assert_not_called()
        attempt.menu.assert_not_called()

    def test_slow_audition_does_not_open_confirmation_without_verification_budget(self):
        attempt = self.run_add(inspect_delay=10, search_delay=23)
        self.assertEqual(attempt.result['status'], 'unverified')
        attempt.search.assert_called_once()
        attempt.menu.assert_not_called()
        attempt.pause.assert_called_once()

    def test_dialog_cleanup_failure_still_attempts_pause(self):
        attempt = self.run_add(dismiss_error=OSError('无法取消'))
        self.assertEqual(attempt.result['status'], 'unverified')
        self.assertTrue(attempt.result['retry_requires_refresh'])
        self.assertIn('无法核验加歌弹窗已关闭', attempt.result['message'])
        attempt.pause.assert_called_once()


class FakePlaylistController(MockPlayerController):
    name = 'kugou'

    def __init__(self):
        super().__init__()
        self.configured = ''
        self.result = {'status': 'added', 'message': '已加入并核验', 'in_playlist': True}
        self.play_result = {}
        self.loading = False
        self.resolved, self.fail, self.supported = None, None, True

    def configure_playlist(self, name):
        self.configured = name

    def playlist_snapshot(self):
        return {'name': self.resolved or self.configured, 'requested': self.configured, 'route': 'A',
                'supported': self.supported, 'can_add': True, 'complete': False,
                'tracks': [{'title': '晴天', 'artist': '周杰伦'}], 'note': 'test'}

    def refresh_playlist(self):
        if self.fail:
            raise self.fail
        return self.playlist_snapshot()

    def add_to_playlist(self, song):
        super().play_track(song)  # 试听真实状态变化，但不能借此提交待播和已播。
        self.toggle()
        return self.result

    def play_track(self, song):
        self.received = song
        super().play_track(song)
        self.play_result = {'via': 'playlist'}
        if self.loading:
            self._reading = PlayerReading(**{**self._reading.__dict__, 'status': 'paused'})
            raise ControllerTrackLoading('加载中')


class PlaylistServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.database = Database(':memory:')
        SettingsRepository(self.database).set(PLAYLIST_KEY, '演出歌单')
        self.controller = FakePlaylistController()
        self.service = PlayerService(self.database, controller_name='kugou', factory=lambda: self.controller)
        await self.service.refresh()

    async def asyncTearDown(self):
        await self.service.close()
        self.database.close()

    async def test_refresh_only_marks_members_absent_when_scan_complete(self):
        result = await self.service.refresh_playlist()
        self.assertTrue(result['songs'][1])
        self.assertNotIn(2, result['songs'])

    async def test_audition_does_not_mutate_queue_or_history(self):
        await self.service.enqueue(1, 'end')
        result = await self.service.add_to_playlist(1)
        self.assertEqual(result['status'], 'added')
        self.assertEqual(len(QueueRepository(self.database).list_items()), 1)
        self.assertEqual(self.database.query_one('SELECT COUNT(*) FROM history')[0], 0)
        self.assertEqual(self.service.state.status, 'paused')

    async def test_unverified_add_does_not_mark_present(self):
        self.controller.result = {'status': 'unverified', 'message': '无法确认', 'in_playlist': None}
        result = await self.service.add_to_playlist(1)
        self.assertIsNone(result['playlist']['songs'][1])

    async def test_loading_paused_reading_does_not_commit_early(self):
        await self.service.enqueue(1, 'end')
        self.controller.loading = True
        with self.assertRaises(PlayerConflict):
            await self.service.command(PlayerCommand(action='play', song_id=1))
        self.assertEqual(len(QueueRepository(self.database).list_items()), 1)
        self.controller._reading = PlayerReading(**{**self.controller._reading.__dict__, 'status': 'playing'})
        await self.service.refresh()
        self.assertEqual(QueueRepository(self.database).list_items(), [])
        self.assertTrue((await self.service.playlist())['songs'][1])

    async def test_detected_full_name_is_written_back_and_old_records_dropped(self):
        PlaylistRepository(self.database).set('演出歌单', SongRepository(self.database).get(2), False)
        self.controller.resolved = '演出歌单（完整名）'
        PlaylistRepository(self.database).set(self.controller.resolved, SongRepository(self.database).get(2), False)
        result = await self.service.refresh_playlist()
        self.assertEqual(SettingsRepository(self.database).get(PLAYLIST_KEY), '演出歌单（完整名）')
        self.assertEqual(result['name'], '演出歌单（完整名）')
        self.assertEqual(PlaylistRepository(self.database).list('演出歌单'), {})
        self.assertTrue(result['songs'][1])
        self.assertNotIn(2, result['songs'])

    async def test_write_back_never_overrides_a_name_the_user_changed_meanwhile(self):
        settings = SettingsRepository(self.database)
        repository = PlaylistRepository(self.database)
        other = '用户刚改的'
        repository.set(other, SongRepository(self.database).get(2), True)

        def refresh():
            old = {**self.controller.playlist_snapshot(), 'name': '演出歌单（完整名）', 'complete': True}
            settings.set(PLAYLIST_KEY, other)
            self.controller.supported = False
            return old

        with patch.object(self.controller, 'refresh_playlist', side_effect=refresh):
            result = await self.service.refresh_playlist()
        self.assertEqual(settings.get(PLAYLIST_KEY), other)
        self.assertEqual(self.controller.configured, other)
        self.assertFalse(result['supported'])
        self.assertEqual(result['songs'], {2: True})
        self.assertEqual(repository.list('演出歌单（完整名）'), {})

    async def test_refresh_rejects_old_snapshot_even_if_setting_returns_to_same_name(self):
        settings = SettingsRepository(self.database)
        repository = PlaylistRepository(self.database)
        repository.set('演出歌单', SongRepository(self.database).get(2), True)

        def refresh():
            old = {**self.controller.playlist_snapshot(), 'name': '旧全名', 'complete': True}
            settings.set(PLAYLIST_KEY, '另一张歌单')
            settings.set(PLAYLIST_KEY, '演出歌单')
            self.controller.supported = False
            return old

        with patch.object(self.controller, 'refresh_playlist', side_effect=refresh):
            result = await self.service.refresh_playlist()
        self.assertEqual(settings.get(PLAYLIST_KEY), '演出歌单')
        self.assertTrue(result['songs'][2])
        self.assertEqual(repository.list('旧全名'), {})

    async def test_failed_or_unreadable_refresh_keeps_member_records(self):
        PlaylistRepository(self.database).set('演出歌单', SongRepository(self.database).get(2), False)
        self.controller.fail = PlayerUnavailable('酷狗未运行')
        with self.assertRaises(PlayerDisconnected):
            await self.service.refresh_playlist()
        self.controller.fail, self.controller.supported = None, False
        self.controller.resolved = '未确认的全名'
        await self.service.refresh_playlist()
        self.assertEqual(SettingsRepository(self.database).get(PLAYLIST_KEY), '演出歌单')
        self.assertIs(PlaylistRepository(self.database).list('演出歌单')[2], False)

    async def test_concurrent_add_is_rejected_without_replay(self):
        async with self.service._lock:
            with self.assertRaisesRegex(PlayerConflict, '其他操作'):
                await self.service.add_to_playlist(1)

    async def test_refresh_and_settings_save_do_not_queue_behind_player(self):
        async with self.service._lock:
            with self.assertRaisesRegex(PlayerConflict, '再刷新歌单'):
                await self.service.refresh_playlist()
            with self.assertRaisesRegex(PlayerConflict, '再保存播放器设置'):
                await self.service.switch_controller('kugou', '另一张歌单')
        self.assertEqual(SettingsRepository(self.database).get(PLAYLIST_KEY), '演出歌单')


class PlaylistApiTests(unittest.TestCase):
    def test_strict_requests_and_settings_compatibility(self):
        database = Database(':memory:')
        ppt = PptService(factory=lambda app: FakePptController(app), poll_interval=100)
        service = PlayerService(database, poll_interval=100)
        with TestClient(create_app(ppt, database, service)) as client:
            self.assertEqual(client.put('/api/settings/controller', json={'name': 'mock', 'playlist': ' 演出歌单 '}).status_code, 200)
            self.assertEqual(client.get('/api/playlist').json()['name'], '演出歌单')
            client.put('/api/settings/controller', json={'name': 'mock'})
            self.assertEqual(client.get('/api/playlist').json()['name'], '演出歌单')
            for value in ('1', True, -1):
                self.assertEqual(client.post('/api/playlist/tracks', json={'song_id': value}).status_code, 422)
            self.assertEqual(client.post('/api/playlist/tracks', json={'song_id': 1}).status_code, 409)
            self.assertEqual(client.post('/api/playlist/tracks', json={'song_id': 9999}).status_code, 404)
            self.assertEqual(client.post('/api/playlist/refresh').status_code, 409)
            client.put('/api/settings/controller', json={'name': 'mock', 'playlist': ''})
            self.assertEqual(client.get('/api/playlist').json()['name'], '')


if __name__ == '__main__':
    unittest.main()
