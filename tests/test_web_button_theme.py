"""Web admin buttons must stay readable in both themes."""
import os
import unittest

for key, value in {
    "API_ID": "1", "API_HASH": "test", "BOT_TOKEN": "1:test", "ADMINS": "1",
    "LOG_CHANNEL": "-1001", "BIN_CHANNEL": "-1002",
    "DATABASE_URL": "mongodb://localhost:27017", "URL": "https://example.com",
}.items():
    os.environ.setdefault(key, value)

from web.dashboard_routes import CARD_CSS
from web.web_assets import CSS


class WebButtonThemeTests(unittest.TestCase):
    def test_edit_buttons_use_a_light_theme_surface(self):
        self.assertNotIn("rgba(42,42,48,.90)", CSS)
        self.assertIn(".btn-edit{background:rgba(255,255,255,.18)", CSS)
        self.assertIn(".light .btn-edit{", CSS)
        self.assertIn("color:var(--text)", CSS.split(".light .btn-edit{", 1)[1].split("}", 1)[0])

    def test_delete_buttons_are_bright_red_in_both_themes(self):
        self.assertNotIn("rgba(160,8,8,.78)", CSS)
        self.assertIn(".light .btn-del{", CSS)
        self.assertIn("background:var(--accent)", CSS.split(".light .btn-del{", 1)[1].split("}", 1)[0])

    def test_group_secondary_buttons_are_not_white_on_light_grey(self):
        self.assertIn(".gm-btn.alt{background:var(--bg4);color:var(--text)", CARD_CSS)
        self.assertIn(".gm-btn.alt:hover{", CARD_CSS)
        self.assertNotIn(".gm-btn.alt{background:var(--bg4)}", CARD_CSS)

    def test_group_remove_button_is_not_dark_maroon(self):
        self.assertNotIn("rgba(160,8,8,.78)", CARD_CSS)
        self.assertIn(".gm-mem-actions button.gm-remove{background:var(--accent)", CARD_CSS)


if __name__ == "__main__":
    unittest.main()
