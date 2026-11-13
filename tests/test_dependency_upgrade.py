"""Compatibility checks for the native async MongoDB driver and bot listeners."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

for key, value in {
    'API_ID': '1', 'API_HASH': 'test', 'BOT_TOKEN': '1:test', 'ADMINS': '1',
    'LOG_CHANNEL': '-1001', 'BIN_CHANNEL': '-1002',
    'DATABASE_URL': 'mongodb://localhost:27017', 'URL': 'https://example.com',
}.items():
    os.environ.setdefault(key, value)

from hydrogram.errors import ListenerTimeout
from mockupdb import MockupDB
from pymongo import AsyncMongoClient
from database import ia_filterdb as db
from database.users_chats_db import Database
from plugins import check_db_TEMP, premium


class DriverUpgradeTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_async_driver_find_update_and_aggregate(self):
        # A wire-protocol stub exercises the real PyMongo async client, not Motor's mock.
        server = MockupDB(auto_ismaster=True, max_wire_version=25)
        server.run()
        commands = []
        updates = []
        processed = False
        def respond(request):
            nonlocal processed
            commands.append(request.command_name)
            name = request.command_name
            if name.lower() in ('hello', 'ismaster'):
                request.ok(ismaster=True, isWritablePrimary=True, minWireVersion=0, maxWireVersion=25)
            elif name == 'aggregate':
                collection = request.doc['aggregate']
                batch = ([{'_id': 'series', 'count': 2}, {'_id': 'quality', 'count': 3}]
                         if collection == 'QualityGroups' else [{'_id': 'Movies', 'count': 4}])
                request.ok(cursor={'id': 0, 'ns': 'test.' + collection, 'firstBatch': batch})
            elif name == 'listIndexes':
                request.ok(cursor={'id': 0, 'ns': 'test.Files', 'firstBatch': [{
                    'name': '_id_', 'key': {'_id': 1}, 'v': 2
                }, {'name': 'title_1', 'key': {'title': 1}, 'v': 2}]})
            elif name == 'find':
                request.ok(cursor={'id': 0, 'ns': 'test.Files', 'firstBatch': [{'_id': 'a'}]})
            elif name == 'update':
                updates.append(request.doc)
                query = request.doc['updates'][0]['q']
                if 'payment_decisions.-1005_100' in query:
                    request.ok(n=0 if processed else 1, nModified=0 if processed else 1)
                    processed = True
                else:
                    request.ok(n=1, nModified=1)
            else:
                request.ok()
            return True
        server.autoresponds(respond)
        client = AsyncMongoClient(server.uri, serverSelectionTimeoutMS=5000)
        try:
            with patch.object(db, 'groups', client.test.QualityGroups), patch.object(db, 'posts', client.test.Posts):
                self.assertEqual(await db.get_saved_group_counts(), {'total': 5, 'quality': 3, 'series': 2})
                self.assertEqual(await db.get_post_category_counts(), (4, 4, 0, 0, 0))
            rows = await client.test.Files.find({}).to_list(length=10)
            self.assertEqual(rows, [{'_id': 'a'}])
            self.assertEqual((await client.test.Files.update_one({'_id': 'a'}, {'$set': {'group_id': '1'}})).modified_count, 1)
            account = SimpleNamespace(premium=client.test.Premiums, df_prm=Database.df_prm)
            status = {'premium': True, 'plan': '30 Days'}
            self.assertTrue(await Database.decide_payment(account, 55, -1005, 100, 'confirm', 1, status))
            self.assertFalse(await Database.decide_payment(account, 55, -1005, 100, 'confirm', 1, status))
            operation = updates[-3]['updates'][0]
            self.assertEqual(operation['q']['payment_decisions.-1005_100'], {'$exists': False})
            self.assertEqual(operation['u']['$set']['status'], status)
            self.assertEqual(operation['u']['$set']['payment_decisions.-1005_100']['action'], 'confirm')
            indexes = [index async for index in await client.test.Files.list_indexes()]
            self.assertEqual([index['name'] for index in indexes], ['_id_', 'title_1'])
            self.assertIn('listIndexes', commands)
            self.assertIn('aggregate', commands)
            self.assertIn('find', commands)
            self.assertIn('update', commands)
        finally:
            await client.close()
            server.stop()

    async def test_payment_listener_is_scoped_to_chat_and_user_and_handles_timeout(self):
        msg = SimpleNamespace(id=77)
        reply = AsyncMock()
        message = SimpleNamespace(chat=SimpleNamespace(id=99), edit=AsyncMock(return_value=msg), reply=reply)
        query = SimpleNamespace(from_user=SimpleNamespace(id=55), message=message, answer=AsyncMock())
        client = SimpleNamespace(listen=AsyncMock(side_effect=ListenerTimeout()))
        with patch.object(premium, 'ADMINS', []):
            await premium.buy_callback(client, query)
        client.listen.assert_awaited_once_with(chat_id=99, user_id=55, timeout=60)
        self.assertIn('Timeout', reply.await_args.args[0])

    async def test_payment_receipt_listener_and_success(self):
        response = SimpleNamespace(id=4, text='30')
        receipt = SimpleNamespace(photo=True, copy=AsyncMock())
        client = SimpleNamespace(listen=AsyncMock(side_effect=[response, receipt]))
        message = SimpleNamespace(chat=SimpleNamespace(id=99),
            edit=AsyncMock(return_value=SimpleNamespace(id=1)),
            reply_photo=AsyncMock(return_value=SimpleNamespace(id=2)),
            reply=AsyncMock(return_value=SimpleNamespace(id=3)))
        query = SimpleNamespace(from_user=SimpleNamespace(id=55, mention='Test'), message=message, answer=AsyncMock())
        with patch.object(premium, 'ADMINS', []), patch.object(premium, 'safe_del', new_callable=AsyncMock):
            await premium.buy_callback(client, query)
        self.assertEqual(client.listen.await_args_list, [
            call(chat_id=99, user_id=55, timeout=60),
            call(chat_id=99, user_id=55, timeout=300),
        ])
        receipt.copy.assert_awaited_once()
        premium.VERIFY_CACHE.pop(55, None)

    async def test_temporary_migration_closes_clients_on_early_return(self):
        status = SimpleNamespace(edit=AsyncMock())
        message = SimpleNamespace(from_user=SimpleNamespace(id=56), text='mongodb://new test',
                                  reply=AsyncMock(return_value=status))
        old_db = SimpleNamespace(list_collection_names=AsyncMock(return_value=[]))
        new_db = SimpleNamespace()
        class FakeClient:
            def __init__(self, database):
                self.database = database
                self.close = AsyncMock()
                self.admin = SimpleNamespace(command=AsyncMock())
            def __getitem__(self, name):
                return self.database
        old, new = FakeClient(old_db), FakeClient(new_db)
        check_db_TEMP.PENDING[56] = {'action': 'copy_db'}
        with patch.object(check_db_TEMP, 'AsyncMongoClient', side_effect=[old, new]):
            await check_db_TEMP.receive_new_url(None, message)
        old.close.assert_awaited_once()
        new.close.assert_awaited_once()
        self.assertIn('No collections', status.edit.await_args.args[0])
