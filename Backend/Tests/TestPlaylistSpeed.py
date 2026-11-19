"""验证虚拟列表复用槽位时的覆盖，以及代表性歌单的检测操作次数。"""
from unittest.mock import patch

from KugouControl import Playlist
from KugouControl.Playlist import Playback, Scrolling
from KugouControl.Track import TrackFailed
from Tests.TestPlaylistFakes import FakeKugou, FakePlaybackKugou, IsolatedPlaylistTestCase


def songs(count):
    return [(f'歌曲{i:03d}', '歌手') for i in range(count)]


class PlaylistSpeedTests(IsolatedPlaylistTestCase):
    def test_detection_with_53_sidebar_slots_and_13_songs_uses_fewer_wheels_and_waits(self):
        playlists = {f'歌单{i}': songs(13) for i in range(49)}
        # 基线 8e5a924，同一替身、滚轮立即生效；一次 Input.wheel 可发送多格。
        baseline = {(0, 6): (25, 37), (0, 42): (17, 29), (1500, 6): (22, 58), (1500, 42): (22, 58)}
        for (offset, index), (wheels, waits) in baseline.items():
            with self.subTest(offset=offset, index=index):
                ui = FakeKugou(playlists, nav_offset=offset)
                state = ui.run(lambda: Playlist.inspect(1, f'歌单{index}'))
                self.assertTrue(state['complete'])
                self.assertEqual(len(state['tracks']), 13)
                self.assertLess(len(ui.wheels), wheels)
                self.assertLess(len(ui.waits), waits)

    def test_wheel_applied_after_several_polls_is_not_discarded(self):
        ui = FakeKugou({'长歌单': songs(25)}, reuse_song_rows=True)
        ui.open('长歌单')
        polls = 0
        pending = None
        wheel = ui.wheel
        layout = Scrolling._layout

        def enqueue(*args):
            nonlocal pending
            pending = args

        def delayed_layout(collection):
            nonlocal polls
            if pending is not None:
                polls += 1
                if polls == 3:
                    wheel(*pending)
            return layout(collection)

        def exercise():
            scroller = Scrolling._WheelScroll(1, ui.songs)
            with patch.object(Scrolling, '_layout', side_effect=delayed_layout), \
                 patch.object(ui, 'wheel', side_effect=enqueue):
                return scroller.down(), scroller.per_notch

        self.assertEqual(ui.run(exercise), (True, ui.NOTCH))
        self.assertEqual(polls, 4)


class RecycledPlaylistRowsTests(IsolatedPlaylistTestCase):
    def test_121_songs_are_read_in_order_using_only_a_pool_of_recycled_rows(self):
        expected = songs(121)
        ui = FakeKugou({'长歌单': expected}, song_rows=5, reuse_song_rows=True)
        ui.open('长歌单')
        slots = tuple(ui.songs.children())
        first_names = tuple(row.name for row in slots)

        state = ui.run(lambda: Playlist.inspect(1, '长歌单'))

        self.assertTrue(state['complete'])
        self.assertEqual([(row['title'], row['artist']) for row in state['tracks']], expected)
        self.assertEqual(tuple(ui.songs.children()), slots)
        self.assertLess(len(slots), len(expected))
        self.assertNotEqual(tuple(row.name for row in slots), first_names)

    def test_clicks_the_intended_song_near_the_end_after_inspecting_a_long_playlist(self):
        tracks = songs(123)
        target = tracks[115]
        ui = FakePlaybackKugou({'长歌单': tracks}, song_rows=5, reuse_song_rows=True)
        self.assertTrue(ui.run(lambda: Playlist.inspect(1, '长歌单'))['complete'])
        with patch.object(Playback, '_current', side_effect=lambda pid: ui.now), \
             patch('KugouControl.Uia.invalidate'), patch('KugouControl.Uia.read_controls', return_value={'status': 'playing'}):
            ui.run(lambda: Playlist.play_from_playlist(1, 2, '长歌单', *target))
        self.assertEqual(ui.now, target)
        self.assertEqual(sum(click[2] for click in ui.clicks), 1)
        self.assertEqual(ui.play_bar_hits, 0)
        self.assertEqual(ui.artist_hits, 0)

    def test_rewinds_from_an_aligned_bottom_when_provider_only_exposes_visible_rows(self):
        ui = FakeKugou({'长歌单': songs(121)}, reuse_song_rows=True)
        ui.open('长歌单')
        ui.songs.scroll(10000)
        children = ui.songs.children
        view = ui.songs.rectangle

        def visible_children():
            return [row for row in children() if row.visible
                    and view.top < row.rectangle.bottom and row.rectangle.top < view.bottom]

        with patch.object(ui.songs, 'children', side_effect=visible_children):
            state = ui.run(lambda: Playlist.inspect(1, '长歌单'))
        self.assertTrue(state['complete'])
        self.assertEqual(len(state['tracks']), 121)
        self.assertEqual(ui.songs.offset, (121 - ui.song_rows) * ui.songs.row)

    def test_identical_songs_in_distant_viewports_do_not_get_deduplicated_before_playback(self):
        tracks = songs(121)
        tracks[115] = tracks[1]
        ui = FakePlaybackKugou({'长歌单': tracks}, reuse_song_rows=True)
        with patch.object(Playback, '_current', side_effect=lambda pid: ui.now):
            with self.assertRaisesRegex(TrackFailed, '多个同名版本'):
                ui.run(lambda: Playlist.play_from_playlist(1, 2, '长歌单', *tracks[1]))
        self.assertFalse(any(click[2] for click in ui.clicks))

    def test_lost_wheel_after_progress_does_not_prove_the_recycled_playlist_complete(self):
        ui = FakeKugou({'长歌单': songs(121)}, reuse_song_rows=True)
        ui.open('长歌单')
        wheel = ui.wheel

        def lose_wheel(hwnd, x, y, notches):
            if ui.songs.offset < 2 * ui.NOTCH:
                wheel(hwnd, x, y, notches)

        with patch.object(ui, 'wheel', side_effect=lose_wheel):
            state = ui.run(lambda: Playlist.inspect(1, '长歌单'))
        self.assertTrue(state['supported'])
        self.assertFalse(state['complete'])
        self.assertIn('未完整读取', state['note'])
        self.assertGreater(len(state['tracks']), ui.song_rows)
        self.assertLess(len(state['tracks']), 121)

    def test_a_jump_without_an_overlap_does_not_append_disconnected_rows(self):
        ui = FakeKugou({'长歌单': songs(121)}, reuse_song_rows=True)
        ui.open('长歌单')
        def jump_down(hwnd, x, y, notches):
            if notches > 0:
                ui.songs.scroll(500)

        with patch.object(ui, 'wheel', side_effect=jump_down):
            state = ui.run(lambda: Playlist.inspect(1, '长歌单'))
        self.assertFalse(state['complete'])
        self.assertEqual([(row['title'], row['artist']) for row in state['tracks']], songs(ui.song_rows))

    def test_a_stale_small_count_cannot_hide_more_recycled_rows(self):
        ui = FakeKugou({'长歌单': songs(121)}, reuse_song_rows=True)
        page = ui.page

        def stale_page():
            content = page()
            content.children()[1].children()[1].name = '共 12 首歌曲'
            return content

        with patch.object(ui, 'page', side_effect=stale_page):
            state = ui.run(lambda: Playlist.inspect(1, '长歌单'))
        self.assertFalse(state['complete'])
        self.assertGreater(len(state['tracks']), 12)
