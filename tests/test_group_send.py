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


def group(members, kind='quality', order=None):
    return {'_id': '7', 'name': 'Film', 'members': members,
            'group_type': kind, 'episode_order': order or []}


def files(*ids):
    return [{'_id': fid, 'file_name': f'{fid}.mkv', 'file_size': 10,
             'file_ref': f'ref-{fid}'} for fid in ids]


class GroupSendTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        commands._GROUP_SEND_ACTIVE.clear()

    def tearDown(self):
        commands._GROUP_SEND_ACTIVE.clear()

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
        self.assertEqual(row[0].text, '📺 Send All Episodes (2)')
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
        self.assertEqual(markup.inline_keyboard[0][0].text, '🎬 Send All Qualities (2)')


if __name__ == '__main__':
    unittest.main()
