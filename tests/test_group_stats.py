"""Saved group statistics use actual QualityGroups records, not chat groups."""
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
from mongomock_motor import AsyncMongoMockClient
from database import ia_filterdb as db
from web import stats_routes as stats


class GroupStatsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mongo = AsyncMongoMockClient()
        self.store = self.mongo.stats_test
        patches = [
            patch.object(db, 'groups', self.store.QualityGroups),
            patch.object(stats, 'get_auth', AsyncMock(return_value=('admin', 1))),
            patch.object(stats, 'db_count_documents', AsyncMock(return_value={})),
            patch.object(stats, '_get_total_plays', AsyncMock(return_value=0)),
            patch.object(stats, 'get_directory_counts', AsyncMock(return_value=(0, 0, 0, 0))),
            patch.object(stats, 'get_post_category_counts', AsyncMock(return_value=(0, 0, 0, 0, 0))),
            patch.object(stats.user_db, 'total_users_count', AsyncMock(return_value=0)),
            patch.object(stats.user_db, 'get_today_logged_in_users_count', AsyncMock(return_value=0)),
            patch.object(stats.user_db, 'get_premium_users_count', AsyncMock(return_value=0)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        app = web.Application()
        app.add_routes(stats.stats_routes)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.mongo.close()

    async def test_empty_and_live_type_counts(self):
        self.assertEqual(await db.get_saved_group_counts(), {'total': 0, 'quality': 0, 'series': 0})
        await self.store.QualityGroups.insert_many([
            {'_id': '1', 'group_type': 'quality', 'members': ['a', 'b']},
            {'_id': '2', 'group_type': 'series', 'members': ['c', 'd']},
            {'_id': '3', 'members': ['legacy']},  # old singleton record, still stored
            {'_id': '4', 'group_type': 'unexpected'},  # same quality fallback as rendering
        ])
        await self.store.Groups.insert_many([{'_id': 1}, {'_id': 2}, {'_id': 3}])
        self.assertEqual(await db.get_saved_group_counts(), {'total': 4, 'quality': 3, 'series': 1})
        response = await self.client.get('/stats')
        body = await response.text()
        self.assertEqual(response.status, 200)
        self.assertIn('id="saved-group-total"><span data-count="4"', body)
        self.assertIn('id="saved-quality-count"><span data-count="3"', body)
        self.assertIn('id="saved-series-count"><span data-count="1"', body)
        await self.store.QualityGroups.update_one({'_id': '1'}, {'$set': {'group_type': 'series'}})
        await self.store.QualityGroups.delete_one({'_id': '2'})
        self.assertEqual(await db.get_saved_group_counts(), {'total': 3, 'quality': 2, 'series': 1})
        body = await (await self.client.get('/stats')).text()
        self.assertIn('id="saved-group-total"><span data-count="3"', body)
        self.assertIn('id="saved-quality-count"><span data-count="2"', body)

    async def test_failure_is_not_falsely_displayed_as_zero(self):
        with patch.object(stats, 'get_saved_group_counts', AsyncMock(side_effect=RuntimeError('offline'))):
            response = await self.client.get('/stats')
        self.assertEqual(response.status, 200)
        body = await response.text()
        self.assertIn('id="saved-group-total">Unavailable', body)
        self.assertIn('id="saved-series-count">—', body)
        self.assertIn('Total Files', body)

    async def test_stats_remain_admin_only(self):
        for identity in [('user', 2), (None, None)]:
            with patch.object(stats, 'get_auth', AsyncMock(return_value=identity)), \
                 patch.object(stats, 'get_saved_group_counts', AsyncMock()) as counts:
                response = await self.client.get('/stats', allow_redirects=False)
                self.assertEqual(response.status, 302)
                counts.assert_not_awaited()
