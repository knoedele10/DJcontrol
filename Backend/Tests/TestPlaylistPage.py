"""歌单导航、歌曲识别和页面扫描测试。"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from KugouControl import Playlist, Track
from KugouControl.Playlist import Navigation, Page, Playback, Scrolling
from KugouControl.Profiles import PLAYLIST_LAYOUT, exact_track
from Tests.TestPlaylistFakes import (
    Element, FakeKugou, FakePlaybackKugou, IsolatedPlaylistTestCase, SONGS,
    VirtualList, _without_count, kugou_row, page, row, show,
)


class PlaylistIdentityTests(IsolatedPlaylistTestCase):
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
        self.assertEqual(Page._labelled_row('<a Memories>Memories</a>，歌手:ＴＲＡ＄Ｈ，专辑:Memories，时长:02:33'),
                         {'title': 'Memories', 'artist': 'ＴＲＡ＄Ｈ', 'album': 'Memories', 'duration': 153})
        self.assertEqual(Page._labelled_row('<a 明天，你好>明天，你好</a>，歌手:牛奶咖啡，专辑:Lost & Found去寻找，时长:04:31'),
                         {'title': '明天，你好', 'artist': '牛奶咖啡', 'album': 'Lost & Found去寻找', 'duration': 271})
        self.assertEqual(Page._labelled_row('<a a>b>a>b</a>，歌手:甲、乙，时长:01:00'),
                         {'title': 'a>b', 'artist': '甲、乙', 'duration': 60})
        # 列表末尾残留的旧行只有链接文字，没有歌手：不能当成一首歌。
        self.assertIsNone(Page._labelled_row('<a Memories>Memories</a>'))
        self.assertIsNone(Page._labelled_row('歌手 - 歌曲'))

    def test_labelled_rows_reject_partial_or_ambiguous_fields_without_shortening_artist(self):
        for label in ('<a 歌曲>歌曲</a>，歌手:歌手', '<a 旧歌>歌曲</a>，歌手:歌手，时长:03:00',
                      '<a 歌曲>歌曲</a>，歌手:甲，专辑:乙，专辑:某专辑，时长:03:00'):
            with self.subTest(label=label):
                self.assertIsNone(Page._labelled_row(label))
        track = Page._labelled_row('<a 歌曲>歌曲</a>，歌手:甲，时长:乙，专辑:某专辑，时长:03:00')
        self.assertEqual(track['artist'], '甲，时长:乙')

    def test_scan_does_not_infer_identity_from_an_unlabelled_row(self):
        target, _ = page([Element('DataItem', '歌手 - 歌曲')])
        with patch.object(Page, '_pattern', return_value=None), patch.object(Scrolling, 'Input'), \
             patch.object(Scrolling.time, 'sleep'), patch.dict(PLAYLIST_LAYOUT, load_wait=0):
            tracks, complete, _ = Page._scan(1, target, float('inf'))
        self.assertEqual(tracks, [])
        self.assertFalse(complete)

    def test_scan_virtual_list_reads_the_last_song_and_checks_scroll(self):
        names = [kugou_row(f'歌曲{i}', '歌手') for i in range(120)] + [kugou_row('末尾歌曲', '歌手')]
        target, scroll = self._pattern_page(names)
        with patch.object(Page, '_pattern', return_value=scroll), patch.object(Scrolling.time, 'sleep'):
            tracks, complete, _ = Page._scan(1, target, float('inf'))
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
        with patch.object(Page, '_pattern', return_value=scroll), patch.object(Scrolling.time, 'sleep'):
            tracks, complete, _ = Page._scan(1, target, float('inf'), ('歌曲9', '歌手'))
        self.assertEqual(len(tracks), 4)
        self.assertFalse(complete)

    def test_unreadable_row_on_an_earlier_viewport_keeps_members_unknown(self):
        target, scroll = self._pattern_page(['不可识别'] + [kugou_row(f'歌曲{i}', '歌手') for i in range(10)])
        with patch.object(Page, '_pattern', return_value=scroll), patch.object(Scrolling.time, 'sleep'):
            tracks, complete, _ = Page._scan(1, target, float('inf'), ('不存在', '歌手'))
        self.assertEqual(scroll.CurrentVerticalScrollPercent, 100)
        self.assertIn(('歌曲9', '歌手'), [(track['title'], track['artist']) for track in tracks])
        self.assertFalse(complete)

    def test_positive_count_with_empty_indicator_does_not_prove_absence(self):
        target, _ = page([], [Element('Custom', children=[Element('Text', '演出歌单', visible=False),
                                                            Element('Text', '共 1 首歌曲', visible=False)]),
                              Element('Text', '没有搜索结果')])
        with patch.object(Page, '_pattern', return_value=None), patch.object(Scrolling, 'Input'), \
             patch.object(Scrolling.time, 'sleep'), patch.dict(PLAYLIST_LAYOUT, load_wait=0):
            tracks, complete, _ = Page._scan(1, target, float('inf'), name='演出歌单')
        self.assertEqual(tracks, [])
        self.assertFalse(complete)

    def test_active_filter_is_not_an_unfiltered_member_snapshot(self):
        filtered, _ = page([row('一首歌', '歌手')], [Element('Edit', '歌单内搜索')])
        with patch.object(Page, '_pattern', return_value=SimpleNamespace(CurrentValue='旧关键字')):
            self.assertEqual(Page._scan(1, filtered, float('inf')), ([], False, None))

    def test_replaced_collection_cannot_publish_stale_members(self):
        before, _ = page([row('旧歌', '歌手')])
        after, _ = page([row('新歌', '歌手')])
        with patch.object(Page, '_pattern', return_value=None), patch.object(Scrolling, 'Input'), \
             patch.object(Scrolling.time, 'sleep'):
            current_page = iter((before, after)).__next__
            self.assertEqual(Page._scan(1, before, float('inf'), verify_page=current_page), ([], False, None))

    def test_scroll_failure_keeps_absent_members_unknown(self):
        target, _ = page([row('一首歌', '歌手')])
        scroll = SimpleNamespace(CurrentVerticallyScrollable=True, CurrentVerticalScrollPercent=50, SetScrollPercent=lambda *args: None)
        with patch.object(Page, '_pattern', return_value=scroll), patch.object(Scrolling.time, 'sleep'):
            with self.assertRaises(Playlist.PlaylistUnsupported):
                Page._scan(1, target, float('inf'))

    def test_wheel_that_does_not_move_is_not_proof_of_the_end(self):
        # 没有 ScrollPattern 只能滚轮；滚不动也可能是消息没送达，没有「共 N 首」就不认读全。
        target, grid = page([row('一首歌', '歌手')])
        grid._children.append(Element('ScrollBar'))
        with patch.object(Page, '_pattern', return_value=None), patch.object(Scrolling, 'Input'), \
             patch.object(Scrolling.time, 'sleep'):
            tracks, complete, _ = Page._scan(1, target, float('inf'))
        self.assertEqual(len(tracks), 1)
        self.assertFalse(complete)

    def test_probe_never_enables_unmeasured_filter_coordinates(self):
        target = Element('Custom', '演出歌单', [Element('Edit', '歌单内搜索')])
        with patch.object(Page, 'open_playlist', return_value=(target, '演出歌单')), patch.object(Page, '_set_filter'), \
             patch.object(Page, '_current_page', return_value=target), \
             patch.object(Page, '_pattern', return_value=None), \
             patch.dict(PLAYLIST_LAYOUT, first_song=None):
            state = Playlist.inspect(1, '演出歌单')
        self.assertFalse(state['supported'])
        self.assertIn('尚未真机验证', state['note'])


class PlaylistNavigationTests(IsolatedPlaylistTestCase):
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
        item, full = ui.run(lambda: Navigation._find_entry(1, ui.nav, '最上面的歌单', float('inf')))
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
            ui.run(lambda: Navigation._find_entry(1, ui.nav, '演出歌单', float('inf'), exact_only=True))

    def test_same_title_and_an_unrelated_list_do_not_prove_the_playlist_page(self):
        ui = FakeKugou({'演出歌单': SONGS})
        ui.open('演出歌单')
        ui.songs.name = '评论'
        with self.assertRaisesRegex(Playlist.PlaylistUnsupported, '唯一歌单正文'):
            ui.run(lambda: Page._page(1, '演出歌单', ui.nav))

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
            ui.run(lambda: Page._scan(1, Page._current_page(1, '演出歌单'), float('inf'), target, name='演出歌单'))

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
        self.assertIsNone(Page._total(target, '演出歌单'))

    def test_play_double_clicks_a_fully_visible_row(self):
        songs = [(f'歌曲{i}', '歌手') for i in range(12)]
        ui = FakePlaybackKugou({'演出歌单': songs}, song_rows=4)
        with patch.object(Playback, '_current', side_effect=lambda pid: ui.now), \
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
        with patch.object(Playback, '_current', side_effect=lambda pid: ui.now), \
             patch('KugouControl.Uia.invalidate'), patch('KugouControl.Uia.read_controls', return_value={'status': 'playing'}):
            ui.run(lambda: Playlist.play_from_playlist(1, 2, '演出歌单', '晴天', '周杰伦'))
        self.assertEqual(ui.now, ('晴天', '周杰伦'))
        self.assertEqual(ui.nav.offset, 0)
        ui = FakeKugou({'演出歌单': SONGS, **{f'歌单{i}': SONGS for i in range(10)}})
        ui.run(lambda: Playlist.inspect(1, '演出歌单'))
        self.assertGreater(ui.nav.offset, 0)
