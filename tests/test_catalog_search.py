"""Catalogue pagination, filtering and access regressions (mock MongoDB)."""
import os
import unittest
from unittest.mock import AsyncMock, patch

for key, value in {
    'API_ID': '1', 'API_HASH': 'test', 'BOT_TOKEN': '1:test', 'ADMINS': '1',
    'LOG_CHANNEL': '-1001', 'BIN_CHANNEL': '-1002',
    'DATABASE_URL': 'mongodb://localhost:27017', 'URL': 'https://example.com',
}.items():
    os.environ.setdefault(key, value)

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from bson import ObjectId
from mongomock_motor import AsyncMongoMockClient
from web import actor_routes, post_routes
from web.catalog_search import catalog_page, parse_catalog_offset
from database import ia_filterdb as db


class CatalogTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        store = AsyncMongoMockClient().test
        self.actors, self.posts = store.actors, store.posts
        await self.actors.insert_many([
            {'_id': ObjectId(f'{i:024x}'), 'name': f'Profile {i:02}',
             'category': 'actor' if i < 20 else 'app', 'created_at': 1}
            for i in range(1, 23)])
        await self.posts.insert_many([
            {'_id': ObjectId(f'{i:024x}'), 'title': f'Post {i:02}', 'tags': ['shared'],
             'category': 'Movies' if i < 21 else 'Porn', 'created_at': 1}
            for i in range(1, 23)])
        self.patches = [patch.object(actor_routes, 'actors', self.actors),
                        patch.object(post_routes, 'posts_col', self.posts),
                        patch.object(actor_routes, 'get_auth', AsyncMock(return_value=('user', 5))),
                        patch.object(post_routes, 'get_auth', AsyncMock(return_value=('user', 5))),
                        patch.object(actor_routes, 'require_active_plan', AsyncMock(return_value=True)),
                        patch.object(post_routes, 'require_active_plan', AsyncMock(return_value=True))]
        for p in self.patches: p.start()
        app = web.Application()
        app.add_routes(actor_routes.actor_routes)
        app.add_routes(post_routes.post_routes)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        for p in reversed(self.patches): p.stop()

    async def test_page_boundaries_and_tie_break(self):
        first, has_next = await catalog_page(self.posts, {})
        second, more = await catalog_page(self.posts, {}, 20)
        self.assertEqual((len(first), has_next, len(second), more), (20, True, 2, False))
        self.assertEqual(len({p['_id'] for p in first + second}), 22)
        exactly, more = await catalog_page(self.posts, {'category': 'Movies'})
        self.assertEqual((len(exactly), more), (20, False))
        self.assertEqual((await catalog_page(self.posts, {}, -4))[0], first)
        self.assertEqual((await catalog_page(self.posts, {}, 'bad'))[0], first)
        self.assertEqual(parse_catalog_offset('9' * 100), 2**63 - 1)

    async def test_search_categories_literal_query_and_offsets(self):
        for path, category in [('/api/directory/search', 'cat=app'),
                               ('/api/posts/search', 'category=Porn')]:
            resp = await self.client.get(path + '?' + category)
            data = await resp.json()
            self.assertEqual(resp.status, 200)
            self.assertFalse(data['has_next'])
            resp = await self.client.get(path + '?offset=20')
            self.assertFalse((await resp.json())['has_next'])
            resp = await self.client.get(path + '?q=%5B')
            self.assertFalse((await resp.json())['has_next'])
        resp = await self.client.get('/api/posts/search?q=shared&category=Movies')
        self.assertIn('Post 20', (await resp.json())['html'])

    async def test_access_and_database_failures(self):
        for mod, path in [(actor_routes, '/api/directory/search'), (post_routes, '/api/posts/search')]:
            with patch.object(mod, 'require_active_plan', AsyncMock(return_value=False)):
                self.assertEqual((await self.client.get(path)).status, 403)
            with patch.object(mod, 'get_auth', AsyncMock(return_value=(None, None))):
                self.assertEqual((await self.client.get(path)).status, 403)
            with patch.object(mod, 'catalog_page', AsyncMock(side_effect=RuntimeError('offline'))):
                self.assertEqual((await self.client.get(path)).status, 503)

    async def test_actor_files_access_and_invalid_id(self):
        # Route name and parameters follow the profile page's AJAX call.
        path = '/api/actor/search?id=bad'
        response = await self.client.get(path)
        self.assertEqual(response.status, 400)
        with patch.object(actor_routes, 'require_active_plan', AsyncMock(return_value=False)):
            self.assertEqual((await self.client.get(path)).status, 403)


class GroupFilterTests(unittest.TestCase):
    def test_group_filter_precedence(self):
        query = {'file_name': 'example'}
        self.assertEqual(db._apply_group_filter(query), query)
        self.assertEqual(db._apply_group_filter(query, grouped_only=True),
                         {'$and': [query, {'group_id': {'$exists': True}}]})
        self.assertEqual(db._apply_group_filter(query, True, True),
                         {'$and': [query, {'group_id': {'$exists': False}}]})
