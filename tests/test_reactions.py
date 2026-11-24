"""REACTIONS must be parsed once and used on /start and real searches."""
import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

for key, value in {
    "API_ID": "1", "API_HASH": "test", "BOT_TOKEN": "1:test", "ADMINS": "1",
    "LOG_CHANNEL": "-1001", "BIN_CHANNEL": "-1002",
    "DATABASE_URL": "mongodb://localhost:27017", "URL": "https://example.com",
}.items():
    os.environ.setdefault(key, value)

from info import parse_reactions
from plugins import filter as bot_filter
from utils import react_to_message


class ReactionConfigTests(unittest.TestCase):
    def test_accepts_spaces_commas_and_removes_duplicates(self):
        self.assertEqual(parse_reactions("👍, ❤️  🔥 👍"), ["👍", "❤️", "🔥"])

    def test_blank_value_disables_reactions(self):
        self.assertEqual(parse_reactions(""), [])
        self.assertEqual(parse_reactions(" ,  "), [])


class FakeMessage:
    def __init__(self, fail=False, missing=False):
        self.calls = []
        self.fail = fail
        if not missing:
            async def react(emoji, big=False):
                if self.fail:
                    raise RuntimeError("REACTION_INVALID")
                self.calls.append((emoji, big))
                return True
            self.react = react


class ReactionSendTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_one_configured_reaction(self):
        message = FakeMessage()
        with patch("utils.random.choice", return_value="🔥"):
            self.assertTrue(await react_to_message(message, ["👍", "🔥"], big=True))
        self.assertEqual(message.calls, [("🔥", True)])

    async def test_empty_config_or_missing_api_is_safe(self):
        message = FakeMessage()
        self.assertFalse(await react_to_message(message, []))
        self.assertFalse(await react_to_message(FakeMessage(missing=True), ["👍"]))
        self.assertEqual(message.calls, [])

    async def test_telegram_error_never_breaks_the_handler(self):
        message = FakeMessage(fail=True)
        self.assertFalse(await react_to_message(message, ["👍"]))
        self.assertEqual(message.calls, [])

    async def test_real_search_acknowledges_with_a_reaction(self):
        message = SimpleNamespace(
            text="Avengers", react=AsyncMock(return_value=True),
            chat=SimpleNamespace(id=55), from_user=SimpleNamespace(mention="User"),
            reply=AsyncMock(),
        )
        with patch.object(bot_filter, "REACTIONS", ["👍"]), \
                patch.object(bot_filter, "get_search_results",
                             AsyncMock(return_value=([], 0, 0, "all"))), \
                patch.object(bot_filter, "start_auto_delete_timer", AsyncMock()):
            await bot_filter.auto_filter(None, message, settings={"spell_check": False})
            await asyncio.sleep(0)
        message.react.assert_awaited_once_with("👍", big=False)


if __name__ == "__main__":
    unittest.main()
