"""Regression checks for the optional, removable library-repair plugin."""
import asyncio
import importlib.util
import io
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

for key, value in {
    'API_ID': '1', 'API_HASH': 'test', 'BOT_TOKEN': '1:test', 'ADMINS': '1',
    'LOG_CHANNEL': '-1001', 'BIN_CHANNEL': '-1002',
    'DATABASE_URL': 'mongodb://localhost:27017', 'URL': 'https://example.com',
}.items():
    os.environ.setdefault(key, value)

from hydrogram.errors import BadRequest, FloodWait
from mongomock_motor import AsyncMongoMockClient

# Removing the optional plugin must not make the rest of the test suite fail.
HAS_PLUGIN = importlib.util.find_spec('plugins.repair_library_TEMP') is not None
if HAS_PLUGIN:
    from plugins import repair_library_TEMP as repair


class Video:
    file_id = 'freshfile'
    width = 1280
    height = 720
    duration = 90
    mime_type = 'video/mp4'
    thumbs = [SimpleNamespace(file_id='t' * 30)]


def cached(id=50, media=None):
    media = media or Video()
    return SimpleNamespace(id=id, media=SimpleNamespace(value='video'), video=media, document=None)


@unittest.skipUnless(HAS_PLUGIN, 'optional repair plugin has been removed')
class CombinedRepairTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mongo = AsyncMongoMockClient()
        self.col = self.mongo.test.Primary
        self.status = SimpleNamespace(id=9, chat=SimpleNamespace(id=77), edit=AsyncMock())
        self.run = repair.RepairRun(status=self.status)
        self.photo = SimpleNamespace(photo=SimpleNamespace(file_id='new_photo_id'))
        self.client = SimpleNamespace(send_cached_media=AsyncMock(side_effect=lambda **kw: cached(id=50 + self.client.send_cached_media.await_count)),
                                      download_media=AsyncMock(side_effect=lambda *a, **kw: io.BytesIO(b'thumb')),
                                      send_photo=AsyncMock(return_value=self.photo), delete_messages=AsyncMock(), send_message=AsyncMock())
        self.groups = self.mongo.test.QualityGroups
        self.patches = [patch.object(repair, 'groups', self.groups),
                        patch.object(repair, '_invalidate_search_caches'),
                        patch.object(repair, 'FILE_COLLECTIONS', {'primary': self.col}),
                        patch.object(repair, '_pause', AsyncMock()),
                        patch.object(repair, 'should_probe_media', return_value=True),
                        patch.object(repair, 'probe_telegram_file', AsyncMock(return_value={'w': 1920, 'h': 1080, 'duration': 95}))]
        for p in self.patches: p.start()

    async def asyncTearDown(self):
        for p in reversed(self.patches): p.stop()
        self.mongo.close()
        repair._active_run = None

    async def add(self, ident, **fields):
        await self.col.insert_one({'_id': ident, 'file_ref': f'file-{ident}', 'file_name': 'Movie.mp4',
                                   'file_size': 1000, 'file_type': 'document', **fields})

    async def test_one_scan_repairs_both_and_preserves_web_posters(self):
        await self.add('both')
        await self.add('only_thumb', meta={'v': 2, 'mime': 'video/mp4'})
        await self.add('only_meta', thumb_url='TG_ID:existing')
        await self.add('web', thumb_url='https://example.com/image.jpg', thumb_source='web')
        await self.add('done', thumb_url='NO_THUMB', meta={'v': 2})
        # document+video MIME is intentionally migrated even when v=2
        await self.col.update_one({'_id': 'only_thumb'}, {'$set': {'file_type': 'video'}})
        await self.col.update_one({'_id': 'done'}, {'$set': {'file_type': 'video'}})
        await repair.run_repair(self.client, self.run)
        self.assertEqual(self.run.total, 4)
        self.assertEqual(self.run.scanned, 4)
        self.assertEqual(self.run.meta, 3)
        self.assertEqual(self.run.probed, 3)
        self.assertEqual(self.run.thumbs, 2)
        self.assertEqual(self.client.send_cached_media.await_count, 4)  # overlap fetched only once
        both = await self.col.find_one({'_id': 'both'})
        self.assertEqual((both['meta']['w'], both['meta']['h'], both['duration']), (1920, 1080, 95))
        self.assertEqual(both['file_type'], 'video')
        self.assertEqual(both['thumb_url'], 'TG_ID:new_photo_id')
        self.assertEqual((await self.col.find_one({'_id': 'web'}))['thumb_url'], 'https://example.com/image.jpg')
        self.assertEqual((await self.col.find_one({'_id': 'only_meta'}))['thumb_url'], 'TG_ID:existing')
        self.client.delete_messages.assert_awaited_once()
        self.assertEqual(len(self.client.delete_messages.await_args.args[1]), 4)
        self.assertIn('repair complete', self.status.edit.await_args.args[0])

    async def test_thumbnail_update_refreshes_group_cover_revision_and_cache(self):
        await self.add('covered')
        await self.groups.insert_one({'_id': 1, 'thumb_fid': 'covered', 'thumb_col': 'primary', 'thumb_revision': 'old'})
        await repair.run_repair(self.client, self.run)
        doc = await self.col.find_one({'_id': 'covered'})
        group = await self.groups.find_one({'_id': 1})
        self.assertNotEqual(doc['thumb_revision'], 'old')
        self.assertEqual(group['thumb_revision'], doc['thumb_revision'])
        self.assertGreaterEqual(repair._invalidate_search_caches.call_count, 1)

    async def test_group_revision_failure_is_reported_as_partial(self):
        await self.add('covered')
        with patch.object(self.groups, 'update_many', AsyncMock(side_effect=RuntimeError('offline'))), \
             self.assertLogs('plugins.repair_library_TEMP', level='WARNING'):
            await repair.run_repair(self.client, self.run)
        self.assertEqual((await self.col.find_one({'_id': 'covered'}))['thumb_url'], 'TG_ID:new_photo_id')
        self.assertEqual((self.run.errors, self.run.group_errors), (1, 1))
        self.assertIn('group covers: <code>1</code>', self.status.edit.await_args.args[0])
        self.assertIn('finished with errors', self.status.edit.await_args.args[0])

    async def test_rerun_processes_no_completed_files(self):
        await self.add('one')
        await repair.run_repair(self.client, self.run)
        again = repair.RepairRun(status=self.status)
        await repair.run_repair(self.client, again)
        self.assertEqual(again.total, 0)
        self.assertEqual(self.client.send_cached_media.await_count, 1)

    async def test_missing_media_is_not_marked_as_no_thumbnail(self):
        await self.add('missing-media')
        self.client.send_cached_media.side_effect = None
        self.client.send_cached_media.return_value = SimpleNamespace(id=51, media=None)
        with self.assertLogs('plugins.repair_library_TEMP', level='WARNING'):
            await repair.run_repair(self.client, self.run)
        doc = await self.col.find_one({'_id': 'missing-media'})
        self.assertNotIn('thumb_url', doc)
        self.assertNotIn('meta', doc)
        self.assertEqual(self.run.errors, 1)
        self.client.delete_messages.assert_awaited_once()

    async def test_no_thumbnail_is_marked_and_metadata_still_filled(self):
        await self.add('no-thumb')
        media = Video()
        media.thumbs = []
        self.client.send_cached_media.side_effect = lambda **kw: cached(media=media)
        await repair.run_repair(self.client, self.run)
        doc = await self.col.find_one({'_id': 'no-thumb'})
        self.assertEqual(doc['thumb_url'], 'NO_THUMB')
        self.assertEqual(doc['meta']['v'], 2)
        self.assertEqual((self.run.meta, self.run.no_thumb), (1, 1))
        self.client.send_photo.assert_not_awaited()

    async def test_other_collections_processed_but_actors_excluded(self):
        cloud = self.mongo.test.Cloud
        archive = self.mongo.test.Archive
        actors = self.mongo.test.Actors
        for col in (cloud, archive, actors):
            await col.insert_one({'_id': col.name, 'file_ref': col.name, 'file_name': 'Movie.mp4',
                                  'file_type': 'document', 'file_size': 100})
        with patch.object(repair, 'FILE_COLLECTIONS', {'primary': self.col, 'cloud': cloud, 'archive': archive}):
            await repair.run_repair(self.client, self.run)
        self.assertEqual(self.run.scanned, 2)
        self.assertEqual((await cloud.find_one({'_id': 'Cloud'}))['thumb_url'], 'TG_ID:new_photo_id')
        self.assertEqual((await archive.find_one({'_id': 'Archive'}))['meta']['v'], 2)
        self.assertNotIn('meta', await actors.find_one({'_id': 'Actors'}))

    async def test_web_poster_changed_during_upload_is_not_overwritten(self):
        await self.add('race', meta={'v': 2}, thumb_url='old')
        await self.col.update_one({'_id': 'race'}, {'$set': {'file_type': 'video'}})
        async def upload(**kwargs):
            await self.col.update_one({'_id': 'race'}, {'$set': {'thumb_source': 'web', 'thumb_url': 'web-new'}})
            return self.photo
        self.client.send_photo.side_effect = upload
        await repair.run_repair(self.client, self.run)
        self.assertEqual((await self.col.find_one({'_id': 'race'}))['thumb_url'], 'web-new')
        self.assertEqual(self.run.thumbs, 0)

    async def test_bad_requests_do_not_permanently_mark_files(self):
        await self.add('broken')
        self.client.send_cached_media.side_effect = BadRequest('bad request')
        with self.assertLogs('plugins.repair_library_TEMP', level='WARNING'):
            await repair.run_repair(self.client, self.run)
        doc = await self.col.find_one({'_id': 'broken'})
        self.assertNotIn('thumb_url', doc)
        self.assertNotIn('meta', doc)
        self.assertEqual(self.run.errors, 1)
        self.assertIn('finished with errors', self.status.edit.await_args.args[0])

    async def test_upload_error_preserves_completed_meta_and_remains_retryable(self):
        await self.add('upload')
        self.client.send_photo.side_effect = BadRequest('forbidden')
        with self.assertLogs('plugins.repair_library_TEMP', level='WARNING'):
            await repair.run_repair(self.client, self.run)
        doc = await self.col.find_one({'_id': 'upload'})
        self.assertEqual(doc['meta']['v'], 2)
        self.assertNotIn('thumb_url', doc)
        self.assertEqual(self.run.errors, 1)
        self.client.delete_messages.assert_awaited_once()

    async def test_floodwait_retries_same_file_and_cleans_both_messages(self):
        await self.add('flood')
        self.client.send_photo.side_effect = [FloodWait(1), self.photo]
        await repair.run_repair(self.client, self.run)
        self.assertEqual(self.client.send_cached_media.await_count, 2)
        self.assertEqual((self.run.meta, self.run.thumbs, self.run.errors), (1, 1, 0))
        self.assertEqual(len(self.client.delete_messages.await_args.args[1]), 2)

    async def test_stop_signal_skips_remaining_records_and_cleanup_runs(self):
        await self.add('first')
        await self.add('second')
        async def stop_after_first(*args, **kwargs):
            self.run.stop.set()
            return cached()
        self.client.send_cached_media.side_effect = stop_after_first
        await repair.run_repair(self.client, self.run)
        self.assertEqual(self.client.send_cached_media.await_count, 1)
        self.assertEqual(self.run.scanned, 1)
        self.assertIn('cancelled', self.status.edit.await_args.args[0])
        self.client.delete_messages.assert_awaited_once()

    async def test_failure_to_count_is_reported_as_interrupted(self):
        with patch.object(self.col, 'count_documents', AsyncMock(side_effect=RuntimeError('offline'))), \
             self.assertLogs('plugins.repair_library_TEMP', level='ERROR'):
            await repair.run_repair(self.client, self.run)
        self.assertEqual(self.run.errors, 1)
        self.assertIn('interrupted', self.status.edit.await_args.args[0])

    async def test_cancel_button_is_admin_and_run_scoped(self):
        repair._active_run = self.run
        query = SimpleNamespace(data=f'repair_cancel:{self.run.token}', from_user=SimpleNamespace(id=2),
                                message=self.status, answer=AsyncMock())
        await repair.repair_cancel(None, query)
        self.assertFalse(self.run.stop.is_set())
        query.from_user.id = 1
        query.data = 'repair_cancel:other'
        await repair.repair_cancel(None, query)
        self.assertFalse(self.run.stop.is_set())
        query.data = f'repair_cancel:{self.run.token}'
        await repair.repair_cancel(None, query)
        self.assertTrue(self.run.stop.is_set())

    async def test_only_one_run_and_admin_guard(self):
        gate, entered = asyncio.Event(), asyncio.Event()
        async def work(*args):
            entered.set()
            await gate.wait()
        message = SimpleNamespace(from_user=SimpleNamespace(id=1), reply=AsyncMock(return_value=self.status))
        with patch.object(repair, 'run_repair', side_effect=work):
            task = asyncio.create_task(repair.repair_library_cmd(self.client, message))
            await entered.wait()
            duplicate = SimpleNamespace(from_user=SimpleNamespace(id=1), reply=AsyncMock())
            await repair.repair_library_cmd(self.client, duplicate)
            self.assertIn('already running', duplicate.reply.await_args.args[0])
            outsider = SimpleNamespace(from_user=SimpleNamespace(id=2), reply=AsyncMock())
            await repair.repair_library_cmd(self.client, outsider)
            outsider.reply.assert_not_awaited()
            gate.set()
            await task
        self.assertIsNone(repair._active_run)
