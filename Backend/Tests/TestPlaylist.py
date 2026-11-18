"""歌单状态、回退边界与准备试听隔离；所有桌面依赖均使用替身。"""
from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from Database import Database, PlaylistRepository, QueueRepository, SessionRepository, SettingsRepository, SongRepository
from KugouControl import Playlist, Track, Worker
from KugouControl.Adapter import KugouController
from KugouControl.Profiles import PLAYLIST_LAYOUT, exact_track
from Main import create_app
from Player.Base import ControllerTimeout, ControllerTrackLoading, PlayerReading
from Player.Mock import MockPlayerController
from Player.Model import PlayerCommand
from Player.Service import PLAYLIST_KEY, PlayerConflict, PlayerService
from PptControl.Service import PptService
from Tests.TestDiagnostics import FakePptController


class Element:
    def __init__(self, kind, name='', children=(), left=300, top=100):
        self.control_type, self.name = kind, name
        self._children = list(children)
        self.parent = None
        self.visible = True
        self.rectangle = SimpleNamespace(left=left, top=top, right=left + 150, bottom=top + 35)
        for child in self._children:
            child.parent = self

    def children(self):
        return self._children


def row(title, artist):
    return Element('DataItem', children=[Element('Text', title), Element('Text', artist)])


def page(rows, extra=()):
    header = Element('Header', children=[Element('HeaderItem', '歌曲'), Element('HeaderItem', '歌手')])
    grid = Element('DataGrid', children=[header, *rows])
    return Element('Custom', '演出歌单', [grid, *extra]), grid


class PlaylistIdentityTests(unittest.TestCase):
    def test_exact_identity_preserves_versions_and_all_artists(self):
        self.assertTrue(exact_track('晴 天', '周杰伦', '晴天', '周杰伦'))
        self.assertTrue(exact_track('凉凉', '甲、乙', '凉凉', '乙/甲'))
        self.assertFalse(exact_track('晴天 (Live)', '周杰伦', '晴天', '周杰伦'))
        self.assertFalse(exact_track('晴天', '翻唱者', '晴天', '周杰伦'))
        self.assertFalse(exact_track('凉凉', '甲', '凉凉', '甲/乙'))

    def test_scan_does_not_infer_identity_from_an_unlabelled_row(self):
        target, _ = page([Element('DataItem', '歌手 - 歌曲')])
        with patch.object(Playlist, '_pattern', return_value=None):
            tracks, complete, _ = Playlist._scan(target, float('inf'))
        self.assertEqual(tracks, [])
        self.assertFalse(complete)

    def test_scan_virtual_list_reads_the_last_song_and_checks_scroll(self):
        target, grid = page([])
        class Scroll:
            CurrentVerticallyScrollable = True
            CurrentVerticalScrollPercent = 0
            def SetScrollPercent(self, x, value):
                self.CurrentVerticalScrollPercent = value
        scroll = Scroll()
        header = grid._children[0]
        grid.children = lambda: [header, *(row(f'歌曲{scroll.CurrentVerticalScrollPercent}-{i}', '歌手') for i in range(20)),
                                 *([row('末尾歌曲', '歌手')] if scroll.CurrentVerticalScrollPercent == 100 else [])]
        with patch.object(Playlist, '_pattern', return_value=scroll), patch.object(Playlist.time, 'sleep'):
            tracks, complete, _ = Playlist._scan(target, float('inf'))
        self.assertTrue(complete)
        self.assertGreater(len(tracks), 100)
        self.assertIn({'title': '末尾歌曲', 'artist': '歌手'}, tracks)

    def test_scroll_failure_keeps_absent_members_unknown(self):
        target, _ = page([row('一首歌', '歌手')])
        scroll = SimpleNamespace(CurrentVerticallyScrollable=True, CurrentVerticalScrollPercent=50, SetScrollPercent=lambda *args: None)
        with patch.object(Playlist, '_pattern', return_value=scroll), patch.object(Playlist.time, 'sleep'):
            with self.assertRaises(Playlist.PlaylistUnsupported):
                Playlist._scan(target, float('inf'))

    def test_missing_scroll_pattern_with_scrollbar_is_not_complete(self):
        target, grid = page([row('一首歌', '歌手')])
        grid._children.append(Element('ScrollBar'))
        with patch.object(Playlist, '_pattern', return_value=None):
            self.assertFalse(Playlist._scan(target, float('inf'))[1])

    def test_named_page_is_scoped_away_from_sidebar(self):
        target, _ = page([row('歌曲', '歌手')])
        entry = Element('TreeItem', '演出歌单', left=0)
        root = Element('Window', children=[entry, target])
        with patch.object(Playlist, '_root', return_value=root):
            self.assertIs(Playlist.open_playlist(1, '演出歌单'), target)

    def test_probe_never_enables_unmeasured_filter_coordinates(self):
        target = Element('Custom', '演出歌单', [Element('Edit', '歌单内搜索')])
        with patch.object(Playlist, 'open_playlist', return_value=target), patch.object(Playlist, '_set_filter'), \
             patch.dict(PLAYLIST_LAYOUT, first_song=None):
            state = Playlist.inspect(1, '演出歌单')
        self.assertFalse(state['supported'])
        self.assertIn('尚未真机验证', state['note'])


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
        target, _ = page([row('歌曲', '歌手')])
        with patch.object(Playlist, 'open_playlist', return_value=target), \
             patch.object(Playlist, '_set_filter', side_effect=Playlist.PlaylistUnsupported()), \
             patch.object(Playlist, '_pattern', return_value=None), patch.object(Playlist, '_current', return_value=('歌曲', '歌手')), \
             patch.object(Playlist, '_pause') as pause, patch.object(Playlist, '_click'), \
             patch('KugouControl.Uia.invalidate'), patch('KugouControl.Uia.read_controls', return_value={'status': 'paused'}), \
             patch.dict(PLAYLIST_LAYOUT, wait=0.01):
            with self.assertRaises(Track.TrackFailed):
                Playlist.play_from_playlist(1, 2, '演出歌单', '歌曲', '歌手')
            pause.assert_called_once()

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
            raise subprocess.TimeoutExpired(args, kwargs['timeout'])
        controller = KugouController(runner=runner)
        controller.configure_playlist('演出歌单')
        controller._playlist['can_add'] = True
        with self.assertRaisesRegex(ControllerTimeout, '检查并暂停'):
            controller.add_to_playlist({'id': 1, 'title': '歌曲', 'artist': '歌手'})
        self.assertEqual(len(calls), 1)

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
    def run_add(self, state, *, now=('歌曲', '歌手'), playback_error=None, invoke_error=None):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(Playlist, 'inspect', return_value=state))
        stack.enter_context(patch.object(Playlist, 'inspect_add', side_effect=lambda *args: args[-1]))
        stack.enter_context(patch.object(Playlist.Input, 'press'))
        stack.enter_context(patch.object(Playlist, '_current', return_value=now))
        stack.enter_context(patch.object(Playlist, '_destination', return_value=object()))
        search = stack.enter_context(patch.object(Track, '_play_search'))
        play = stack.enter_context(patch.object(Playlist, 'play_from_playlist', side_effect=playback_error))
        invoke = stack.enter_context(patch.object(Playlist, '_invoke', side_effect=invoke_error))
        pause = stack.enter_context(patch.object(Playlist, '_pause'))
        result = Playlist.add_to_playlist(1, 2, '演出歌单', '歌曲', '歌手')
        return result, search, play, invoke, pause

    def test_present_song_does_not_audition_or_add(self):
        result, search, play, invoke, pause = self.run_add({'can_add': True, 'complete': True,
            'tracks': [{'title': '歌曲', 'artist': '歌手'}]})
        self.assertEqual(result['status'], 'already_present')
        search.assert_not_called()
        invoke.assert_not_called()

    def test_exact_version_is_required_before_adding(self):
        result, search, play, invoke, pause = self.run_add({'can_add': True, 'complete': True, 'tracks': []}, now=('歌曲 (Live)', '歌手'))
        self.assertEqual(result['status'], 'unverified')
        invoke.assert_not_called()
        pause.assert_called_once()

    def test_click_without_membership_verification_is_unverified(self):
        result, search, play, invoke, pause = self.run_add({'can_add': True, 'complete': True, 'tracks': []},
            playback_error=Playlist.PlaylistMiss('添加后歌单仍无此歌'))
        self.assertEqual(result['status'], 'unverified')
        self.assertIsNone(result['in_playlist'])
        invoke.assert_called_once()
        pause.assert_called_once()

    def test_success_requires_a_second_play_from_playlist(self):
        result, search, play, invoke, pause = self.run_add({'can_add': True, 'complete': True, 'tracks': []})
        self.assertEqual(result['status'], 'added')
        search.assert_called_once()
        play.assert_called_once()
        invoke.assert_called_once()
        pause.assert_called_once()

    def test_menu_failure_is_not_retried(self):
        result, search, play, invoke, pause = self.run_add({'can_add': True, 'complete': True, 'tracks': []},
            invoke_error=Playlist.PlaylistUnsupported('菜单不可用'))
        self.assertEqual(result['status'], 'unverified')
        invoke.assert_called_once()
        play.assert_not_called()

    def test_incomplete_membership_audition_failure_still_pauses(self):
        result, search, play, invoke, pause = self.run_add({'can_add': True, 'complete': False, 'tracks': []},
            playback_error=Track.TrackFailed('歌单试播版本不符'))
        self.assertEqual(result['status'], 'unverified')
        search.assert_not_called()
        invoke.assert_not_called()
        pause.assert_called_once()


class FakePlaylistController(MockPlayerController):
    name = 'kugou'

    def __init__(self):
        super().__init__()
        self.configured = ''
        self.result = {'status': 'added', 'message': '已加入并核验', 'in_playlist': True}
        self.play_result = {}
        self.loading = False

    def configure_playlist(self, name):
        self.configured = name

    def playlist_snapshot(self):
        return {'name': self.configured, 'route': 'A', 'supported': True, 'can_add': True,
                'complete': False, 'tracks': [{'title': '晴天', 'artist': '周杰伦'}], 'note': 'test'}

    def refresh_playlist(self):
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

    async def test_concurrent_add_is_rejected_without_replay(self):
        async with self.service._lock:
            with self.assertRaisesRegex(PlayerConflict, '其他操作'):
                await self.service.add_to_playlist(1)


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
