"""Payment callbacks: repeats, concurrent decisions and Telegram failures."""
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

from hydrogram.errors import ListenerTimeout, MessageNotModified
from mongomock_motor import AsyncMongoMockClient
from database.users_chats_db import Database
from plugins import premium


def query(data='pay_confirm_55_30', *, message_id=100, admin_id=1):
    return SimpleNamespace(data=data, answer=AsyncMock(), from_user=SimpleNamespace(id=admin_id, mention='Admin'),
        message=SimpleNamespace(id=message_id, chat=SimpleNamespace(id=-1005), caption='Receipt',
                                edit_caption=AsyncMock(), edit=AsyncMock(), reply=AsyncMock()))


class PremiumCallbackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mongo = AsyncMongoMockClient()
        self.collection = self.mongo.test.Premiums
        await self.collection.create_index('id', unique=True)
        self.db = SimpleNamespace(premium=self.collection, df_prm=Database.df_prm)
        self.db.decide_payment = lambda *args: Database.decide_payment(self.db, *args)
        self.db_patch = patch.object(premium, 'db', self.db)
        self.admin_patch = patch.object(premium, 'ADMINS', [1, 2])
        self.db_patch.start(); self.admin_patch.start()
        self.addCleanup(self.db_patch.stop); self.addCleanup(self.admin_patch.stop)
        self.addCleanup(premium.ACTIVE_PURCHASES.clear)
        self.addCleanup(premium.VERIFY_CACHE.clear)

    async def asyncTearDown(self):
        self.mongo.close()

    async def test_buy_already_displayed_prompt_and_timeout(self):
        q = query(); q.from_user.id = 55
        q.message.edit.side_effect = MessageNotModified()
        bot = SimpleNamespace(listen=AsyncMock(side_effect=ListenerTimeout()))
        await premium.buy_callback(bot, q)
        q.answer.assert_awaited_once_with()
        bot.listen.assert_awaited_once_with(chat_id=-1005, user_id=55, timeout=60)
        self.assertIn('Timeout', q.message.reply.await_args.args[0])
        self.assertNotIn(55, premium.ACTIVE_PURCHASES)

    async def test_simultaneous_buy_clicks_do_not_start_two_listeners(self):
        first = query(); first.from_user.id = 55
        first.message.edit.return_value = first.message
        second = query(); second.from_user.id = 55
        entered, release = asyncio.Event(), asyncio.Event()
        async def listen(**_kwargs):
            entered.set(); await release.wait(); raise ListenerTimeout()
        bot = SimpleNamespace(listen=AsyncMock(side_effect=listen))
        task = asyncio.create_task(premium.buy_callback(bot, first))
        await entered.wait()
        await premium.buy_callback(bot, second)
        self.assertIn('already active', second.answer.await_args.args[0])
        release.set(); await task
        bot.listen.assert_awaited_once()
        self.assertNotIn(55, premium.ACTIVE_PURCHASES)

    async def test_duplicate_approval_is_durable_and_decision_not_reapplied(self):
        bot = SimpleNamespace(send_message=AsyncMock())
        q1, q2 = query(), query()
        await premium.pay_action(bot, q1)
        record = await self.collection.find_one({'id': 55})
        self.assertTrue(record['status']['premium'])
        self.assertEqual(record['status']['plan'], '30 Days')
        self.assertEqual(record['payment_decisions']['-1005_100']['action'], 'confirm')
        await premium.pay_action(bot, q2)
        self.assertEqual((await self.collection.find_one({'id': 55}))['status'], record['status'])
        self.assertIn('already been processed', q2.answer.await_args.args[0])
        q2.message.edit_caption.assert_not_awaited()
        bot.send_message.assert_awaited_once()

    async def test_simultaneous_opposite_decisions_only_apply_once(self):
        bot = SimpleNamespace(send_message=AsyncMock())
        q1 = query('pay_confirm_55_30', admin_id=1)
        q2 = query('pay_reject_55', admin_id=2)
        await asyncio.gather(premium.pay_action(bot, q1), premium.pay_action(bot, q2))
        record = await self.collection.find_one({'id': 55})
        decision = record['payment_decisions']['-1005_100']['action']
        self.assertEqual(record['status']['premium'], decision == 'confirm')
        self.assertEqual(bot.send_message.await_count, 1)
        self.assertEqual(q1.message.edit_caption.await_count + q2.message.edit_caption.await_count, 1)
        self.assertTrue(any('already been processed' in str(q.answer.await_args) for q in (q1, q2)))

    async def test_independent_receipts_and_duplicate_not_modified(self):
        bot = SimpleNamespace(send_message=AsyncMock())
        q1, q2 = query(message_id=100), query(message_id=101)
        q1.message.edit_caption.side_effect = MessageNotModified()
        await premium.pay_action(bot, q1)
        await premium.pay_action(bot, q2)
        record = await self.collection.find_one({'id': 55})
        self.assertEqual(len(record['payment_decisions']), 2)
        self.assertEqual(bot.send_message.await_count, 2)

    async def test_legacy_processed_receipt_without_buttons_is_not_reapplied(self):
        bot = SimpleNamespace(send_message=AsyncMock())
        q = query(); q.message.reply_markup = None
        await premium.pay_action(bot, q)
        self.assertIn('already been processed', q.answer.await_args.args[0])
        self.assertIsNone(await self.collection.find_one({'id': 55}))
        bot.send_message.assert_not_awaited()

    async def test_missing_unique_index_fails_closed(self):
        bot = SimpleNamespace(send_message=AsyncMock())
        q = query()
        with patch.object(self.collection, 'create_index', AsyncMock(side_effect=RuntimeError('index failed'))):
            with self.assertLogs(premium.logger, level='ERROR'):
                await premium.pay_action(bot, q)
        self.assertIn('retry', q.answer.await_args.args[0])
        self.assertIsNone(await self.collection.find_one({'id': 55}))
        bot.send_message.assert_not_awaited()

    async def test_other_telegram_failure_does_not_undo_saved_approval(self):
        bot = SimpleNamespace(send_message=AsyncMock())
        q = query(); q.message.edit_caption.side_effect = RuntimeError('Telegram unreachable')
        with self.assertLogs(premium.logger, level='WARNING'):
            await premium.pay_action(bot, q)
        self.assertTrue((await self.collection.find_one({'id': 55}))['status']['premium'])
        bot.send_message.assert_awaited_once()
        duplicate = query(); await premium.pay_action(bot, duplicate)
        self.assertIn('already been processed', duplicate.answer.await_args.args[0])

    async def test_database_failure_is_retryable_and_invalid_denied(self):
        bot = SimpleNamespace(send_message=AsyncMock())
        broken = query()
        with patch.object(premium.db, 'decide_payment', AsyncMock(side_effect=RuntimeError('offline'))):
            with self.assertLogs(premium.logger, level='ERROR'):
                await premium.pay_action(bot, broken)
        self.assertIn('retry', broken.answer.await_args.args[0])
        self.assertIsNone(await self.collection.find_one({'id': 55}))
        for invalid in (query('pay_confirm_55_0'), query('pay_confirm_55_999999999999999999'), query('pay_reject_55', admin_id=5)):
            await premium.pay_action(bot, invalid)
            self.assertTrue(invalid.answer.await_args.kwargs['show_alert'])
        bot.send_message.assert_not_awaited()
        retry = query(); await premium.pay_action(bot, retry)
        self.assertTrue((await self.collection.find_one({'id': 55}))['status']['premium'])

    async def test_failed_receipt_forward_does_not_claim_submission(self):
        receipt = SimpleNamespace(photo=True, copy=AsyncMock(side_effect=RuntimeError('offline')))
        bot = SimpleNamespace(listen=AsyncMock(side_effect=[SimpleNamespace(id=2, text='30'), receipt]))
        q = query(); q.from_user.id = 55; q.from_user.mention = 'User'
        q.message.edit.return_value = q.message
        q.message.reply_photo = AsyncMock(return_value=SimpleNamespace(id=3))
        with patch.object(premium, 'safe_del', new_callable=AsyncMock), self.assertLogs(premium.logger, level='ERROR'):
            await premium.buy_callback(bot, q)
        self.assertNotIn(55, premium.VERIFY_CACHE)
        self.assertNotIn('Sent to Admin', q.message.reply.await_args.args[0])
