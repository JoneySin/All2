import os
import unittest

for key, value in {
    "API_ID": "1", "API_HASH": "test", "BOT_TOKEN": "1:test", "ADMINS": "1",
    "LOG_CHANNEL": "-1001", "BIN_CHANNEL": "-1002",
    "DATABASE_URL": "mongodb://localhost:27017", "URL": "https://example.com",
    "UPI_ID": "test@upi", "UPI_NAME": "Test Merchant", "RECEIPT_SEND_USERNAME": "@admin",
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
            self.assertIn('class="act-name"', card)
            self.assertIn('openCatalogCard(', card)
            self.assertIn('prefetchCatalogUrl(', card)
        self.assertIn('act-text-card', render_catalog_card(item, 'actor', 'text'))
        self.assertIn('act-poster', render_catalog_card(item, 'actor', 'poster'))

    def test_actor_name_glow_css_and_gzip_helper(self):
        from web import web_assets
        self.assertNotIn('actorNameRedBounce', web_assets.CSS)
        self.assertNotIn('backBtnRedBounce', web_assets.CSS)
        self.assertIn('.is-opening .act-name', web_assets.CSS)
        self.assertIn('.back-pill-btn.is-backing', web_assets.CSS)
        self.assertIn('openCatalogCard', web_assets.JS)
        self.assertIn('openBackNav', web_assets.JS)
        self.assertIn('prefetchCatalogUrl', web_assets.JS)
        self.assertNotIn('setTimeout(function(){window.location.href', web_assets.JS)
        res = web_assets._h('<html>test</html>')
        self.assertTrue(res.compression)

    def test_back_buttons_use_shared_glow_pill(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1] / 'web'
        for filename, expected_href in (
            ('actor_routes.py', 'href="/actors"'),
            ('post_routes.py', 'href="/posts"'),
            ('recycle_routes.py', 'href="/dashboard"'),
            ('post_editor.py', 'href="{esc(back)}"'),
        ):
            src = (root / filename).read_text(encoding='utf-8')
            self.assertIn('back-pill-btn', src, filename)
            self.assertIn('openBackNav(this,event)', src, filename)
            self.assertIn('>← Back</a>', src, filename)
            self.assertIn(expected_href, src, filename)

    def test_post_escapes_content_and_rejects_unsafe_image_url(self):
        card = render_catalog_card({'_id': 'two', 'title': '<script>', 'category': 'A&B',
                                    'cover_image': 'javascript:alert(1)'}, 'post')
        self.assertIn('&lt;script&gt;', card)
        self.assertIn('A&amp;B', card)
        self.assertNotIn('javascript:', card)


if __name__ == '__main__':
    unittest.main()
