"""Bounded Telegram authorization retries during Koyeb startup.

Telegram can answer a cold bot login with a temporary 500/timeout. Koyeb must
not restart the whole instance for every such answer, and a retry must not load
the plugin handlers twice.
"""
import os
import unittest
from unittest.mock import AsyncMock, patch

for key, value in {
    "API_ID": "1", "API_HASH": "test", "BOT_TOKEN": "1:test", "ADMINS": "1",
    "LOG_CHANNEL": "-1001", "BIN_CHANNEL": "-1002",
    "DATABASE_URL": "mongodb://localhost:27017", "URL": "https://example.com",
}.items():
    os.environ.setdefault(key, value)

from bot import Bot


class StartupRetryTests(unittest.IsolatedAsyncioTestCase):
    def _instance(self):
        instance = Bot.__new__(Bot)
        instance.plugins = {"root": "plugins"}
        return instance

    async def test_timeout_is_retried_without_reloading_plugins(self):
        instance = self._instance()
        seen = []

        async def fake_start(client):
            seen.append(client.plugins)
            if len(seen) == 1:
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

    async def test_exhausted_retries_surface_the_transport_error(self):
        instance = self._instance()

        async def always_timeout(client):
            raise TimeoutError("no answer")

        with patch('bot.Client.start', always_timeout), \
                patch('bot.AUTH_RETRY_ATTEMPTS', 2), \
                patch('bot.AUTH_RETRY_DELAY', 0), \
                patch('bot.asyncio.sleep', AsyncMock()):
            with self.assertRaises(TimeoutError):
                await instance._start_telegram()

        self.assertEqual(instance.plugins, {"root": "plugins"})
