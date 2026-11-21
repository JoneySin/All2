"""Quality/series group shortcuts on file cards."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

for key, value in {
    'API_ID': '1', 'API_HASH': 'test', 'BOT_TOKEN': '1:test', 'ADMINS': '1',
    'LOG_CHANNEL': '-1001', 'BIN_CHANNEL': '-1002',
    'DATABASE_URL': 'mongodb://localhost:27017', 'URL': 'https://example.com',
}.items():
    os.environ.setdefault(key, value)

from pyrogram import enums
from plugins import commands
from utils import temp


def group(members, kind='quality', order=None):
    return {'_id': '7', 'name': 'Film', 'members': members,
            'group_type': kind, 'episode_order': order or []}


def files(*ids):
    return [{'_id': fid, 'file_name': f'{fid}.mkv', 'file_size': 10,
             'file_ref': f'ref-{fid}'} for fid in ids]


class GroupSendTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        commands._GROUP_SEND_ACTIVE.clear()
        temp.SEND_ALL_ENABLED = True

    def tearDown(self):
        commands._GROUP_SEND_ACTIVE.clear()
        temp.SEND_ALL_ENABLED = True

    async def test_quality_group_sends_every_member(self):
        client = SimpleNamespace(
            send_cached_media=AsyncMock(side_effect=[SimpleNamespace(id=i) for i in range(3)]),
            send_message=AsyncMock(),
        )
        query = SimpleNamespace(
            data='grp#7', from_user=SimpleNamespace(id=5),
            message=SimpleNamespace(chat=SimpleNamespace(id=5)), answer=AsyncMock(),
        )
        with patch.object(commands, 'IS_PREMIUM', False), \
                patch.object(commands, 'PM_FILE_DELETE_TIME', 0), \
                patch.object(commands, 'get_groups_by_ids', AsyncMock(return_value=[group(['a', 'b', 'c'])])), \
                patch.object(commands, 'get_files_by_ids', AsyncMock(return_value=files('a', 'b', 'c'))), \
                patch.object(commands, 'get_settings', AsyncMock(return_value={'caption': '{file_name}'})):
            await commands.send_group_files(client, query)

        self.assertEqual(client.send_cached_media.await_count, 3)
        query.answer.assert_awaited_once()
        self.assertEqual(client.send_cached_media.await_args_list[0].args[0], 5)

    async def test_series_group_follows_episode_order(self):
        client = SimpleNamespace(
            send_cached_media=AsyncMock(side_effect=[SimpleNamespace(id=1), SimpleNamespace(id=2)]),
            send_message=AsyncMock(),
        )
        query = SimpleNamespace(
            data='grp#7', from_user=SimpleNamespace(id=5),
            message=SimpleNamespace(chat=SimpleNamespace(id=5)), answer=AsyncMock(),
        )
        with patch.object(commands, 'IS_PREMIUM', False), \
                patch.object(commands, 'PM_FILE_DELETE_TIME', 0), \
                patch.object(commands, 'get_groups_by_ids',
                             AsyncMock(return_value=[group(['b', 'a'], 'series', ['a', 'b'])])), \
                patch.object(commands, 'get_files_by_ids', AsyncMock(return_value=files('a', 'b'))), \
                patch.object(commands, 'get_settings', AsyncMock(return_value={'caption': '{file_name}'})):
            await commands.send_group_files(client, query)

        self.assertEqual([call.args[1] for call in client.send_cached_media.await_args_list],
                         ['ref-a', 'ref-b'])

    def test_group_button_is_green_and_skips_single_member(self):
        row = commands._group_button(group(['a', 'b'], 'series', ['a', 'b']))
        self.assertEqual(row[0].callback_data, 'grp#7')
        self.assertEqual(row[0].text, '⚡Send All 2 Episode')
        self.assertIsNone(commands._group_button(group(['a'])))

    async def test_start_file_card_gets_the_group_button(self):
        client = SimpleNamespace(send_cached_media=AsyncMock(return_value=SimpleNamespace(id=9)))
        message = SimpleNamespace(
            command=['start', 'file_5_a'],
            chat=SimpleNamespace(id=5, type=enums.ChatType.PRIVATE),
            from_user=SimpleNamespace(id=5, mention='Admin'),
            delete=AsyncMock(),
        )
        file = {'_id': 'a', 'file_name': 'Film 720p.mkv', 'file_size': 10,
                'file_ref': 'ref-a', 'group_id': '7'}
        with patch.object(commands, 'db', SimpleNamespace(is_user_exist=AsyncMock(return_value=True))), \
                patch.object(commands, 'IS_PREMIUM', False), \
                patch.object(commands, 'REACTIONS', []), \
                patch.object(commands, 'PM_FILE_DELETE_TIME', 0), \
                patch.object(commands, 'get_file_details', AsyncMock(return_value=file)), \
                patch.object(commands, 'get_group_for_file',
                             AsyncMock(return_value=group(['a', 'b']))), \
                patch.object(commands, 'get_settings', AsyncMock(return_value={'caption': '{file_name}'})):
            await commands.start(client, message)

        markup = client.send_cached_media.await_args.kwargs['reply_markup']
        self.assertEqual(markup.inline_keyboard[0][0].callback_data, 'grp#7')
        self.assertEqual(markup.inline_keyboard[0][0].text, '♻️Send All 2 Quality')

    async def test_admin_toggle_persists_and_updates_runtime(self):
        message = SimpleNamespace(
            command=['sendall', 'off'],
            reply=AsyncMock(),
        )
        with patch.object(commands, 'db', SimpleNamespace(set_send_all_enabled=AsyncMock())):
            await commands.send_all_toggle(None, message)
        self.assertFalse(temp.SEND_ALL_ENABLED)
        message.reply.assert_awaited_once()
        self.assertIn('OFF', message.reply.await_args.args[0])

        message.command = ['sendall', 'on']
        with patch.object(commands, 'db', SimpleNamespace(set_send_all_enabled=AsyncMock())):
            await commands.send_all_toggle(None, message)
        self.assertTrue(temp.SEND_ALL_ENABLED)

    async def test_disabled_feature_hides_button_and_rejects_old_callbacks(self):
        temp.SEND_ALL_ENABLED = False
        client = SimpleNamespace(
            send_cached_media=AsyncMock(return_value=SimpleNamespace(id=9)),
            send_message=AsyncMock(),
        )
        message = SimpleNamespace(
            command=['start', 'file_5_a'],
            chat=SimpleNamespace(id=5, type=enums.ChatType.PRIVATE),
            from_user=SimpleNamespace(id=5, mention='Admin'),
            delete=AsyncMock(),
        )
        file = {'_id': 'a', 'file_name': 'Film 720p.mkv', 'file_size': 10,
                'file_ref': 'ref-a', 'group_id': '7'}
        with patch.object(commands, 'db', SimpleNamespace(is_user_exist=AsyncMock(return_value=True))), \
                patch.object(commands, 'IS_PREMIUM', False), \
                patch.object(commands, 'REACTIONS', []), \
                patch.object(commands, 'PM_FILE_DELETE_TIME', 0), \
                patch.object(commands, 'get_file_details', AsyncMock(return_value=file)), \
                patch.object(commands, 'get_settings', AsyncMock(return_value={'caption': '{file_name}'})):
            await commands.start(client, message)

        markup = client.send_cached_media.await_args.kwargs['reply_markup']
        callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
        self.assertNotIn('grp#7', callbacks)

        query = SimpleNamespace(
            data='grp#7', from_user=SimpleNamespace(id=5),
            message=SimpleNamespace(chat=SimpleNamespace(id=5)), answer=AsyncMock(),
        )
        await commands.send_group_files(client, query)
        query.answer.assert_awaited_once()
        self.assertIn('turned off', query.answer.await_args.args[0])
        self.assertEqual(client.send_cached_media.await_count, 1)  # only the /start card

    async def test_watch_card_does_not_reintroduce_group_button(self):
        client = SimpleNamespace(
            send_cached_media=AsyncMock(return_value=SimpleNamespace(id=99)),
            edit_reply_markup=AsyncMock(),
        )
        message = SimpleNamespace(chat=SimpleNamespace(id=5), id=9,
                                  edit_reply_markup=AsyncMock())
        query = SimpleNamespace(
            data='stream#a', from_user=SimpleNamespace(id=5), message=message,
            answer=AsyncMock(),
        )
        file = {'_id': 'a', 'file_name': 'Film.mkv', 'file_ref': 'ref-a', 'group_id': '7'}
        with patch.object(commands, 'get_file_details', AsyncMock(return_value=file)), \
                patch.object(commands, 'db', SimpleNamespace(add_to_delete_queue=AsyncMock())), \
                patch.object(commands, 'STREAM_TTL', 10):
            await commands.stream_cb(client, query)
        markup = message.edit_reply_markup.await_args.args[0]
        callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
        self.assertFalse(any(str(cb).startswith('grp#') for cb in callbacks))


if __name__ == '__main__':
    unittest.main()
