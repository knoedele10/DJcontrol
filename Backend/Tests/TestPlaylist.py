"""歌单成员存储、服务和 API 测试。"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from Database import Database, PlaylistRepository, QueueRepository, SessionRepository, SettingsRepository, SongRepository
from Main import create_app
from Player.Base import ControllerTrackLoading, PlayerReading, PlayerUnavailable
from Player.Mock import MockPlayerController
from Player.Model import PlayerCommand
from Player.Service import PLAYLIST_KEY, PlayerConflict, PlayerDisconnected, PlayerService
from PptControl.Service import PptService
from Tests.TestDiagnostics import FakePptController


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
