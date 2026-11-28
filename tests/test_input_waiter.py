"""Kurigram-native input waiter, dependency pins and crypto backend."""
import asyncio
import os
import unittest
from pathlib import Path

for key, value in {
    "API_ID": "1", "API_HASH": "test", "BOT_TOKEN": "1:test", "ADMINS": "1",
    "LOG_CHANNEL": "-1001", "BIN_CHANNEL": "-1002",
    "DATABASE_URL": "mongodb://localhost:27017", "URL": "https://example.com",
    "UPI_ID": "test@upi", "UPI_NAME": "Test Merchant", "RECEIPT_SEND_USERNAME": "@admin",
}.items():
    os.environ.setdefault(key, value)

from pyrogram import Client, StopPropagation, enums

from input_waiter import InputTimeout, wait_for_user_message


class FakeClient:
    def __init__(self):
        self.handlers = []

    def add_handler(self, handler, group):
        self.handlers.append((handler, group))

    def remove_handler(self, handler, group):
        self.handlers.remove((handler, group))


class InputWaiterTests(unittest.IsolatedAsyncioTestCase):
    async def test_requirements_pin_latest_kurigram(self):
        import pyrogram
        import pymongo
        requirements = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text()
        self.assertIn("kurigram==2.2.28", requirements)
        self.assertEqual(pyrogram.__version__, "2.2.28")
        self.assertIn("pymongo==4.20.2", requirements)
        self.assertEqual(pymongo.__version__, "4.20.2")
        self.assertIn("kuricrypt==0.1.2", requirements)
        self.assertNotIn("TgCrypto", requirements)

    async def test_kurigram_2228_stream_and_media_helpers(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch
        from pyrogram import raw
        from pyrogram.errors import BadMsgNotification
        from pyrogram.file_id import FileId, FileType, ThumbnailSource
        import media_probe
        from web.utils.custom_dl import TGCustomYield

        closed = False

        async def fake_get_file(*_a, **_kw):
            nonlocal closed
            try:
                yield b"a" * (1024 * 1024)
                yield b"b" * (1024 * 1024)
            finally:
                closed = True

        fake_client = SimpleNamespace(get_file=fake_get_file)
        with patch.object(FileId, "decode", return_value=SimpleNamespace()):
            data = await media_probe.fetch_file_range(fake_client, "ref", 2 * 1024 * 1024, 0, 1)
        self.assertEqual(len(data), 1024 * 1024)
        self.assertTrue(closed)

        loc = await TGCustomYield.get_location(SimpleNamespace(
            file_type=FileType.CHAT_PHOTO,
            chat_id=123,
            chat_access_hash=456,
            media_id=789,
            thumbnail_source=ThumbnailSource.CHAT_PHOTO_BIG,
        ))
        self.assertIsInstance(loc, raw.types.InputPeerPhotoFileLocation)
        self.assertEqual(loc.photo_id, 789)
        self.assertTrue(loc.big)

        calls = 0

        async def fake_invoke(_query, **_kw):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise BadMsgNotification(16)
            return raw.types.upload.File(type=raw.types.storage.FileMp4(), mtime=0, bytes=b"ok")

        ms = SimpleNamespace(invoke=AsyncMock(side_effect=fake_invoke))
        out = await TGCustomYield()._get_chunk(ms, loc, 0, 1024)
        self.assertEqual(out, b"ok")
        self.assertEqual(calls, 2)

    def test_fast_crypto_backend_is_kuricrypt(self):
        import kuricrypt
        from pyrogram.crypto import aes
        self.assertIs(aes._crypto_backend, kuricrypt)
        key, iv, data = os.urandom(32), os.urandom(32), os.urandom(4096)
        self.assertEqual(
            kuricrypt.ige256_decrypt(kuricrypt.ige256_encrypt(data, key, iv), key, iv),
            data,
        )

    def test_button_style_enum_exists(self):
        self.assertTrue(hasattr(enums, "ButtonStyle"))
        for style in ("SUCCESS", "DANGER", "PRIMARY"):
            self.assertTrue(hasattr(enums.ButtonStyle, style))

    def test_listener_timeout_is_a_timeout(self):
        self.assertTrue(issubclass(InputTimeout, asyncio.TimeoutError))

    async def test_waits_for_next_message_and_stops_propagation(self):
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
        result = await wait_for_user_message(client, chat_id=1, user_id=2, timeout=1)
        self.assertIs(result, await expected)
        self.assertEqual(captured["group"], -1)
        self.assertEqual(client.handlers, [])

    async def test_times_out_and_cleans_up(self):
        client = FakeClient()
        with self.assertRaises(InputTimeout):
            await wait_for_user_message(client, chat_id=1, timeout=0.02)
        self.assertEqual(client.handlers, [])

    def test_does_not_patch_client(self):
        # Input waiting is a helper, not a monkey-patched Client method.
        self.assertNotIn("listen", vars(Client))


if __name__ == "__main__":
    unittest.main()
