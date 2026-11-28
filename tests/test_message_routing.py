"""Private admin messages must reach the handler the user expects.

Pyrogram stops walking a handler group as soon as one handler matches and
returns.  A catch-all helper that quietly returns would therefore swallow
/start and plain searches; these tests pin the ContinuePropagation contract.
"""
import importlib.util
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

for key, value in {
    'API_ID': '1', 'API_HASH': 'test', 'BOT_TOKEN': '1:test', 'ADMINS': '1',
    'LOG_CHANNEL': '-1001', 'BIN_CHANNEL': '-1002',
    'DATABASE_URL': 'mongodb://localhost:27017', 'URL': 'https://example.com',
    'UPI_ID': 'test@upi', 'UPI_NAME': 'Test Merchant', 'RECEIPT_SEND_USERNAME': '@admin',
}.items():
    os.environ.setdefault(key, value)

from pyrogram import ContinuePropagation, enums
from pyrogram.handlers import MessageHandler
from pyrogram.types import Chat, Message

from bot import Bot
from plugins import commands, index
from plugins import filter as filter_plugin
from utils import temp

HAS_CHECK_DB_TEMP = importlib.util.find_spec('plugins.temp.check_db_TEMP') is not None
if HAS_CHECK_DB_TEMP:
    from plugins.temp import check_db_TEMP


def _message(text, command=None):
    user = SimpleNamespace(id=1, first_name='Admin', mention='Admin', is_bot=False)
    return Message(
        id=1,
        chat=Chat(id=1, type=enums.ChatType.PRIVATE),
        from_user=user,
        text=text,
        command=command or [],
        outgoing=False,
    )


class CatchAllHelperTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(HAS_CHECK_DB_TEMP, 'plugins/temp/check_db_TEMP.py was removed')
    async def test_db_migration_helper_releases_unrelated_admin_text(self):
        check_db_TEMP.PENDING.clear()
        with self.assertRaises(ContinuePropagation):
            await check_db_TEMP.receive_new_url(None, _message('Hello'))

    @unittest.skipUnless(HAS_CHECK_DB_TEMP, 'plugins/temp/check_db_TEMP.py was removed')
    async def test_db_migration_helper_releases_new_commands(self):
        check_db_TEMP.PENDING[1] = {'action': 'copy_db', 'collection': None}
        try:
            with self.assertRaises(ContinuePropagation):
                await check_db_TEMP.receive_new_url(None, _message('/start', ['start']))
        finally:
            check_db_TEMP.PENDING.clear()

    async def test_index_helper_releases_ordinary_admin_text(self):
        with self.assertRaises(ContinuePropagation):
            await index.auto_index(None, _message('Hello'))

    async def test_search_helper_releases_invalid_search_text(self):
        with self.assertRaises(ContinuePropagation):
            await filter_plugin.pm_search(None, _message('/start', ['start']))


class AdminStartRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_survives_earlier_admin_text_handlers(self):
        """Walk group 0 exactly like the dispatcher and require a real /start reply."""
        client = Bot()
        client.load_plugins()
        client.me = SimpleNamespace(id=1, username='testbot', first_name='Bot', mention='@testbot')
        temp.U_NAME = 'testbot'

        message = _message('/start', ['start'])
        message.react = AsyncMock()
        message.reply_photo = AsyncMock()

        fake_db = SimpleNamespace(
            is_user_exist=AsyncMock(return_value=True),
            add_user=AsyncMock(),
            get_chat=AsyncMock(return_value=True),
        )
        with patch.object(commands, 'db', fake_db), \
                patch.object(commands, 'REACTIONS', []), \
                patch.object(commands, 'IS_PREMIUM', False):
            for handler in client.dispatcher.groups[0]:
                if not isinstance(handler, MessageHandler):
                    continue
                if not await handler.check(client, message):
                    continue
                try:
                    await handler.callback(client, message)
                except ContinuePropagation:
                    continue
                break

        self.assertEqual(message.reply_photo.await_count, 1)


if __name__ == '__main__':
    unittest.main()
