"""Kurigram-native inline keyboard builders and colour rules."""
import itertools
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

from pyrogram import enums

from keyboards import DANGER, PRIMARY, SUCCESS, ui_button, ui_keyboard


class StyleRulesTests(unittest.TestCase):
    def test_semantic_colours(self):
        self.assertEqual(ui_button("❌ Close", callback_data="close_42").style, DANGER)
        self.assertEqual(ui_button("Cancel Indexing", callback_data="cancel").style, DANGER)
        self.assertEqual(ui_button("Restart Bot", callback_data="restart").style, DANGER)
        self.assertEqual(ui_button("💥 CONFIRM DESTROY ALL", callback_data="confirm_del").style, DANGER)
        self.assertEqual(ui_button("▶️ Watch / Download", callback_data="stream#1").style, SUCCESS)
        self.assertEqual(ui_button("Send all episodes", callback_data="send_all").style, SUCCESS)
        self.assertEqual(ui_button("💎 Buy Premium Plan", callback_data="buy_prem").style, SUCCESS)
        self.assertEqual(ui_button("✅ Approve Payment", callback_data="pay_confirm").style, SUCCESS)
        self.assertEqual(ui_button("◀️ Prev", callback_data="nav_1").style, PRIMARY)
        self.assertEqual(ui_button("👨‍🚒 Help Menu", callback_data="help").style, PRIMARY)

    def test_toggle_state_text(self):
        self.assertEqual(ui_button("✅ ON", callback_data="toggle").style, SUCCESS)
        self.assertEqual(ui_button("❌ OFF", callback_data="toggle").style, DANGER)

    def test_explicit_style_wins_when_unique(self):
        self.assertEqual(ui_button("Watch", callback_data="stream#1", style=DANGER).style, DANGER)


class KeyboardTests(unittest.TestCase):
    def test_every_button_is_coloured_and_rows_are_unique(self):
        markup = ui_keyboard([
            [ui_button("▶️ Watch / Download", callback_data="stream#1"),
             ui_button("❌ Close", callback_data="close_1")],
            [ui_button("◀️ Prev", callback_data="nav_prev"),
             ui_button("Next ▶️", callback_data="nav_next")],
            [ui_button("🌐 Website", url="https://example.com")],
        ])
        styles = [[button.style for button in row] for row in markup.inline_keyboard]
        self.assertEqual(styles[0], [SUCCESS, DANGER])
        self.assertEqual(styles[1], [PRIMARY, SUCCESS])
        self.assertEqual(styles[2], [PRIMARY])
        self.assertNotIn(enums.ButtonStyle.DEFAULT, itertools.chain.from_iterable(styles))

    def test_rows_never_repeat_a_colour(self):
        markup = ui_keyboard([
            [ui_button("▶️ Watch", callback_data="stream#1"),
             ui_button("⬇️ Download", callback_data="download"),
             ui_button("❌ Close", callback_data="close_1")],
            [ui_button("◀️ Prev", callback_data="prev"),
             ui_button("Next ▶️", callback_data="next"),
             ui_button("⚙️ Settings", callback_data="settings")],
        ])
        for row in markup.inline_keyboard:
            colours = [button.style for button in row]
            self.assertEqual(len(colours), len(set(colours)), colours)

    def test_duplicate_explicit_styles_are_separated(self):
        markup = ui_keyboard([[ui_button("Watch", callback_data="stream", style=DANGER),
                               ui_button("Help", callback_data="help", style=DANGER)]])
        first, second = markup.inline_keyboard[0]
        self.assertEqual(first.style, DANGER)
        self.assertNotEqual(second.style, DANGER)

    def test_long_rows_keep_neighbours_different(self):
        markup = ui_keyboard([[
            ui_button("Watch", callback_data="stream#1"),
            ui_button("Download", callback_data="download"),
            ui_button("Close", callback_data="close_1"),
            ui_button("Help", callback_data="help"),
        ]])
        colours = [button.style for button in markup.inline_keyboard[0]]
        self.assertTrue(all(a != b for a, b in itertools.pairwise(colours)), colours)
        self.assertEqual(len(set(colours)), 3)


class NativeUsageTests(unittest.TestCase):
    def test_plugins_use_the_native_keyboard_helpers(self):
        root = Path(__file__).resolve().parents[1]
        for path in sorted((root / "plugins").glob("*.py")):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("InlineKeyboardButton(", source, path.name)
            self.assertNotIn("InlineKeyboardMarkup(", source, path.name)


if __name__ == "__main__":
    unittest.main()
