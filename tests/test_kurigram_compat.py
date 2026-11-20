"""Kurigram migration: dependency pin, listen shim and timeout alias."""
import asyncio
import os
import unittest
from pathlib import Path

for key, value in {
    "API_ID": "1", "API_HASH": "test", "BOT_TOKEN": "1:test", "ADMINS": "1",
    "LOG_CHANNEL": "-1001", "BIN_CHANNEL": "-1002",
    "DATABASE_URL": "mongodb://localhost:27017", "URL": "https://example.com",
}.items():
    os.environ.setdefault(key, value)

from pyrogram import Client, StopPropagation, enums

import kurigram_compat as compat


class FakeClient:
    def __init__(self):
        self.handlers = []

    def add_handler(self, handler, group):
        self.handlers.append((handler, group))

    def remove_handler(self, handler, group):
        self.handlers.remove((handler, group))


class CompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_requirements_pin_latest_kurigram(self):
        requirements = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text()
        self.assertIn("kurigram==2.2.27", requirements)
        self.assertNotIn("hydrogram", requirements)

    def test_button_style_enum_exists(self):
        self.assertTrue(hasattr(enums, "ButtonStyle"))
        self.assertTrue(hasattr(enums.ButtonStyle, "SUCCESS"))
        self.assertTrue(hasattr(enums.ButtonStyle, "DANGER"))
        self.assertTrue(hasattr(enums.ButtonStyle, "PRIMARY"))

    def test_listener_timeout_is_a_timeout(self):
        self.assertTrue(issubclass(compat.ListenerTimeout, asyncio.TimeoutError))

    async def test_listen_captures_next_message_and_stops_propagation(self):
        client = FakeClient()
        captured = {}

        async def send():
            for _ in range(50):
                if client.handlers:
                    break
                await asyncio.sleep(0.001)
            handler, group = client.handlers[0]
            captured["group"] = group
            message = object()
            with self.assertRaises(StopPropagation):
                await handler.callback(client, message)
            return message

        expected = asyncio.create_task(send())
        result = await compat.listen(client, chat_id=1, user_id=2, timeout=1)
        self.assertIs(result, await expected)
        self.assertEqual(captured["group"], -1)
        self.assertEqual(client.handlers, [])

    async def test_listen_times_out_and_cleans_up(self):
        client = FakeClient()
        with self.assertRaises(compat.ListenerTimeout):
            await compat.listen(client, chat_id=1, timeout=0.02)
        self.assertEqual(client.handlers, [])

    async def test_client_has_listen(self):
        self.assertTrue(hasattr(Client, "listen"))
        self.assertTrue(callable(Client.listen))


if __name__ == "__main__":
    unittest.main()
