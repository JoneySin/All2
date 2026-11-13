"""Bot spelling suggestions must be relevant, local, and searchable."""
import asyncio
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

from mongomock_motor import AsyncMongoMockClient
from database import ia_filterdb as db
from plugins import filter as bot_filter
from utils import temp


class DatabaseSuggestionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mongo = AsyncMongoMockClient()
        store = self.mongo.test
        self.cols = [store.Primary, store.Cloud, store.Archive]
        self.patches = [patch.object(db, name, col) for name, col in zip(('primary', 'cloud', 'archive'), self.cols)]
        self.patches.append(patch.object(db, 'COLLECTIONS', dict(zip(('primary', 'cloud', 'archive'), self.cols))))
        # mongomock doesn't implement Mongo $text. Exercise the actual bot
        # search/pagination path with its regex filter while candidate lookup
        # independently tests its timeout-bounded regex fallback.
        self.patches.append(patch.object(db, 'build_query_filter', lambda raw, regex, lang=None: ({'file_name': regex}, False) if regex else (None, False)))
        for p in self.patches: p.start()

    async def asyncTearDown(self):
        for p in reversed(self.patches): p.stop()
        self.mongo.close()

    async def add(self, col, name, id):
        await self.cols[col].insert_one({'_id': id, 'file_name': name, 'file_size': 100, 'file_ref': id})

    async def test_typo_near_start_ranking_and_real_search_verification(self):
        await self.add(0, 'Avengers Endgame 1080p.mkv', 'a')
        await self.add(1, 'Avengers Age of Ultron 720p.mkv', 'b')
        await self.add(2, 'Avengers Endgame 1080p.mkv', 'duplicate')
        await self.add(0, 'The Endgame of Chess.mp4', 'c')
        suggestions = await db.get_db_spell_suggestions('Xvengers Endgme')
        self.assertEqual(suggestions, ['Avengers Endgame 1080p.mkv'])
        for suggestion in suggestions:
            files, _, _, _ = await db.get_search_results(suggestion, 12, 0, collection_type='all')
            self.assertTrue(files)

    async def test_fuzzy_typo_across_collections_and_unrelated_excluded(self):
        await self.add(0, 'Hoot 2020 1080p.mkv', 'a')
        await self.add(1, 'Hook 1991 720p.mkv', 'b')
        await self.add(2, 'Avengers Endgame 2020.mkv', 'c')
        suggestions = await db.get_db_spell_suggestions('Hootx')
        self.assertEqual(suggestions[0], 'Hoot 2020 1080p.mkv')
        self.assertNotIn('Avengers Endgame 2020.mkv', suggestions)
        self.assertEqual(await db.get_db_spell_suggestions('qqqqqqqq'), [])
        self.assertEqual(await db.get_db_spell_suggestions('x' * 121), [])

    async def test_candidates_without_searchable_results_are_rejected(self):
        await self.add(0, 'Hoot 2020.mkv', 'a')
        await self.add(1, 'Hoot 2019.mkv', 'b')
        async def verify(title, *args, **kwargs):
            if '2020' in title:
                return ([], '', 0, 'None')
            return ([{'_id': 'b'}], '', 1, 'Cloud')
        with patch.object(db, 'get_search_results', AsyncMock(side_effect=verify)):
            self.assertEqual(await db.get_db_spell_suggestions('Hootx'), ['Hoot 2019.mkv'])
        with patch.object(db, 'get_search_results', AsyncMock(side_effect=RuntimeError('offline'))):
            self.assertEqual(await db.get_db_spell_suggestions('Hootx'), [])

    async def test_single_collection_and_combining_marks(self):
        self.assertEqual(db._spell_words('कहानी', 8), ['कहानी'])
        await self.add(0, 'Kahani 2012.mkv', 'a')
        await self.add(1, 'Kahani 2016.mkv', 'b')
        self.assertEqual(await db.get_db_spell_suggestions('Kahanix', collection_type='cloud'), ['Kahani 2016.mkv'])

    async def test_server_query_is_bounded_and_escaped(self):
        self.assertLessEqual(len(db._spell_fragments(db._spell_words('abcdefgh ijklmnop qrstuvwx yzabcd', 8))), 9)
        self.assertEqual(db._spell_fragments(['ab']), [])
        self.assertNotIn('.*', db._spell_fragments(db._spell_words('foo.*bar', 8)))
        self.assertEqual(db._SPELL_CANDIDATES_PER_COLLECTION, 50)
        self.assertGreater(db._SPELL_MAX_TIME_MS, 0)


class BotSuggestionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        bot_filter.SPELL_SUGGESTIONS.clear()
        bot_filter.BUTTONS.clear()
        temp.FILES.clear()

    async def test_database_only_even_when_empty(self):
        with patch.object(bot_filter, 'get_db_spell_suggestions', AsyncMock(return_value=[])) as lookup:
            self.assertEqual(await bot_filter.get_spell_suggestions('helo'), [])
        lookup.assert_awaited_once_with('helo', limit=5)
        self.assertFalse(hasattr(bot_filter, 'get_google_spell_suggestions'))

    async def test_group_and_pm_show_only_owned_searchable_buttons_and_respect_settings(self):
        for chat_id in (123, -10099):
            reply = SimpleNamespace(chat=SimpleNamespace(id=chat_id), id=77, edit_text=AsyncMock())
            msg = SimpleNamespace(text='Hootx', chat=SimpleNamespace(id=chat_id), from_user=SimpleNamespace(id=5, mention='User'), reply=AsyncMock(return_value=reply))
            with patch.object(bot_filter, 'get_search_results', AsyncMock(return_value=([], '', 0, 'None'))), \
                 patch.object(bot_filter, 'get_spell_suggestions', AsyncMock(return_value=['Hoot 2020.mkv'])) as get_s, \
                 patch.object(bot_filter, 'start_auto_delete_timer', AsyncMock()):
                await bot_filter.auto_filter(None, msg, settings={'spell_check': True})
                await asyncio.sleep(0)
            get_s.assert_awaited_once()
            button = reply.edit_text.await_args.kwargs['reply_markup'].inline_keyboard[0][0]
            self.assertEqual(button.callback_data, f'spellchk_5_{chat_id}-77_0')
            self.assertEqual(button.text, '🔍 Hoot 2020.mkv')
            with patch.object(bot_filter, 'get_search_results', AsyncMock(return_value=([], '', 0, 'None'))), \
                 patch.object(bot_filter, 'get_spell_suggestions', AsyncMock()) as off, \
                 patch.object(bot_filter, 'start_auto_delete_timer', AsyncMock()):
                await bot_filter.auto_filter(None, msg, settings={'spell_check': False})
                await asyncio.sleep(0)
            off.assert_not_awaited()

    async def test_callback_owner_expiry_and_deleted_file(self):
        message = SimpleNamespace(chat=SimpleNamespace(id=-10099), id=77, edit_text=AsyncMock())
        bot_filter.SPELL_SUGGESTIONS['-10099-77'] = ['Hoot 2020.mkv']
        query = SimpleNamespace(data='spellchk_5_-10099-77_0', from_user=SimpleNamespace(id=6), message=message, answer=AsyncMock())
        await bot_filter.spell_check_handler(None, query)
        self.assertIn('not for you', query.answer.await_args.args[0])
        query.from_user.id = 5
        for data in ('spellchk_5_-10099-77_-1', 'spellchk_5_-10099-78_0', 'spellchk_5_-10099-77_5'):
            query.data = data
            await bot_filter.spell_check_handler(None, query)
            self.assertIn('expired', query.answer.await_args.args[0])
        query.data = 'spellchk_5_-10099-77_0'
        with patch.object(bot_filter, 'IS_PREMIUM', False), patch.object(bot_filter, 'get_search_results', AsyncMock(return_value=([], '', 0, 'None'))):
            await bot_filter.spell_check_handler(None, query)
        self.assertIn('no longer available', message.edit_text.await_args.args[0])

    async def test_callback_database_error_preserves_buttons_for_retry(self):
        message = SimpleNamespace(chat=SimpleNamespace(id=123), id=77, edit_text=AsyncMock())
        bot_filter.SPELL_SUGGESTIONS['123-77'] = ['Hoot 2020.mkv']
        query = SimpleNamespace(data='spellchk_5_123-77_0', from_user=SimpleNamespace(id=5), message=message, answer=AsyncMock())
        with patch.object(bot_filter, 'IS_PREMIUM', False), \
             patch.object(bot_filter, 'get_search_results', AsyncMock(side_effect=RuntimeError('offline'))), \
             self.assertLogs('plugins.filter', level='ERROR'):
            await bot_filter.spell_check_handler(None, query)
        query.answer.assert_awaited_once()
        message.edit_text.assert_not_awaited()
        self.assertEqual(bot_filter.SPELL_SUGGESTIONS['123-77'], ['Hoot 2020.mkv'])

    async def test_callback_uses_full_filename_and_result_ui(self):
        title = 'Hoot ' + 'x' * 220 + '.mkv'
        message = SimpleNamespace(chat=SimpleNamespace(id=123), id=77, edit_text=AsyncMock())
        bot_filter.SPELL_SUGGESTIONS['123-77'] = [title]
        query = SimpleNamespace(data='spellchk_5_123-77_0', from_user=SimpleNamespace(id=5), message=message, answer=AsyncMock())
        files = [{'_id': 'file1', 'file_name': title, 'file_size': 100}]
        with patch.object(bot_filter, 'IS_PREMIUM', False), \
             patch.object(bot_filter, 'get_search_results', AsyncMock(return_value=(files, '', 1, 'Primary'))) as search, \
             patch.object(bot_filter, 'get_settings', AsyncMock(return_value={'simple_mode': True})), \
             patch.object(bot_filter, 'get_filter_ui', return_value=('results', None)), \
             patch.object(bot_filter, 'start_auto_delete_timer', AsyncMock()):
            await bot_filter.spell_check_handler(None, query)
            await asyncio.sleep(0)
        self.assertEqual(search.await_args.args[0], title)
        self.assertEqual(bot_filter.BUTTONS['123-77']['query'], title)
        self.assertEqual(message.edit_text.await_args.args[0], 'results')
        self.assertLessEqual(len(query.answer.await_args.args[0]), 200)


class SuggestionLoadTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_lookups_are_bounded_and_recover(self):
        started, release = asyncio.Event(), asyncio.Event()
        count = 0
        async def slow(*args):
            nonlocal count
            count += 1
            if count == 2:
                started.set()
            await release.wait()
            return ['available']
        with patch.object(db, '_find_db_spell_suggestions', side_effect=slow):
            first = asyncio.create_task(db.get_db_spell_suggestions('first'))
            second = asyncio.create_task(db.get_db_spell_suggestions('second'))
            await started.wait()
            self.assertEqual(await db.get_db_spell_suggestions('third'), [])
            release.set()
            self.assertEqual(await first, ['available'])
            self.assertEqual(await second, ['available'])
            self.assertEqual(await db.get_db_spell_suggestions('fourth'), ['available'])

    async def test_actual_pymongo_wire_queries_have_limits_and_verify(self):
        from mockupdb import MockupDB
        from pymongo import AsyncMongoClient
        server = MockupDB(auto_ismaster=True, max_wire_version=25)
        server.run()
        finds = []
        def respond(request):
            if request.command_name.lower() in ('hello', 'ismaster'):
                request.ok(ismaster=True, isWritablePrimary=True, minWireVersion=0, maxWireVersion=25)
            elif request.command_name == 'find':
                finds.append(request.doc)
                request.ok(cursor={'id': 0, 'ns': 'test.' + request.doc['find'], 'firstBatch': [
                    {'_id': 'a', 'file_name': 'Hoot 2020.mkv', 'file_size': 100, 'file_ref': 'a'}]})
            else:
                request.ok()
            return True
        server.autoresponds(respond)
        client = AsyncMongoClient(server.uri, serverSelectionTimeoutMS=5000)
        try:
            with patch.object(db, 'primary', client.test.Primary), patch.object(db, 'cloud', client.test.Cloud), patch.object(db, 'archive', client.test.Archive):
                suggestions = await db.get_db_spell_suggestions('Hootx')
            self.assertEqual(suggestions, ['Hoot 2020.mkv'])
            candidate_finds = [cmd for cmd in finds if cmd.get('maxTimeMS') == db._SPELL_MAX_TIME_MS]
            self.assertEqual(len(candidate_finds), 6)
            self.assertTrue(all(cmd.get('limit') == db._SPELL_CANDIDATES_PER_COLLECTION for cmd in candidate_finds))
            self.assertTrue(any('$text' in cmd['filter'] for cmd in candidate_finds))
            self.assertTrue(any('$or' in cmd['filter'] for cmd in candidate_finds))
            self.assertTrue(any(cmd.get('limit') == 1 for cmd in finds))
        finally:
            await client.close()
            server.stop()


class SearchEntryPointTests(unittest.IsolatedAsyncioTestCase):
    async def test_pm_and_group_use_shared_all_collection_flow(self):
        client = object()
        for chat_id, entry in ((55, bot_filter.pm_search), (-10055, bot_filter.group_search)):
            message = SimpleNamespace(text='Avngers', chat=SimpleNamespace(id=chat_id), from_user=SimpleNamespace(id=55))
            with patch.object(bot_filter, 'is_valid_search', AsyncMock(return_value=True)), \
                 patch.object(bot_filter, 'is_premium', AsyncMock(return_value=True)), \
                 patch.object(bot_filter, 'get_settings', AsyncMock(return_value={'spell_check': True, 'search_enabled': True})), \
                 patch.object(bot_filter, 'auto_filter', AsyncMock()) as core:
                await entry(client, message)
            core.assert_awaited_once_with(client, message, collection_type='all', settings={'spell_check': True, 'search_enabled': True})

    async def test_search_disabled_group_never_suggests(self):
        message = SimpleNamespace(text='Avngers', chat=SimpleNamespace(id=-10055), from_user=SimpleNamespace(id=55))
        with patch.object(bot_filter, 'is_valid_search', AsyncMock(return_value=True)), \
             patch.object(bot_filter, 'get_settings', AsyncMock(return_value={'search_enabled': False})), \
             patch.object(bot_filter, 'auto_filter', AsyncMock()) as core:
            await bot_filter.group_search(None, message)
        core.assert_not_awaited()
