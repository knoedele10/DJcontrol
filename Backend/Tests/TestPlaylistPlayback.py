"""歌单点播、搜索回退和控制器路由测试。"""
from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

from KugouControl import Playlist, Track, Worker
from KugouControl.Adapter import KugouController
from KugouControl.Playlist import Playback
from KugouControl.Profiles import PLAYLIST_ADD_TIMEOUT, PLAYLIST_LAYOUT
from Player.Base import CapabilityUnsupported, ControllerTimeout, PlayerUnavailable
from Tests.TestPlaylistFakes import FakePlaybackKugou, IsolatedPlaylistTestCase


class PlaylistClickSafetyTests(IsolatedPlaylistTestCase):
    def test_partial_scan_with_possible_same_name_version_does_not_fall_back_to_search(self):
        ui = FakePlaybackKugou({'演出歌单': [('歌曲', '歌手'), ('加载中', '其他')]})
        ui.open('演出歌单')
        ui.songs.names[1] = '<a 加载中>加载中</a>，歌手:其他'
        ui.songs.layout()
        with patch.object(Playback, '_current', side_effect=lambda pid: ui.now):
            with self.assertRaisesRegex(Playlist.TrackFailed, '无法确认目标歌曲是否有多个版本'):
                ui.run(lambda: Playlist.play_from_playlist(1, 2, '演出歌单', '歌曲', '歌手'))
        self.assertFalse(any(double for _, _, double in ui.clicks))

    def test_double_click_lands_right_of_the_duration_not_on_the_artist_link(self):
        # 真机：行中点落在「Toby Fox」歌手链接上，双击跳到了歌手页。
        ui = FakePlaybackKugou({'演出歌单': [('Finale', 'Toby Fox')]})
        with patch.object(Playback, '_current', side_effect=lambda pid: ui.now), \
             patch('KugouControl.Uia.invalidate'), patch('KugouControl.Uia.read_controls', return_value={'status': 'playing'}):
            ui.run(lambda: Playlist.play_from_playlist(1, 2, '演出歌单', 'Finale', 'Toby Fox'))
        self.assertEqual((ui.now, ui.artist_hits), (('Finale', 'Toby Fox'), 0))
        row = ui.songs.rectangle
        self.assertGreater(ui.clicks[-1][0], row.left + 0.9 * (row.right - row.left))

    def test_row_click_uses_actual_playback_bar_boundary(self):
        songs = [(f'歌曲{i}', '歌手') for i in range(4)]
        ui = FakePlaybackKugou({'演出歌单': songs}, song_rows=4)
        ui.PLAY_BAR = 15
        with patch.object(Playback, '_current', side_effect=lambda pid: ui.now), \
             patch('KugouControl.Uia.invalidate'), patch('KugouControl.Uia.read_controls', return_value={'status': 'playing'}):
            ui.run(lambda: Playlist.play_from_playlist(1, 2, '演出歌单', '歌曲3', '歌手'))
        self.assertEqual(ui.now, ('歌曲3', '歌手'))
        self.assertEqual(ui.clicks[-1][1], round(ui.songs.rectangle.bottom - (40 + ui.PLAY_BAR) / 2))
        self.assertFalse(ui.play_bar_hits)

    def test_pause_followed_by_page_change_stops_before_double_click(self):
        ui = FakePlaybackKugou({'演出歌单': [('歌曲', '歌手')], '另一歌单': [('别的歌', '歌手')]})
        ui.now = ('歌曲', '歌手')
        with patch.object(Playback, '_current', side_effect=lambda pid: ui.now), \
             patch.object(Playback, '_pause', side_effect=lambda *args: ui.open('另一歌单')) as pause, \
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

        with patch.object(Playback, '_current', side_effect=lambda pid: ui.now), \
             patch.object(Playback, '_pause', side_effect=replace), patch('KugouControl.Uia.invalidate'):
            with self.assertRaisesRegex(Playlist.PlaylistUnsupported, '重新确认目标歌曲行'):
                ui.run(lambda: Playlist.play_from_playlist(1, 2, '演出歌单', '歌曲', '歌手'))
        self.assertFalse(any(double for _, _, double in ui.clicks))


class PlaylistRoutingTests(IsolatedPlaylistTestCase):
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
        with patch.object(Playback, '_current', side_effect=lambda pid: ui.now), patch.object(Playback, '_pause') as pause, \
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
