"""Settings from info.py must have a real effect, not just a DB default."""
import asyncio
import os
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

for key, value in {
    "API_ID": "1", "API_HASH": "test", "BOT_TOKEN": "1:test", "ADMINS": "1",
    "LOG_CHANNEL": "-1001", "BIN_CHANNEL": "-1002",
    "DATABASE_URL": "mongodb://localhost:27017", "URL": "https://example.com",
}.items():
    os.environ.setdefault(key, value)

from info import PAYMENT_ENV, REQUIRED_ENV
from plugins import commands
from plugins import filter as bot_filter


def _start_message():
    return SimpleNamespace(
        command=["start", "file_5_a"],
        chat=SimpleNamespace(id=5, type=__import__("pyrogram").enums.ChatType.PRIVATE),
        from_user=SimpleNamespace(id=5, mention="Admin"),
        delete=AsyncMock(),
    )


def _file():
    return {"_id": "a", "file_name": "Film 720p.mkv", "file_size": 10,
            "file_ref": "ref-a", "group_id": "7"}


class RequiredEnvTests(unittest.TestCase):
    def test_compulsory_list_is_the_single_source_of_truth(self):
        self.assertEqual(REQUIRED_ENV, (
            "API_ID", "API_HASH", "BOT_TOKEN", "ADMINS",
            "LOG_CHANNEL", "DATABASE_URL", "URL",
        ))
        self.assertEqual(PAYMENT_ENV, ("UPI_ID", "UPI_NAME", "RECEIPT_SEND_USERNAME"))

    def test_missing_required_variable_fails_before_anything_else(self):
        env = os.environ.copy()
        env.pop("URL", None)
        result = subprocess.run(
            [sys.executable, "-c", "import info"],
            cwd=Path(__file__).resolve().parents[1],
            env=env, capture_output=True, text=True, timeout=20,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing required environment variable(s): URL", result.stderr)

    def test_missing_log_channel_fails_while_bin_and_delete_fallback_to_log(self):
        env = os.environ.copy()
        env.pop("LOG_CHANNEL", None)
        no_log = subprocess.run(
            [sys.executable, "-c", "import info"],
            cwd=Path(__file__).resolve().parents[1],
            env=env, capture_output=True, text=True, timeout=20,
        )
        self.assertNotEqual(no_log.returncode, 0)
        self.assertIn("LOG_CHANNEL", no_log.stderr)

        env2 = os.environ.copy()
        env2["LOG_CHANNEL"] = "-100111"
        env2.pop("BIN_CHANNEL", None)
        env2.pop("DELETE_CHANNEL", None)
        env2.pop("MEDIA_STORAGE_CHANNEL", None)
        ok = subprocess.run(
            [sys.executable, "-c",
             "import info; print(info.LOG_CHANNEL, info.BIN_CHANNEL, info.DELETE_CHANNEL, info.MEDIA_STORAGE_CHANNEL)"],
            cwd=Path(__file__).resolve().parents[1],
            env=env2, capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(ok.returncode, 0, msg=ok.stderr)
        self.assertEqual(ok.stdout.strip(), "-100111 -100111 -100111 -100111")


class ProtectContentTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_file_uses_per_chat_file_secure_setting(self):
        client = SimpleNamespace(
            send_cached_media=AsyncMock(return_value=SimpleNamespace(id=9)))
        message = _start_message()
        with patch.object(commands, "db", SimpleNamespace(
                    is_user_exist=AsyncMock(return_value=True))), \
                patch.object(commands, "IS_PREMIUM", False), \
                patch.object(commands, "REACTIONS", []), \
                patch.object(commands, "PM_FILE_DELETE_TIME", 0), \
                patch.object(commands, "get_file_details", AsyncMock(return_value=_file())), \
                patch.object(commands, "get_group_for_file", AsyncMock(return_value=None)), \
                patch.object(commands, "get_settings", AsyncMock(
                    return_value={"caption": "{file_name}", "file_secure": True})):
            await commands.start(client, message)

        self.assertIs(client.send_cached_media.await_args.kwargs["protect_content"], True)

    async def test_group_send_uses_file_secure_setting(self):
        client = SimpleNamespace(
            send_cached_media=AsyncMock(return_value=SimpleNamespace(id=9)),
            send_message=AsyncMock())
        query = SimpleNamespace(
            data="grp#7", from_user=SimpleNamespace(id=5),
            message=SimpleNamespace(chat=SimpleNamespace(id=5)),
            answer=AsyncMock())
        group = {"_id": "7", "name": "Film", "members": ["a", "b"],
                 "group_type": "quality", "episode_order": []}
        with patch.object(commands, "IS_PREMIUM", False), \
                patch.object(commands, "PM_FILE_DELETE_TIME", 0), \
                patch.object(commands, "get_groups_by_ids", AsyncMock(return_value=[group])), \
                patch.object(commands, "get_files_by_ids", AsyncMock(return_value=[
                    {"_id": "a", "file_name": "a.mkv", "file_size": 10, "file_ref": "ref-a"},
                    {"_id": "b", "file_name": "b.mkv", "file_size": 10, "file_ref": "ref-b"},
                ])), \
                patch.object(commands, "get_settings", AsyncMock(
                    return_value={"caption": "{file_name}", "file_secure": True})):
            await commands.send_group_files(client, query)

        self.assertTrue(all(call.kwargs["protect_content"] is True
                            for call in client.send_cached_media.await_args_list))


class AutoDeleteSettingTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, enabled):
        message = SimpleNamespace(
            text="Avengers", react=AsyncMock(), chat=SimpleNamespace(id=55),
            from_user=SimpleNamespace(mention="User"), reply=AsyncMock())
        timer = AsyncMock()
        with patch.object(bot_filter, "REACTIONS", []), \
                patch.object(bot_filter, "get_search_results",
                             AsyncMock(return_value=([], 0, 0, "all"))), \
                patch.object(bot_filter, "start_auto_delete_timer", timer):
            await bot_filter.auto_filter(
                None, message,
                settings={"spell_check": False, "auto_delete": enabled})
            await asyncio.sleep(0)
        return timer

    async def test_disabled_auto_delete_keeps_search_reply(self):
        timer = await self._run(False)
        timer.assert_not_awaited()

    async def test_enabled_auto_delete_still_schedules_cleanup(self):
        timer = await self._run(True)
        timer.assert_awaited_once()

    def test_merged_media_storage_channel_resolution(self):
        import info
        with patch.dict(os.environ, {"MEDIA_STORAGE_CHANNEL": "", "THUMBNAIL_STORAGE_CHANNEL": "", "ACTOR_STORAGE_CHANNEL": ""}):
            self.assertEqual(info._resolve_media_storage_channel(), info.BIN_CHANNEL)
        with patch.dict(os.environ, {"MEDIA_STORAGE_CHANNEL": "-100999", "THUMBNAIL_STORAGE_CHANNEL": "-100888", "ACTOR_STORAGE_CHANNEL": "-100777"}):
            self.assertEqual(info._resolve_media_storage_channel(), -100999)
        with patch.dict(os.environ, {"MEDIA_STORAGE_CHANNEL": "", "THUMBNAIL_STORAGE_CHANNEL": "-100888", "ACTOR_STORAGE_CHANNEL": "-100777"}):
            self.assertEqual(info._resolve_media_storage_channel(), -100888)
        with patch.dict(os.environ, {"MEDIA_STORAGE_CHANNEL": "", "THUMBNAIL_STORAGE_CHANNEL": "", "ACTOR_STORAGE_CHANNEL": "-100777"}):
            self.assertEqual(info._resolve_media_storage_channel(), -100777)


if __name__ == "__main__":
    unittest.main()
