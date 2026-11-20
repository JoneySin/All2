"""Kurigram native button colours applied to every inline keyboard."""
import itertools
import os
import unittest
from pathlib import Path

for key, value in {
    "API_ID": "1", "API_HASH": "test", "BOT_TOKEN": "1:test", "ADMINS": "1",
    "LOG_CHANNEL": "-1001", "BIN_CHANNEL": "-1002",
    "DATABASE_URL": "mongodb://localhost:27017", "URL": "https://example.com",
}.items():
    os.environ.setdefault(key, value)

from pyrogram import enums
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import button_styles as bs


class StyleRulesTests(unittest.TestCase):
    def test_semantic_colours(self):
        self.assertEqual(bs.style_for("❌ Close", "close_42"), enums.ButtonStyle.DANGER)
        self.assertEqual(bs.style_for("Cancel Indexing", "cancel"), enums.ButtonStyle.DANGER)
        self.assertEqual(bs.style_for("Restart Bot", "restart"), enums.ButtonStyle.DANGER)
        self.assertEqual(bs.style_for("▶️ Watch / Download", "stream#1"), enums.ButtonStyle.SUCCESS)
        self.assertEqual(bs.style_for("Send all episodes", ""), enums.ButtonStyle.SUCCESS)
        self.assertEqual(bs.style_for("💎 Buy Premium Plan", "buy_prem"), enums.ButtonStyle.SUCCESS)
        self.assertEqual(bs.style_for("✅ Approve Payment", "pay_confirm"), enums.ButtonStyle.SUCCESS)
        self.assertEqual(bs.style_for("◀️ Prev", "nav_1"), enums.ButtonStyle.PRIMARY)
        self.assertEqual(bs.style_for("👨‍🚒 Help Menu", "help"), enums.ButtonStyle.PRIMARY)

    def test_toggle_state_text(self):
        self.assertEqual(bs.style_for("✅ ON"), enums.ButtonStyle.SUCCESS)
        self.assertEqual(bs.style_for("❌ OFF"), enums.ButtonStyle.DANGER)

    def test_callback_data_can_be_bytes(self):
        self.assertEqual(bs.style_for("", b"close_1"), enums.ButtonStyle.DANGER)


class AutoStyleTests(unittest.TestCase):
    def test_every_button_in_a_new_keyboard_is_coloured(self):
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("▶️ Watch / Download", callback_data="stream#1"),
             InlineKeyboardButton("❌ Close", callback_data="close_1")],
            [InlineKeyboardButton("◀️ Prev", callback_data="nav_prev"),
             InlineKeyboardButton("Next ▶️", callback_data="nav_next")],
            [InlineKeyboardButton("🌐 Website", url="https://example.com")],
        ])
        styles = [[button.style for button in row] for row in markup.inline_keyboard]
        self.assertEqual(styles[0], [enums.ButtonStyle.SUCCESS, enums.ButtonStyle.DANGER])
        self.assertEqual(styles[1], [enums.ButtonStyle.PRIMARY, enums.ButtonStyle.SUCCESS])
        self.assertEqual(styles[2], [enums.ButtonStyle.PRIMARY])
        self.assertNotIn(enums.ButtonStyle.DEFAULT,
                         [button.style for row in markup.inline_keyboard for button in row])

    def test_no_row_repeats_a_colour(self):
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("▶️ Watch", callback_data="stream#1"),
             InlineKeyboardButton("⬇️ Download", callback_data="download"),
             InlineKeyboardButton("❌ Close", callback_data="close_1")],
            [InlineKeyboardButton("◀️ Prev", callback_data="prev"),
             InlineKeyboardButton("Next ▶️", callback_data="next"),
             InlineKeyboardButton("⚙️ Settings", callback_data="settings")],
        ])
        for row in markup.inline_keyboard:
            colours = [button.style for button in row]
            self.assertEqual(len(colours), len(set(colours)), colours)

    def test_long_rows_keep_neighbours_different(self):
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("Watch", callback_data="stream#1"),
            InlineKeyboardButton("Download", callback_data="download"),
            InlineKeyboardButton("Close", callback_data="close_1"),
            InlineKeyboardButton("Help", callback_data="help"),
        ]])
        colours = [button.style for button in markup.inline_keyboard[0]]
        self.assertTrue(all(a != b for a, b in itertools.pairwise(colours)), colours)
        self.assertEqual(len(set(colours)), 3)

    def test_explicit_style_wins(self):
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("Watch", callback_data="stream#1", style=enums.ButtonStyle.DANGER),
        ]])
        self.assertEqual(markup.inline_keyboard[0][0].style, enums.ButtonStyle.DANGER)

    def test_install_is_idempotent_and_wired_in_bot(self):
        bs.install()
        bs.install()
        source = (Path(__file__).resolve().parents[1] / "bot.py").read_text(encoding="utf-8")
        self.assertIn("import button_styles", source)
        self.assertIn("import kurigram_compat", source)


if __name__ == "__main__":
    unittest.main()
