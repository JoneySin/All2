"""Catalogue pagination, filtering and access regressions (mock MongoDB)."""
import os
import unittest
from unittest.mock import AsyncMock, patch

for key, value in {
    'API_ID': '1', 'API_HASH': 'test', 'BOT_TOKEN': '1:test', 'ADMINS': '1',
    'LOG_CHANNEL': '-1001', 'BIN_CHANNEL': '-1002',
    'DATABASE_URL': 'mongodb://localhost:27017', 'URL': 'https://example.com',
    'UPI_ID': 'test@upi', 'UPI_NAME': 'Test Merchant', 'RECEIPT_SEND_USERNAME': '@admin',
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


class ActorSearchSyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import asyncio
        from web import search_api as api
        self.api = api
        self.mongo = AsyncMongoMockClient()
        self.db = self.mongo['actor_search_sync_test']
        self.cols = {name: self.db[name.capitalize()] for name in ('primary', 'cloud', 'archive')}
        self.groups = self.db.QualityGroups
        self.seq = self.db.QualityGroupSeq
        self.actors = self.db.Actors
        self.actor_id = '65ab12345678901234567890'
        await self.actors.insert_one({
            '_id': ObjectId(self.actor_id),
            'name': 'Maya Lin',
            'bio': 'Test bio',
            'tags': ['Maya', 'Lin'],
            'gallery': [],
        })
        async def mock_find_phrase_files(phrase, limit=100):
            import re
            words = str(phrase or '').split()[:12]
            if not words:
                return []
            pattern = '^' + ''.join('(?=.*' + re.escape(w) + ')' for w in words)
            q = {'file_name': re.compile(pattern, re.I)}
            out = []
            for cname, c in self.cols.items():
                docs = await c.find(q, db.FILE_PROJECTION).limit(limit).to_list(length=limit)
                for d in docs:
                    d['source_col'] = cname
                out.extend(docs)
            return out

        self.patches = [
            patch.object(actor_routes, 'actors', self.actors),
            patch.object(actor_routes, 'get_auth', AsyncMock(return_value=('admin', 1))),
            patch.object(actor_routes, 'require_active_plan', AsyncMock(return_value=True)),
            patch.object(api, 'groups', self.groups),
            patch.object(api, 'group_seq', self.seq),
            patch.object(api, 'group_search_cursors', self.db.GroupSearchCursors),
            patch.object(api, 'FILE_COLLECTIONS', self.cols),
            patch.object(api, 'COLLECTIONS', {**self.cols, 'actors': self.actors}),
            patch.object(api, 'find_phrase_files', mock_find_phrase_files),
            patch.object(api, 'get_user_role', AsyncMock(return_value=('admin', 1))),
            patch.object(api, '_AUTO_GROUP_LOCK', asyncio.Lock()),
            patch.object(db, 'primary', self.cols['primary']),
            patch.object(db, 'cloud', self.cols['cloud']),
            patch.object(db, 'archive', self.cols['archive']),
            patch.object(db, 'groups', self.groups),
            patch.object(db, 'FILE_COLLECTIONS', self.cols),
            patch.object(db, 'COLLECTIONS', {**self.cols, 'actors': self.actors}),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        api._GH_CACHE.clear()
        api._SIB_CACHE.clear()
        api.PREFETCH_CACHE.clear()
        api.TRENDING_CACHE.clear()
        app = web.Application()
        app.add_routes(actor_routes.actor_routes)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.mongo.close()

    async def _seed_media(self):
        await self.groups.insert_one({
            '_id': '9', 'num': 9, 'name': 'Maya Anthology',
            'members': ['g1', 'g2'], 'group_type': 'series',
        })
        await self.cols['primary'].insert_many([
            {'_id': 'g1', 'file_ref': 'g1', 'file_name': 'Anthology Episode 1.mkv',
             'caption': 'Maya starring part 1', 'file_size': 1000, 'file_type': 'video',
             'duration': 1800, 'group_id': '9'},
            {'_id': 's1', 'file_ref': 's1', 'file_name': 'Maya Solo Clip.mp4',
             'caption': '', 'file_size': 500, 'file_type': 'video', 'duration': 600},
        ])
        await self.cols['cloud'].insert_many([
            {'_id': 'g2', 'file_ref': 'g2', 'file_name': 'Anthology Episode 2.mkv',
             'caption': '', 'file_size': 1200, 'file_type': 'video',
             'duration': 1900, 'group_id': '9'},
            {'_id': 'a1', 'file_ref': 'a1', 'file_name': 'Lin Feature 720p.mkv',
             'caption': '', 'file_size': 2000, 'file_type': 'video', 'duration': 3600},
            {'_id': 'a2', 'file_ref': 'a2', 'file_name': 'Lin Feature 1080p.mkv',
             'caption': '', 'file_size': 3000, 'file_type': 'video', 'duration': 3600},
        ])
        await self.cols['archive'].insert_many([
            {'_id': 'a3', 'file_ref': 'a3', 'file_name': 'Lin Feature 480p.mkv',
             'caption': '', 'file_size': 1500, 'file_type': 'video', 'duration': 3600},
            {'_id': 's2', 'file_ref': 's2', 'file_name': 'Maya Archive Reel.mp4',
             'caption': '', 'file_size': 700, 'file_type': 'video', 'duration': 900},
        ])

    async def test_actor_profile_renders_all_three_synced_filters(self):
        resp = await self.client.get(f'/actor/{self.actor_id}')
        self.assertEqual(resp.status, 200)
        html = await resp.text()
        for needle in (
            'actor-search-panel',
            'id="actMovieClear"', 'id="actorResInfo"', 'id="actorResCount"',
            'id="cddGfWrapActor"', 'id="cddGfBtnActor"', 'id="cddGfLabelActor"', 'id="cddGfMenuActor"',
            'data-val="all"', 'data-val="group"', 'data-val="single"',
            'id="cddColWrapActor"', 'id="cddModeWrapActor"',
            'class="cdd-kicker"', 'filter-active', 'scrollActorVideoTop',
            'pickActorGF', 'pickActorCol', 'pickActorMode', 'groupHtml(', 'cardHtml(',
            'width:100%;max-width:100%;height:auto;aspect-ratio:3/4',
            'class="actor-tab active" aria-pressed="true"',
            'class="actor-tab-label"',
            '.home-search-panel .gf-wrap,.actor-search-panel .gf-wrap{background:var(--accent);border-color:var(--accent);color:#fff',
            '.home-search-panel .gf-wrap .cdd-menu,.actor-search-panel .gf-wrap .cdd-menu{color:var(--text)}',
            '.grp-title{color:#60a5fa;',
            'body.light .grp-title,body.light .grp-open-title{color:#1d4ed8}',
        ):
            self.assertIn(needle, html)
        self.assertNotIn('@media(max-width:600px){.actor-page{padding:20px 14px 50px}.actor-header-wrap{flex-direction:column;align-items:stretch;gap:18px;padding:17px;margin-bottom:20px}.avatar-box-master{width:100%;max-width:260px', html)

        # Gallery badge renders count when gallery items exist
        await self.actors.update_one({'_id': ObjectId(self.actor_id)}, {'$set': {'gallery': ['TG_ID:g1', 'TG_ID:g2']}})
        resp2 = await self.client.get(f'/actor/{self.actor_id}')
        self.assertIn('<span class="actor-tab-badge">2</span>', await resp2.text())

    async def test_actor_search_group_filters_and_collections(self):
        await self._seed_media()

        # gf=all: saved group #9 + auto-group (a1,a2,a3) + standalone files (s1, s2)
        r = await self.client.get('/api/actor/search', params={
            'id': self.actor_id, 'gf': 'all', 'col': 'all', 'mode': 'tg', 'group': '1',
        })
        data = await r.json()
        self.assertEqual(r.status, 200, data)
        self.assertTrue(data['is_admin'])
        groups = [x for x in data['results'] if x.get('group')]
        singles = [x for x in data['results'] if not x.get('group')]
        self.assertEqual(len(groups), 2)
        self.assertEqual({x['file_id'] for x in singles}, {'s1', 's2'})
        self.assertTrue(any(x.get('tg_thumb') for x in singles))

        # gf=group: only groups, no standalone files
        r = await self.client.get('/api/actor/search', params={
            'id': self.actor_id, 'gf': 'group', 'col': 'all', 'mode': 'none', 'group': '1',
        })
        data = await r.json()
        self.assertEqual(r.status, 200, data)
        self.assertTrue(all(x.get('group') for x in data['results']))
        self.assertEqual(len(data['results']), 2)
        self.assertTrue(all(not v.get('tg_thumb') for g in data['results'] for v in g['variants']))

        # gf=group + col=primary: only saved group #9 has a member in primary
        r = await self.client.get('/api/actor/search', params={
            'id': self.actor_id, 'gf': 'group', 'col': 'primary', 'mode': 'none', 'group': '1',
        })
        data = await r.json()
        self.assertEqual(r.status, 200, data)
        self.assertEqual([g['gid'] for g in data['results']], ['9'])

        # gf=single (UnGroup): returns individual matching files ungrouped across collections
        # (g2 does not mention Maya/Lin in its own file_name/caption, only in its group name)
        r = await self.client.get('/api/actor/search', params={
            'id': self.actor_id, 'gf': 'single', 'col': 'all', 'mode': 'none', 'group': '0',
        })
        data = await r.json()
        self.assertEqual(r.status, 200, data)
        self.assertTrue(all(not x.get('group') for x in data['results']))
        self.assertEqual({x['file_id'] for x in data['results']}, {'g1', 's1', 'a1', 'a2', 'a3', 's2'})

        # gf=single + col=archive: only archive files
        r = await self.client.get('/api/actor/search', params={
            'id': self.actor_id, 'gf': 'single', 'col': 'archive', 'mode': 'none', 'group': '0',
        })
        data = await r.json()
        self.assertEqual(r.status, 200, data)
        self.assertEqual({x['file_id'] for x in data['results']}, {'a3', 's2'})

    async def test_actor_search_pagination_for_grouped_and_single(self):
        await self._seed_media()
        with patch.object(actor_routes, 'MAX_WEB_RESULTS', 1):
            # Grouped pagination via opaque cursors
            collected, offset, first_cursor = [], '0', None
            for _ in range(8):
                r = await self.client.get('/api/actor/search', params={
                    'id': self.actor_id, 'gf': 'group', 'col': 'all', 'mode': 'none',
                    'group': '1', 'offset': offset,
                })
                data = await r.json()
                self.assertEqual(r.status, 200, data)
                collected.extend(data['results'])
                offset = data['next_offset']
                if first_cursor is None:
                    first_cursor = offset
                if not offset:
                    break
            else:
                self.fail('actor grouped cursor did not terminate')
            self.assertEqual(len(collected), 2)
            self.assertTrue(first_cursor)
            # Cursor bound to actor/col/gf rejects mismatched filter
            bad = await self.client.get('/api/actor/search', params={
                'id': self.actor_id, 'gf': 'all', 'col': 'all', 'mode': 'none',
                'group': '1', 'offset': first_cursor,
            })
            self.assertEqual(bad.status, 400)

            # Single (UnGroup) numeric pagination
            single_ids, off = [], '0'
            for _ in range(10):
                r = await self.client.get('/api/actor/search', params={
                    'id': self.actor_id, 'gf': 'single', 'col': 'all', 'mode': 'none',
                    'group': '0', 'offset': off,
                })
                data = await r.json()
                self.assertEqual(r.status, 200, data)
                single_ids.extend(x['file_id'] for x in data['results'])
                off = str(data['next_offset'] or '')
                if not off:
                    break
            else:
                self.fail('actor single pagination did not terminate')
            self.assertEqual(set(single_ids), {'g1', 's1', 'a1', 'a2', 'a3', 's2'})
            self.assertEqual(len(single_ids), 6)

