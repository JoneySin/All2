"""Editor, cache, and inline-player regressions using mocked MongoDB/Telegram."""
import asyncio
import html
import io
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

for key, value in {
    "API_ID": "1", "API_HASH": "test", "BOT_TOKEN": "1:test", "ADMINS": "1",
    "LOG_CHANNEL": "-1001", "BIN_CHANNEL": "-1002",
    "DATABASE_URL": "mongodb://localhost:27017", "URL": "https://example.com",
}.items():
    os.environ.setdefault(key, value)

from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer
from bson import ObjectId
from mongomock_motor import AsyncMongoMockClient
from database import ia_filterdb as db
from web import actor_routes as actor
from web import post_routes as post
from web import search_api as api
from web import stream_routes as stream
from web.post_editor import post_image_src
from web.web_assets import build_page


class FakeBot:
    def __init__(self):
        self.send_cached_media = AsyncMock(return_value=SimpleNamespace(id=123))
        self.send_photo = AsyncMock(return_value=SimpleNamespace(photo=SimpleNamespace(file_id="same-photo")))
        self.download_media = AsyncMock(return_value=io.BytesIO(b"image-bytes"))


class EditorPlayerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mongo = AsyncMongoMockClient()
        store = self.mongo["editor_test"]
        self.cols = {n: store[n.capitalize()] for n in ("primary", "cloud", "archive")}
        self.groups, self.actors, self.posts = store.QualityGroups, store.Actors, store.Posts
        self.bot = FakeBot()
        patches = [
            patch.object(db, "primary", self.cols["primary"]), patch.object(db, "cloud", self.cols["cloud"]),
            patch.object(db, "archive", self.cols["archive"]), patch.object(db, "groups", self.groups),
            patch.object(db, "actors", self.actors), patch.object(api, "groups", self.groups),
            patch.object(api, "FILE_COLLECTIONS", self.cols),
            patch.object(api, "COLLECTIONS", {**self.cols, "actors": self.actors}),
            patch.object(api, "get_user_role", AsyncMock(return_value=("admin", 1))),
            patch.object(actor, "actors", self.actors), patch.object(post, "posts_col", self.posts),
            patch.object(actor, "get_auth", AsyncMock(return_value=("admin", 1))),
            patch.object(post, "get_auth", AsyncMock(return_value=("admin", 1))),
            patch.object(actor, "require_active_plan", AsyncMock(return_value=True)),
            patch.object(post, "require_active_plan", AsyncMock(return_value=True)),
            patch.object(api.temp, "BOT", self.bot),
            patch.object(api.db, "add_to_delete_queue", AsyncMock()),
            patch.object(api.db, "track_video_play", AsyncMock()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        api.thumb_cache.clear()
        api._invalidate_search_caches()
        app = web.Application()
        app.add_routes(api.search_routes)
        app.add_routes(actor.actor_routes)
        app.add_routes(post.post_routes)
        app.add_routes(stream.routes)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.mongo.close()

    async def test_inline_setup_signed_ranges_and_normal_download(self):
        await self.cols["primary"].insert_one({"_id": "stored-id", "file_ref": "telegram-ref", "file_name": "movie.mp4"})
        response = await self.client.post('/setup_stream', json={"file_id": "stored-id", "mode": "inline"})
        self.assertEqual(response.status, 200)
        url = (await response.json())["url"]
        self.assertEqual(urlsplit(url).path, '/download/123')
        self.assertEqual(parse_qs(urlsplit(url).query).get('inline'), ['1'])
        self.bot.send_cached_media.assert_awaited_once_with(chat_id=api.BIN_CHANNEL, file_id='telegram-ref')
        api.db.track_video_play.assert_awaited_once()
        info = SimpleNamespace(file_size=1000, file_name='movie.mp4', mime_type='application/octet-stream', is_video=False)
        with patch.object(stream, 'get_media_info', AsyncMock(return_value=info)):
            r = await self.client.head(url, headers={'Range': 'bytes=10-19'})
            self.assertEqual(r.status, 206)
            self.assertEqual(r.headers['Content-Type'], 'video/mp4')
            self.assertTrue(r.headers['Content-Disposition'].startswith('inline;'))
            self.assertEqual(r.headers['Content-Range'], 'bytes 10-19/1000')
            self.assertEqual(r.headers['X-Content-Type-Options'], 'nosniff')
            r = await self.client.head(url.replace('&inline=1', ''))
            self.assertEqual(r.status, 200)
            self.assertTrue(r.headers['Content-Disposition'].startswith('attachment;'))
            info.mime_type = 'text/html'
            r = await self.client.head(url)
            self.assertTrue(r.headers['Content-Disposition'].startswith('attachment;'))
        invalid = await self.client.head('/download/123?e=0&s=bad&inline=1')
        self.assertEqual(invalid.status, 403)

    async def test_setup_still_requires_access(self):
        with patch.object(api, 'get_user_role', AsyncMock(return_value=(None, None))):
            response = await self.client.post('/setup_stream', json={'file_id': 'x', 'mode': 'inline'})
        self.assertEqual(response.status, 403)
        self.bot.send_cached_media.assert_not_awaited()

    async def test_upload_revisions_update_file_and_selected_group_cover(self):
        await self.cols['primary'].insert_one({'_id': 'f1', 'file_name': 'Film', 'thumb_url': 'TG_ID:same-photo'})
        await self.groups.insert_one({'_id': '5', 'members': ['f1'], 'thumb_fid': 'f1', 'thumb_col': 'primary'})
        revisions = []
        for _ in range(2):
            fd = FormData()
            fd.add_field('file_id', 'f1')
            fd.add_field('collection', 'primary')
            fd.add_field('image', b'jpeg', filename='poster.jpg', content_type='image/jpeg')
            response = await self.client.post('/api/upload_thumb', data=fd)
            self.assertEqual(response.status, 200)
            data = await response.json()
            revisions.append(data['thumb_revision'])
            file_doc = await self.cols['primary'].find_one({'_id': 'f1'})
            group_doc = await self.groups.find_one({'_id': '5'})
            self.assertEqual(group_doc['thumb_revision'], file_doc['thumb_revision'])
            file_doc['source_col'] = 'primary'
            self.assertIn('v=' + data['thumb_revision'], api._build_results_list([file_doc], 'tg')[0]['tg_thumb'])
        self.assertNotEqual(revisions[0], revisions[1])

    async def test_thumbnail_partial_failure_is_reported_and_cache_invalidated(self):
        await self.cols['primary'].insert_one({'_id': 'f1', 'file_name': 'Film', 'thumb_url': 'TG_ID:old'})
        api._GH_CACHE['stale'] = (9999999999, ['old'])
        fd = FormData()
        fd.add_field('file_id', 'f1')
        fd.add_field('collection', 'primary')
        fd.add_field('image', b'jpeg', filename='poster.jpg', content_type='image/jpeg')
        with patch.object(self.groups, 'update_many', AsyncMock(side_effect=RuntimeError('group unavailable'))):
            response = await self.client.post('/api/upload_thumb', data=fd)
        self.assertEqual(response.status, 500)
        self.assertTrue((await response.json())['partial'])
        saved = await self.cols['primary'].find_one({'_id': 'f1'})
        self.assertEqual(saved['thumb_url'], 'TG_ID:same-photo')
        self.assertEqual(len(api._GH_CACHE), 0)

    async def test_versioned_thumbnail_cache_cannot_reuse_an_old_revision(self):
        await self.cols['primary'].insert_one({'_id': 'f1', 'thumb_url': 'TG_ID:new'})
        api.thumb_cache['primary:f1:old-version'] = b'old'
        self.bot.download_media.return_value = io.BytesIO(b'new')
        response = await self.client.get('/api/thumb?file_id=f1&col=primary&v=new-version')
        self.assertEqual(await response.read(), b'new')
        self.bot.download_media.assert_awaited_once()

    async def test_slow_original_thumb_cannot_overwrite_admin_upload(self):
        await self.cols['primary'].insert_one({'_id': 'race', 'file_ref': 'ref-race', 'thumb_url': 'TG_ID:old'})
        entered, release = asyncio.Event(), asyncio.Event()

        async def send(*args, **kwargs):
            entered.set()
            await release.wait()
            return SimpleNamespace(id=99, video=SimpleNamespace(thumbs=[SimpleNamespace(file_id='original')]), document=None)

        async def download(fid, **kwargs):
            if fid == 'old':
                return None
            return io.BytesIO(b'original-bytes')

        self.bot.send_cached_media.side_effect = send
        self.bot.download_media.side_effect = download
        with patch.object(api, '_backfill_duration', AsyncMock()), patch.object(api, '_backfill_media_meta', AsyncMock()):
            task = asyncio.create_task(api._get_or_fetch_thumb('race', 'primary', version='old'))
            await asyncio.wait_for(entered.wait(), 2)
            await self.cols['primary'].update_one({'_id': 'race'}, {'$set': {
                'thumb_url': 'TG_ID:admin', 'thumb_revision': 'new', 'is_thumb_permanent': True}})
            release.set()
            await asyncio.wait_for(task, 2)
        self.assertEqual((await self.cols['primary'].find_one({'_id': 'race'}))['thumb_url'], 'TG_ID:admin')

    async def test_prefetch_in_flight_is_not_recached_after_edit(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def stale_page(*args, **kwargs):
            entered.set()
            await release.wait()
            return ([{'_id': 'f1', 'file_name': 'old'}], '')

        with patch.object(api, '_fetch_page', stale_page):
            task = asyncio.create_task(api.bg_prefetch_worker(1, 'film', 'all', 'none', 21, 21))
            await asyncio.wait_for(entered.wait(), 2)
            api._invalidate_search_caches()
            release.set()
            await asyncio.wait_for(task, 2)
        self.assertEqual(len(api.PREFETCH_CACHE), 0)

    async def test_metadata_edit_invalidates_all_search_caches(self):
        await self.cols['primary'].insert_one({'_id': 'f1', 'file_name': 'Old', 'caption': 'old'})
        api._GH_CACHE['x'] = (9999999999, ['old'])
        api._SIB_CACHE['x'] = (9999999999, ['old'])
        api.TRENDING_CACHE['x'] = {'results': ['old']}
        response = await self.client.post('/api/edit_name', json={
            'file_id': 'f1', 'collection': 'primary', 'target_collection': 'primary',
            'new_name': 'New', 'add_caption': 'updated tags'})
        self.assertTrue((await response.json())['success'])
        doc = await self.cols['primary'].find_one({'_id': 'f1'})
        self.assertEqual((doc['file_name'], doc['caption']), ('New', 'updated tags'))
        self.assertEqual((len(api._GH_CACHE), len(api._SIB_CACHE), len(api.TRENDING_CACHE)), (0, 0, 0))

    async def test_file_editor_quality_and_authoritative_group(self):
        await self.cols['primary'].insert_one({'_id': 'f1', 'file_name': 'Old 480p.mkv', 'caption': 'old',
                                               'meta': {'w': 1280, 'h': 720}, 'group_id': 'stale'})
        await self.groups.insert_one({'_id': '7', 'num': 7, 'members': ['f1', 'f2'], 'name': 'Group'})
        response = await self.client.get('/api/file/editor?file_id=f1&collection=primary')
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.json(), {'group_id': '7', 'quality_override': '', 'detected_quality': '1280×720'})
        payload = {'file_id': 'f1', 'collection': 'primary', 'target_collection': 'cloud',
                   'new_name': 'New 480p.mkv', 'add_caption': 'tags', 'quality_override': '1080p'}
        r = await self.client.post('/api/edit_name', json=payload)
        self.assertEqual(r.status, 200)
        doc = await self.cols['cloud'].find_one({'_id': 'f1'})
        self.assertEqual(doc['quality_override'], '1080p')
        self.assertEqual(doc['meta'], {'w': 1280, 'h': 720})
        self.assertIsNone(await self.cols['primary'].find_one({'_id': 'f1'}))
        rows = await db.get_files_by_ids(['f1'])
        self.assertEqual(api._build_results_list(rows, 'none')[0]['res'], '1080p')
        self.assertEqual(api._build_results_list(rows, 'none')[0]['quality_override'], '1080p')
        grouped = api.group_results([api._build_results_list(rows, 'none')[0],
                                     {'file_id': 'f2', 'name': 'Other', 'res': '640×360'}],
                                    manual={'f1': {'_id': '7', 'name': 'Group', 'members': ['f1', 'f2']},
                                            'f2': {'_id': '7', 'name': 'Group', 'members': ['f1', 'f2']}})
        self.assertEqual(next(v for v in grouped[0]['variants'] if v['file_id'] == 'f1')['ql'], '1080p')
        preview = await self.client.get('/api/group/preview?id=7')
        self.assertEqual((await preview.json())['group']['members'][0]['label'], '1080p')
        before = await self.cols['cloud'].find_one({'_id': 'f1'})
        payload.update(collection='cloud', target_collection='cloud', quality_override='x' * 41)
        r = await self.client.post('/api/edit_name', json=payload)
        self.assertEqual(r.status, 400)
        self.assertEqual(await self.cols['cloud'].find_one({'_id': 'f1'}), before)
        payload['quality_override'] = ''
        r = await self.client.post('/api/edit_name', json=payload)
        self.assertEqual(r.status, 200)
        self.assertNotIn('quality_override', await self.cols['cloud'].find_one({'_id': 'f1'}))
        self.assertEqual((await db.get_files_by_ids(['f1']))[0]['meta']['h'], 720)
        with patch.object(api, 'get_user_role', AsyncMock(return_value=('user', 2))):
            self.assertEqual((await self.client.get('/api/file/editor?file_id=f1&collection=cloud')).status, 403)
            self.assertEqual((await self.client.post('/api/edit_name', json=payload)).status, 403)

    async def test_profile_forms_and_avatar_revision(self):
        aid = ObjectId()
        await self.actors.insert_one({'_id': aid, 'name': 'A "Name"', 'bio': 'Biography', 'category': 'actor',
                                      'tags': ['Film'], 'photo_url': 'TG_ID:old', 'created_at': 1, 'gallery': []})
        create = await self.client.get('/admin/create_actor')
        self.assertEqual(create.status, 200)
        self.assertIn('Create a profile', await create.text())
        profile = await self.client.get(f'/actor/{aid}')
        body = await profile.text()
        self.assertEqual(profile.status, 200)
        self.assertIn('Edit profile', body)
        self.assertIn('name="name" value="A &quot;Name&quot;"', body)
        self.assertNotIn('Change Avatar', body)
        self.assertNotIn('avatarUpdateInput', body)
        self.assertIn('onchange="updateActorAvatar(', body)
        revisions = []
        for _ in range(2):
            fd = FormData()
            fd.add_field('actor_id', str(aid))
            fd.add_field('photo', b'jpeg', filename='portrait.jpg', content_type='image/jpeg')
            r = await self.client.post('/api/actor/update_avatar', data=fd)
            self.assertEqual(r.status, 200)
            revisions.append((await r.json())['photo_revision'])
        self.assertNotEqual(*revisions)
        self.assertEqual((await self.actors.find_one({'_id': aid}))['photo_revision'], revisions[-1])

    async def test_profile_links_create_edit_legacy_and_clear(self):
        aid = ObjectId()
        await self.actors.insert_one({'_id': aid, 'name': 'Original', 'bio': 'Biography', 'category': 'actor',
                                      'social_links': {'instagram': 'instagram.com/old', 'youtube': 'https://youtube.com/old',
                                                       'twitter': '', 'website': 'https://example.org/path'},
                                      'photo_url': 'TG_ID:old', 'gallery': []})
        profile = await self.client.get(f'/actor/{aid}')
        body = await profile.text()
        self.assertIn('value="https://instagram.com/old"', body)
        self.assertIn('value="https://example.org/path"', body)
        self.assertIn('>Instagram</a>', body)
        self.assertIn('>website</a>', body)

        # Legacy clients that do not submit link fields must not clear them.
        response = await self.client.post('/api/actor/update_profile', data={
            'actor_id': str(aid), 'name': 'Still here', 'bio': 'Biography'}, headers={'Accept': 'application/json'})
        self.assertEqual(response.status, 200)
        self.assertEqual((await self.actors.find_one({'_id': aid}))['social_links']['website'], 'https://example.org/path')

        rows = [('Instagram', 'instagram.com/old'), ('Shop <official>', 'https://shop.example/a?x=1&y=2'),
                ('', 'news.example:8443/path'), ('Long', 'https://example.com/' + 'x' * 500)]
        rows += [(f'Extra {i}', f'https://example.net/{i}') for i in range(12)]
        form = FormData()
        for key, value in [('actor_id', str(aid)), ('name', 'Updated'), ('bio', 'Biography'), ('links_present', '1')]:
            form.add_field(key, value)
        for label, url in rows:
            form.add_field('link_label', label)
            form.add_field('link_url', url)
        response = await self.client.post('/api/actor/update_profile', data=form, headers={'Accept': 'application/json'})
        self.assertEqual(response.status, 200, await response.text())
        saved = await self.actors.find_one({'_id': aid})
        self.assertEqual(len(saved['profile_links']), len(rows))
        self.assertEqual(saved['profile_links'][0]['url'], 'https://instagram.com/old')
        self.assertEqual(saved['profile_links'][2], {'label': 'news.example', 'url': 'https://news.example:8443/path'})
        self.assertEqual(saved['profile_links'][3]['url'], rows[3][1])
        profile = await self.client.get(f'/actor/{aid}')
        body = await profile.text()
        self.assertIn('>Shop &lt;official&gt;</a>', body)
        self.assertIn('href="https://shop.example/a?x=1&amp;y=2"', body)
        self.assertIn('rel="noopener noreferrer"', body)
        self.assertNotIn('>website</a>', body)  # Removed in the editor.
        actor.get_auth.return_value = ('user', 9)
        public_body = await (await self.client.get(f'/actor/{aid}')).text()
        self.assertIn('>Shop &lt;official&gt;</a>', public_body)
        self.assertNotIn('id="actorEditModal"', public_body)
        actor.get_auth.return_value = ('admin', 1)
        # An old client updating Instagram must not discard custom links.
        response = await self.client.post('/api/actor/update_profile', data={
            'actor_id': str(aid), 'name': 'Updated', 'bio': 'Biography', 'insta': 'https://instagram.com/new'},
            headers={'Accept': 'application/json'})
        self.assertEqual(response.status, 200)
        updated = (await self.actors.find_one({'_id': aid}))['profile_links']
        self.assertEqual(len(updated), len(rows))
        self.assertIn({'label': 'Instagram', 'url': 'https://instagram.com/new'}, updated)
        self.assertIn({'label': 'Shop <official>', 'url': 'https://shop.example/a?x=1&y=2'}, updated)

        # Empty link list really clears legacy links rather than restoring them.
        response = await self.client.post('/api/actor/update_profile', data={
            'actor_id': str(aid), 'name': 'Updated', 'bio': 'Biography', 'links_present': '1'},
            headers={'Accept': 'application/json'})
        self.assertEqual(response.status, 200)
        self.assertEqual((await self.actors.find_one({'_id': aid}))['profile_links'], [])
        body = await (await self.client.get(f'/actor/{aid}')).text()
        self.assertNotIn('>Instagram</a>', body)

    async def test_profile_links_validate_without_partial_writes_and_authorize(self):
        aid = ObjectId()
        old = [{'label': 'Safe', 'url': 'https://example.com/'}]
        await self.actors.insert_one({'_id': aid, 'name': 'Old', 'bio': 'Biography', 'profile_links': old})
        for bad in ('javascript:alert(1)', 'data:text/html,evil', 'https://', 'https://example.com/\\nevil', 'https://user@example.com'):
            form = FormData()
            for key, value in [('actor_id', str(aid)), ('name', 'Changed'), ('bio', 'Biography'),
                               ('links_present', '1'), ('link_label', 'Unsafe'), ('link_url', bad)]:
                form.add_field(key, value)
            response = await self.client.post('/api/actor/update_profile', data=form, headers={'Accept': 'application/json'})
            self.assertEqual(response.status, 400, bad)
            saved = await self.actors.find_one({'_id': aid})
            self.assertEqual((saved['name'], saved['profile_links']), ('Old', old))
        malformed = FormData()
        for key, value in [('actor_id', str(aid)), ('name', 'Changed'), ('bio', 'Biography'),
                           ('links_present', '1'), ('link_label', 'Missing URL')]:
            malformed.add_field(key, value)
        response = await self.client.post('/api/actor/update_profile', data=malformed, headers={'Accept': 'application/json'})
        self.assertEqual(response.status, 400)
        actor.get_auth.return_value = ('user', 9)
        response = await self.client.post('/api/actor/update_profile', data={'actor_id': str(aid)})
        self.assertEqual(response.status, 403)

    async def test_profile_create_rejects_invalid_links_before_photo_upload(self):
        form = FormData()
        for key, value in [('name', 'Profile'), ('bio', 'Biography'), ('links_present', '1'),
                           ('link_label', 'Bad'), ('link_url', 'javascript:alert(1)')]:
            form.add_field(key, value)
        form.add_field('photo', b'jpeg', filename='portrait.jpg', content_type='image/jpeg')
        response = await self.client.post('/api/create_actor', data=form, headers={'Accept': 'application/json'})
        self.assertEqual(response.status, 400)
        self.assertEqual(self.bot.send_photo.await_count, 0)
        self.assertEqual(await self.actors.count_documents({}), 0)

    async def test_profile_create_with_multiple_universal_links(self):
        form = FormData()
        for key, value in [('name', 'Profile'), ('bio', 'Biography'), ('category', 'website'), ('links_present', '1')]:
            form.add_field(key, value)
        for label, url in [('Shop', 'shop.example'), ('Blog', 'https://blog.example'), ('Social', 'https://x.com/user')]:
            form.add_field('link_label', label)
            form.add_field('link_url', url)
        form.add_field('photo', b'jpeg', filename='portrait.jpg', content_type='image/jpeg')
        response = await self.client.post('/api/create_actor', data=form, headers={'Accept': 'application/json'})
        self.assertEqual(response.status, 200, await response.text())
        saved = await self.actors.find_one({'name': 'Profile'})
        self.assertEqual(saved['profile_links'], [{'label': 'Shop', 'url': 'https://shop.example'},
                                                  {'label': 'Blog', 'url': 'https://blog.example'},
                                                  {'label': 'Social', 'url': 'https://x.com/user'}])

    async def test_profile_json_edit_and_upload_failure_are_reported(self):
        aid = ObjectId()
        await self.actors.insert_one({'_id': aid, 'name': 'Old', 'bio': 'Old bio', 'category': 'actor'})
        response = await self.client.post('/api/actor/update_profile', data={
            'actor_id': str(aid), 'name': 'Updated', 'bio': 'New bio', 'category': 'actor', 'tags': 'one, two'},
            headers={'Accept': 'application/json'})
        self.assertTrue((await response.json())['success'])
        saved = await self.actors.find_one({'_id': aid})
        self.assertEqual((saved['name'], saved['bio'], saved['tags']), ('Updated', 'New bio', ['one', 'two']))
        response = await self.client.post('/api/actor/update_profile', data={
            'actor_id': str(aid), 'name': '', 'bio': 'New bio'}, headers={'Accept': 'application/json'})
        self.assertEqual(response.status, 400)
        self.assertEqual((await self.actors.find_one({'_id': aid}))['name'], 'Updated')

        self.bot.send_photo.return_value = SimpleNamespace(photo=None)
        fd = FormData()
        for key, value in [('name', 'Another'), ('bio', 'Biography'), ('category', 'actor')]:
            fd.add_field(key, value)
        fd.add_field('photo', b'jpeg', filename='portrait.jpg', content_type='image/jpeg')
        response = await self.client.post('/api/create_actor', data=fd, headers={'Accept': 'application/json'})
        self.assertEqual(response.status, 500)
        self.assertIn('upload failed', (await response.json())['error'].lower())
        self.assertEqual(await self.actors.count_documents({}), 1)

    async def test_gallery_deletes_only_one_duplicate_and_always_changes_revision(self):
        aid = ObjectId()
        await self.actors.insert_one({'_id': aid, 'gallery': ['TG_ID:same', 'TG_ID:same', 'TG_ID:last']})
        first = await self.client.post('/api/actor/gallery_delete', json={'actor_id': str(aid), 'index': 0})
        self.assertTrue((await first.json())['success'])
        doc = await self.actors.find_one({'_id': aid})
        self.assertEqual(doc['gallery'], ['TG_ID:same', 'TG_ID:last'])
        revision = doc['gallery_revision']
        second = await self.client.post('/api/actor/gallery_delete', json={'actor_id': str(aid), 'index': 0})
        self.assertTrue((await second.json())['success'])
        doc = await self.actors.find_one({'_id': aid})
        self.assertEqual(doc['gallery'], ['TG_ID:last'])
        self.assertNotEqual(doc['gallery_revision'], revision)

    async def test_gallery_concurrent_change_is_not_overwritten(self):
        aid = ObjectId()
        await self.actors.insert_one({'_id': aid, 'gallery': ['a', 'b']})
        real_update = self.actors.update_one

        async def concurrent_update(query, update):
            await real_update({'_id': aid}, {'$push': {'gallery': 'new'}})
            return await real_update(query, update)

        with patch.object(self.actors, 'update_one', side_effect=concurrent_update):
            self.assertFalse(await db.delete_gallery_image_by_index(str(aid), 0))
        self.assertEqual((await self.actors.find_one({'_id': aid}))['gallery'], ['a', 'b', 'new'])

    async def test_post_edit_keeps_existing_media_and_escapes_values(self):
        pid = ObjectId()
        original = {'_id': pid, 'title': 'Old', 'description': 'old', 'category': 'Movies',
                    'cover_image': 'TG_ID:cover', 'screenshots': ['TG_ID:one', 'TG_ID:two'],
                    'videos': [{'file_id': 'first', 'heading': 'Episode 1', 'custom_name': '720p'},
                               {'file_id': 'second', 'heading': 'Episode 2', 'custom_name': '1080p'}], 'tags': ['one']}
        await self.posts.insert_one(original)
        response = await self.client.get(f'/admin/edit_post/{pid}')
        body = await response.text()
        self.assertEqual(response.status, 200)
        self.assertIn('value="TG_ID:cover"', body)
        self.assertIn('TG_ID:one\nTG_ID:two', body)
        self.assertIn('value="first"', body)
        self.assertIn('value="second"', body)

        fd = FormData()
        for key, value in [('post_id', str(pid)), ('title', 'Updated'), ('description', 'New description'),
                           ('category', 'Web Series'), ('tags', 'one, two'), ('cover_url', 'TG_ID:cover'),
                           ('screenshot_urls', 'TG_ID:one\nTG_ID:two'),
                           ('video_id', 'second'), ('video_heading', 'Episode 2'), ('video_name', '1080p'),
                           ('video_id', 'first'), ('video_heading', 'Episode 1'), ('video_name', '720p')]:
            fd.add_field(key, value)
        fd.add_field('cover_file', b'', filename='', content_type='application/octet-stream')
        response = await self.client.post('/api/post/update', data=fd, allow_redirects=False)
        self.assertEqual(response.status, 302)
        updated = await self.posts.find_one({'_id': pid})
        self.assertEqual(updated['cover_image'], 'TG_ID:cover')
        self.assertEqual(updated['screenshots'], ['TG_ID:one', 'TG_ID:two'])
        self.assertEqual([v['file_id'] for v in updated['videos']], ['second', 'first'])
        self.assertEqual(updated['title'], 'Updated')

        bad = '</textarea><script>window.injected=1</script>'
        await self.posts.update_one({'_id': pid}, {'$set': {'description': bad, 'cover_image': '" onerror="bad'}})
        body = await (await self.client.get(f'/admin/edit_post/{pid}')).text()
        self.assertIn(html.escape(bad), body)
        self.assertNotIn(bad, body)
        self.assertIn('value="&quot; onerror=&quot;bad"', body)

    async def test_post_upload_failure_returns_json_without_changing_existing_post(self):
        pid = ObjectId()
        await self.posts.insert_one({'_id': pid, 'title': 'Original', 'description': 'Original description',
                                     'cover_image': 'TG_ID:old', 'screenshots': ['TG_ID:old-shot'], 'videos': []})
        self.bot.send_photo.return_value = SimpleNamespace(photo=None)
        fd = FormData()
        for key, value in [('post_id', str(pid)), ('title', 'Changed'), ('description', 'Changed description'),
                           ('cover_url', 'TG_ID:old'), ('screenshot_urls', 'TG_ID:old-shot')]:
            fd.add_field(key, value)
        fd.add_field('cover_file', b'jpeg', filename='cover.jpg', content_type='image/jpeg')
        response = await self.client.post('/api/post/update', data=fd, headers={'Accept': 'application/json'})
        self.assertEqual(response.status, 500)
        self.assertIn('upload failed', (await response.json())['error'].lower())
        unchanged = await self.posts.find_one({'_id': pid})
        self.assertEqual(unchanged['title'], 'Original')
        self.assertEqual(unchanged['screenshots'], ['TG_ID:old-shot'])

    async def test_post_new_screenshots_append_after_existing(self):
        pid = ObjectId()
        await self.posts.insert_one({'_id': pid, 'title': 'Old', 'description': 'Old', 'cover_image': 'TG_ID:cover'})
        fd = FormData()
        for key, value in [('post_id', str(pid)), ('title', 'New'), ('description', 'New description'),
                           ('cover_url', 'TG_ID:cover'), ('screenshot_urls', 'TG_ID:first\nTG_ID:second')]:
            fd.add_field(key, value)
        fd.add_field('screenshot_files', b'jpeg', filename='new.jpg', content_type='image/jpeg')
        response = await self.client.post('/api/post/update', data=fd, headers={'Accept': 'application/json'})
        data = await response.json()
        self.assertTrue(data['success'])
        self.assertIn(str(pid), data['redirect'])
        saved = await self.posts.find_one({'_id': pid})
        self.assertEqual(saved['screenshots'], ['TG_ID:first', 'TG_ID:second', 'TG_ID:same-photo'])

    async def test_empty_posts_directory_has_grid_and_unsafe_images_are_rejected(self):
        response = await self.client.get('/posts')
        self.assertEqual(response.status, 200)
        self.assertIn('id="post_grid_container"', await response.text())
        self.assertEqual(post_image_src('javascript:alert(1)'), '')
        self.assertEqual(post_image_src('//evil.test/image'), '')
        self.assertEqual(post_image_src('TG_ID:abc+123'), '/api/post/photo?id=abc%2B123')

    def test_legacy_categories_stay_selected_in_editors(self):
        fields = actor.actor_form_fields(category='legacy & unusual')
        self.assertIn('<option value="legacy &amp; unusual" selected>', fields)
        body = post.build_post_editor({'category': 'Legacy & Other'}, post_id=str(ObjectId()))
        self.assertIn('<option value="Legacy &amp; Other" selected>', body)

    async def test_shared_brand_renders_on_landing_and_watch_page(self):
        from web.utils import render_template
        info = SimpleNamespace(mime_type='video/mp4', file_name='Video.mp4')
        with patch.object(render_template, 'get_media_info', AsyncMock(return_value=info)):
            watch = await render_template.media_watch(123)
        self.assertIn('brand-mark', watch)
        self.assertIn('<span class="brand-mark" aria-hidden="true">F</span><span class="brand-word">FAST FINDER</span>', watch)
        self.assertNotIn('__BRAND_', watch)
        self.assertIn('Video.mp4', watch)
        with patch.object(stream, 'get_auth', AsyncMock(return_value=(None, None))):
            response = await self.client.get('/')
            landing = await response.text()
        self.assertIn('<span class="brand-mark" aria-hidden="true">F</span><span class="brand-word">FAST FINDER</span>', landing)
        self.assertNotIn('__BRAND_', landing)

    def test_navigation_icons_keep_admin_permissions_and_labels(self):
        admin = build_page('Home', '', active_tab='dash', role='admin').text
        user = build_page('Home', '', active_tab='dash', role='user').text
        for icon in ('🏠', '📝', '🎭', '📊', '⚙️', '🚪'):
            self.assertIn(icon, admin)
        self.assertNotIn('href="/stats"', user)
        self.assertIn('href="/dashboard" class="sb-link active"', user)
        self.assertIn('aria-label="FastFinder home"', admin)

    def test_shared_page_title_is_escaped_and_player_only_for_authenticated_users(self):
        admin = build_page('<script>bad</script>', '', role='admin').text
        guest = build_page('Guest', '', role=None).text
        self.assertIn('&lt;script&gt;bad&lt;/script&gt;', admin)
        self.assertIn('id="inlinePlayer"', admin)
        self.assertNotIn('id="inlinePlayer"', guest)


if __name__ == '__main__':
    unittest.main()
