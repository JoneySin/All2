"""Telegram authorization retries during Koyeb startup.

Telegram can answer a cold bot login with a temporary 500/timeout. Koyeb must
not restart the whole instance for every such answer, and a retry must not load
the plugin handlers twice. The web port stays healthy and retries until the
client is actually authorized.
"""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

for key, value in {
    "API_ID": "1", "API_HASH": "test", "BOT_TOKEN": "1:test", "ADMINS": "1",
    "LOG_CHANNEL": "-1001", "BIN_CHANNEL": "-1002",
    "DATABASE_URL": "mongodb://localhost:27017", "URL": "https://example.com",
    "UPI_ID": "test@upi", "UPI_NAME": "Test Merchant", "RECEIPT_SEND_USERNAME": "@admin",
}.items():
    os.environ.setdefault(key, value)

from bot import Bot
from utils import temp


class StartupRetryTests(unittest.IsolatedAsyncioTestCase):
    def _instance(self):
        instance = Bot.__new__(Bot)
        instance.plugins = {"root": "plugins"}
        instance.dispatcher = SimpleNamespace(groups={})
        return instance

    async def test_timeout_is_retried_without_reloading_plugins(self):
        instance = self._instance()
        seen = []

        async def fake_start(client):
            seen.append(client.plugins)
            if len(seen) == 1:
                # Kurigram's load_plugins() runs before authorize(), so handlers
                # already exist when the failed auth attempt returns.
                client.dispatcher.groups = {0: [object()]}
                raise TimeoutError('Failed to invoke "auth.ImportBotAuthorization"')
            return client

        with patch('bot.Client.start', fake_start), \
                patch('bot.AUTH_RETRY_ATTEMPTS', 2), \
                patch('bot.AUTH_RETRY_DELAY', 0), \
                patch('bot.asyncio.sleep', AsyncMock()):
            await instance._start_telegram()

        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0], {"root": "plugins"})
        self.assertIsNone(seen[1])
        self.assertEqual(instance.plugins, {"root": "plugins"})

    async def test_retry_reloads_plugins_if_failure_happened_before_loading(self):
        instance = self._instance()
        seen = []

        async def fake_start(client):
            seen.append(client.plugins)
            if len(seen) == 1:
                raise TimeoutError("connect failed before plugins loaded")
            return client

        with patch('bot.Client.start', fake_start), \
                patch('bot.AUTH_RETRY_ATTEMPTS', 2), \
                patch('bot.AUTH_RETRY_DELAY', 0), \
                patch('bot.asyncio.sleep', AsyncMock()):
            await instance._start_telegram()

        self.assertEqual(seen[0], {"root": "plugins"})
        self.assertEqual(seen[1], {"root": "plugins"})

    async def test_transport_failures_keep_retrying_until_telegram_recovers(self):
        instance = self._instance()
        calls = 0

        async def flaky_start(client):
            nonlocal calls
            calls += 1
            if calls < 4:
                raise TimeoutError("no answer")
            return client

        with patch('bot.Client.start', flaky_start), \
                patch('bot.AUTH_RETRY_ATTEMPTS', 2), \
                patch('bot.AUTH_RETRY_DELAY', 0), \
                patch('bot.asyncio.sleep', AsyncMock()), \
                patch.object(temp, 'BOT', None), \
                patch.object(temp, 'BOT_READY', False):
            await instance._start_telegram()
            self.assertIs(temp.BOT, instance)
            self.assertTrue(temp.BOT_READY)

        self.assertEqual(calls, 4)
        self.assertEqual(instance.plugins, {"root": "plugins"})

    async def test_stop_is_idempotent_and_safe_before_connected(self):
        instance = self._instance()
        instance._runner = None
        instance._premium_task = None
        instance._delete_task = None
        instance.is_connected = False
        with patch('bot.stop_group_scan', AsyncMock()), \
                patch('bot.Client.stop', AsyncMock()) as client_stop:
            await instance.stop()
            await instance.stop()
        client_stop.assert_not_awaited()

    async def test_mongo_session_saves_reloads_and_recovers_if_revoked(self):
        from pathlib import Path
        from pyrogram.errors import AuthKeyUnregistered

        stored = {}

        async def fake_get(_tok):
            return stored.get("s", "")

        async def fake_save(_tok, val):
            stored["s"] = val
            return True

        async def fake_del(_tok):
            stored.pop("s", None)

        fake_db = SimpleNamespace(
            get_bot_session=AsyncMock(side_effect=fake_get),
            save_bot_session=AsyncMock(side_effect=fake_save),
            delete_bot_session=AsyncMock(side_effect=fake_del),
        )

        # 1) First boot: no saved session -> start exports and stores in MongoDB
        inst1 = self._instance()
        inst1.name = "Auto_Filter_Bot"
        inst1.workdir = Path(".")
        inst1._use_mongo_session = True
        inst1.export_session_string = AsyncMock(return_value="exported-sess-1")
        with patch('bot.db', fake_db), \
                patch('bot.Client.start', AsyncMock(return_value=inst1)), \
                patch.object(temp, 'BOT', None), \
                patch.object(temp, 'BOT_READY', False):
            await inst1._start_telegram()
        self.assertEqual(stored["s"], "exported-sess-1")
        fake_db.save_bot_session.assert_awaited_once()

        # 2) Second boot: loads saved session from MongoDB
        inst2 = self._instance()
        inst2.name = "Auto_Filter_Bot"
        inst2.workdir = Path(".")
        inst2._use_mongo_session = True
        inst2.export_session_string = AsyncMock(return_value="should-not-export")
        with patch('bot.db', fake_db), \
                patch('bot.Client.start', AsyncMock(return_value=inst2)), \
                patch.object(temp, 'BOT', None), \
                patch.object(temp, 'BOT_READY', False):
            await inst2._start_telegram()
        self.assertEqual(inst2.session_string, "exported-sess-1")
        self.assertEqual(inst2.storage.session_string, "exported-sess-1")
        inst2.export_session_string.assert_not_awaited()

        # 3) Revoked saved session: deletes stale entry, clears storage, retries and saves new session
        inst3 = self._instance()
        inst3.name = "Auto_Filter_Bot"
        inst3.workdir = Path(".")
        inst3._use_mongo_session = True
        inst3.export_session_string = AsyncMock(return_value="fresh-sess-2")
        attempts = 0

        async def revoked_then_ok(client):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise AuthKeyUnregistered()
            return client

        with patch('bot.db', fake_db), \
                patch('bot.Client.start', revoked_then_ok), \
                patch.object(temp, 'BOT', None), \
                patch.object(temp, 'BOT_READY', False):
            await inst3._start_telegram()
        self.assertEqual(attempts, 2)
        self.assertEqual(stored["s"], "fresh-sess-2")
        fake_db.delete_bot_session.assert_awaited_once()
