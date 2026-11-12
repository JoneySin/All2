import os
import unittest

for key, value in {
    "API_ID": "1", "API_HASH": "test", "BOT_TOKEN": "1:test", "ADMINS": "1",
    "LOG_CHANNEL": "-1001", "BIN_CHANNEL": "-1002",
    "DATABASE_URL": "mongodb://localhost:27017", "URL": "https://example.com",
}.items():
    os.environ.setdefault(key, value)

from web.catalog_cards import render_catalog_card


class CatalogCardTests(unittest.TestCase):
    def test_profile_text_and_poster_escape_values(self):
        item = {'_id': 'one', 'name': '<Profile>', 'category': '<actor>', 'created_at': 1}
        for mode in ('text', 'poster'):
            card = render_catalog_card(item, 'actor', mode)
            self.assertIn('&lt;Profile&gt;', card)
            self.assertIn('&lt;actor&gt;', card.lower())
            self.assertNotIn('<Profile>', card)
        self.assertIn('act-text-card', render_catalog_card(item, 'actor', 'text'))
        self.assertIn('act-poster', render_catalog_card(item, 'actor', 'poster'))

    def test_post_escapes_content_and_rejects_unsafe_image_url(self):
        card = render_catalog_card({'_id': 'two', 'title': '<script>', 'category': 'A&B',
                                    'cover_image': 'javascript:alert(1)'}, 'post')
        self.assertIn('&lt;script&gt;', card)
        self.assertIn('A&amp;B', card)
        self.assertNotIn('javascript:', card)


if __name__ == '__main__':
    unittest.main()
