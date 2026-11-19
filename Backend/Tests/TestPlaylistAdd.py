"""加歌对话框与试听、确认、核验流程测试。"""
from __future__ import annotations

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from KugouControl import Playlist, Track
from KugouControl.Playlist import Add, Navigation
from Tests.TestPlaylistFakes import Element, FakeKugou, IsolatedPlaylistTestCase, VirtualList


class PlaylistAddDialogTests(IsolatedPlaylistTestCase):
    def test_add_dialog_only_accepts_the_exact_playlist_name(self):
        # 加歌对话框里只认完全同名：包含匹配可能把歌加进别的歌单。
        ui = FakeKugou({'总结环节Lucy老师': [('歌', '人')], '游戏环节': [('歌', '人')]})
        with self.assertRaisesRegex(Playlist.PlaylistUnsupported, '找不到名为「总结环节」的歌单'):
            ui.run(lambda: Navigation._find_entry(1, ui.nav, '总结环节', float('inf'), exact_only=True))
        item, full = ui.run(lambda: Navigation._find_entry(1, ui.nav, '游戏环节', float('inf'), exact_only=True))
        self.assertEqual((item.name, full), ('游戏环节', '游戏环节'))

    def test_hidden_group_header_in_the_add_dialog_does_not_block_an_exact_match(self):
        # 真机：「选择位置」第 0 项是始终隐藏、读不到名字的「我的音乐」，只要求「自建歌单」之后的歌单都读到。
        ui = FakeKugou({})
        ui.nav = VirtualList('选择位置', [None, '默认列表', '我喜欢', '自建歌单', '默认收藏',
                                           *(f'歌单{i}' for i in range(30))], left=0, top=100, width=200, height=300, row=50)
        ui.nav.scroll(600)
        item, full = ui.run(lambda: Navigation._find_entry(1, ui.nav, '默认收藏', float('inf'), exact_only=True))
        self.assertEqual((item.name, full), ('默认收藏', '默认收藏'))

    def test_probe_reports_the_dialog_result_and_always_cancels(self):
        state = {'name': '演出歌单', 'supported': True, 'complete': True, 'can_add': False, 'add_note': ''}
        with patch.object(Add, '_process_windows', return_value=[]), \
             patch.object(Add, '_destination') as destination, patch.object(Add, '_dismiss') as dismiss:
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
        with patch.object(Add, '_process_windows') as windows:
            result = Playlist.inspect_add(1, 2, state)
        self.assertFalse(result['can_add'])
        self.assertIn('排除重复添加', result['add_note'])
        windows.assert_not_called()

    def test_confirm_rechecks_the_fresh_selection_before_clicking(self):
        places = VirtualList('选择位置', ['演出歌单', '另一歌单'], left=0, top=50, width=210, height=100, row=40)
        dialog = Element('Window', '添加到', [places, Element('Button', '确定')])
        pattern = lambda element, name: (SimpleNamespace(CurrentIsSelected=element.name == '另一歌单')
                                         if name == 'SelectionItem' else None)
        with patch.object(Add, '_root', return_value=dialog), patch.object(Add, '_pattern', side_effect=pattern), \
             patch.object(Add, '_process_windows', return_value=[3]), patch('win32gui.GetWindowText', return_value='添加到'), \
             patch.object(Add, '_click') as click:
            with self.assertRaisesRegex(Playlist.PlaylistUnsupported, '无法确认唯一选中'):
                Add._confirm((2, 3, '演出歌单', 0, 2), float('inf'), check_source=MagicMock(), mark_committed=MagicMock())
        click.assert_not_called()

    def test_confirm_does_not_click_when_post_commit_budget_has_elapsed(self):
        dialog = Element('Window', '添加到', [Element('List', '选择位置'), Element('Button', '确定')])
        attempted = MagicMock()
        with patch.object(Add, '_root', return_value=dialog), \
             patch.object(Add, '_selected_destination', return_value=True), \
             patch.object(Add, '_process_windows', return_value=[3]), patch('win32gui.GetWindowText', return_value='添加到'), \
             patch.object(Add, '_click') as click:
            with self.assertRaisesRegex(Playlist.PlaylistUnsupported, '核验时间不足'):
                Add._confirm((2, 3, '演出歌单', 0, 2), 0, check_source=MagicMock(), mark_committed=attempted)
        click.assert_not_called()
        attempted.assert_not_called()

    def test_confirmation_refuses_a_replaced_add_window(self):
        with patch.object(Add, '_process_windows', return_value=[4]), patch.object(Add, '_click') as click:
            with self.assertRaisesRegex(Playlist.PlaylistUnsupported, '对话框不再有效'):
                Add._confirm((2, 3, '演出歌单', 0, 2), float('inf'),
                                  check_source=MagicMock(), mark_committed=MagicMock())
        click.assert_not_called()

    def test_dismiss_only_closes_observed_add_windows(self):
        titles = {1: '酷狗音乐', 3: '更多', 4: '添加到', 5: '下载', 6: '添加到'}
        with patch.object(Add, '_process_windows', side_effect=[list(titles), [1, 5, 6]]), \
             patch('win32gui.GetWindowText', side_effect=titles.get), \
             patch.object(Add.Input, 'press') as press:
            Add._dismiss(2, {3: '更多', 4: '添加到', 5: '添加到'})
        self.assertCountEqual([call.args[0] for call in press.call_args_list], [3, 4])


class PlaylistAddTests(IsolatedPlaylistTestCase):
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
            scan = stack.enter_context(patch.object(Add, 'inspect', side_effect=inspect))
            stack.enter_context(patch.object(Add, '_current', side_effect=lambda pid: live.now))
            menu = stack.enter_context(patch.object(Add, '_destination', side_effect=destination))
            stack.enter_context(patch.object(Add, '_process_windows', return_value=[]))
            stack.enter_context(patch.object(Add, '_dismiss', side_effect=dismiss_error))
            stack.enter_context(patch.object(Add.time, 'monotonic', side_effect=lambda: live.clock))
            stack.enter_context(patch('KugouControl.Uia.invalidate'))
            stack.enter_context(patch('KugouControl.Uia.read_controls',
                                      side_effect=lambda hwnd: {'status': 'playing', 'duration': live.duration}))
            auditioned = stack.enter_context(patch.object(Track, '_play_search', side_effect=search))
            play = stack.enter_context(patch.object(Add, 'play_from_playlist', create=True))
            invoke = stack.enter_context(patch.object(Add, '_confirm', side_effect=confirm))
            pause = stack.enter_context(patch.object(Add, '_pause'))
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
