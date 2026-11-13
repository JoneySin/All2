"""Regression tests for security and concurrency bugs found in the code audit."""
import asyncio
import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

for key, value in {
    'API_ID': '1', 'API_HASH': 'test', 'BOT_TOKEN': '1:test', 'ADMINS': '1',
    'LOG_CHANNEL': '-1001', 'BIN_CHANNEL': '-1002',
    'DATABASE_URL': 'mongodb://localhost:27017', 'URL': 'https://example.com',
}.items():
    os.environ.setdefault(key, value)

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from mongomock_motor import AsyncMongoMockClient
from database.users_chats_db import OTP_MAX_TRIES, WebAuthDB, hash_password, verify_password
from plugins import index
from utils import temp
from web import login_routes, post_routes, profile_routes


class WebEscapingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app = web.Application()
        app.add_routes(login_routes.login_routes)
        app.add_routes(profile_routes.profile_routes)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_login_messages_escape_html(self):
        payload = '<svg/onload=alert(42)>'
        for path, key in (('/login', 'err'), ('/register', 'err'), ('/forgot_password', 'msg')):
            response = await self.client.get(path, params={key: payload})
            body = await response.text()
            self.assertEqual(response.status, 200)
            self.assertNotIn(payload, body)
            self.assertIn('&lt;svg/onload=alert(42)&gt;', body)

    async def test_verify_registration_rejects_html_id_and_renders_numeric_id(self):
        response = await self.client.get('/verify_registration', params={'tg_id': '\" onfocus=alert(1) x=\"'}, allow_redirects=False)
        self.assertEqual(response.status, 302)
        self.assertEqual(response.headers['Location'], '/register')
        response = await self.client.get('/verify_registration', params={'tg_id': '123'})
        self.assertIn('name="tg_id" value="123"', await response.text())

    async def test_profile_escapes_messages_and_database_values(self):
        email = 'user\" onfocus=alert(12) x=\"@example.com'
        plan = '<svg/onload=alert(13)>'
        fake_web_db = SimpleNamespace(col=SimpleNamespace(find_one=AsyncMock(return_value={'email': email})))
        fake_user_db = SimpleNamespace(get_plan=AsyncMock(return_value={'premium': True, 'expire': plan}))
        with patch.object(profile_routes, 'get_auth', AsyncMock(return_value=('user', 2))), \
                patch.object(profile_routes, 'web_db', fake_web_db), patch.object(profile_routes, 'user_db', fake_user_db):
            response = await self.client.get('/profile', params={'err': '<svg/onload=alert(14)>'})
            body = await response.text()
        self.assertEqual(response.status, 200)
        self.assertNotIn(email, body)
        self.assertNotIn(plan, body)
        self.assertNotIn('<svg/onload=alert(14)>', body)
        self.assertIn('user&quot; onfocus=alert(12) x=&quot;@example.com', body)
        self.assertIn('&lt;svg/onload=alert(13)&gt;', body)


class OTPConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mongo = AsyncMongoMockClient()
        self.db = WebAuthDB(self.mongo.test)
        await self.db.col.insert_one({'tg_id': 55, 'password': hash_password('old'), 'otp': '123456',
                                      'otp_exp': time.time() + 600, 'otp_tries': 0})

    async def asyncTearDown(self):
        self.mongo.close()

    async def test_correct_otp_can_only_change_password_once(self):
        original = self.db.col.find_one_and_update
        both, ready = 0, asyncio.Event()
        async def read_then_wait(*args, **kwargs):
            nonlocal both
            item = await original(*args, **kwargs)
            both += 1
            if both == 2: ready.set()
            await ready.wait()
            return item
        with patch.object(self.db.col, 'find_one_and_update', AsyncMock(side_effect=read_then_wait)):
            results = await asyncio.gather(self.db.verify_otp_and_reset(55, '123456', 'password1'),
                                           self.db.verify_otp_and_reset(55, '123456', 'password2'))
        self.assertEqual(sorted(results), [False, True])
        user = await self.db.col.find_one({'tg_id': 55})
        self.assertTrue(any(verify_password(password, user['password']) for password in ('password1', 'password2')))
        self.assertNotIn('otp', user)

    async def test_stale_bad_attempt_does_not_erase_new_otp(self):
        await self.db.col.update_one({'tg_id': 55}, {'$set': {'otp_tries': OTP_MAX_TRIES - 1}})
        original = self.db.col.find_one_and_update
        async def issue_new_otp(*args, **kwargs):
            old = await original(*args, **kwargs)
            await self.db.col.update_one({'tg_id': 55}, {'$set': {'otp': '654321', 'otp_exp': time.time() + 900, 'otp_tries': 0}})
            return old
        with patch.object(self.db.col, 'find_one_and_update', AsyncMock(side_effect=issue_new_otp)):
            self.assertFalse(await self.db.verify_otp_and_reset(55, '000000', 'newpass'))
        self.assertEqual((await self.db.col.find_one({'tg_id': 55}))['otp'], '654321')

    async def test_expired_and_wrong_otp_do_not_change_password(self):
        for _ in range(OTP_MAX_TRIES):
            self.assertFalse(await self.db.verify_otp_and_reset(55, '000000', 'newpass'))
        self.assertFalse(await self.db.verify_otp_and_reset(55, '123456', 'newpass'))
        self.assertTrue(verify_password('old', (await self.db.col.find_one({'tg_id': 55}))['password']))
        await self.db.col.update_one({'tg_id': 55}, {'$set': {'otp': '123456', 'otp_exp': time.time() - 1, 'otp_tries': 0}})
        self.assertFalse(await self.db.verify_otp_and_reset(55, '123456', 'newpass'))


class IndexCallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_admin_can_index_or_cancel_and_invalid_data_is_rejected(self):
        with patch.object(index, 'ADMINS', [1]), patch.object(index, 'index_files_to_db', AsyncMock()) as run:
            for data, user in [('index#cancel#channel#100#0', 2), ('index#start#channel#100#0#primary', 2),
                               ('index#start#channel#100#-1#primary', 1), ('index#start#channel#100#0#other', 1),
                               ('index#yes#broken', 1)]:
                q = SimpleNamespace(data=data, from_user=SimpleNamespace(id=user), answer=AsyncMock(),
                                    message=SimpleNamespace(edit=AsyncMock()))
                temp.CANCEL = False
                await index.index_files(None, q)
                self.assertTrue(q.answer.await_args.kwargs['show_alert'])
                self.assertFalse(temp.CANCEL)
                q.message.edit.assert_not_awaited()
            run.assert_not_awaited()
            q = SimpleNamespace(data='index#start#channel#100#10#primary', from_user=SimpleNamespace(id=1),
                                answer=AsyncMock(), message=SimpleNamespace(edit=AsyncMock()))
            await index.index_files('bot', q)
            run.assert_awaited_once_with(100, 'channel', q.message, 'bot', 10, 'primary')

    def test_index_stats_do_not_double_count_unsupported(self):
        text = index.index_status_text('primary', '1s', 10, 2, 1, 1, 3, 2, 1, 0)
        self.assertIn('No Media: <code>3</code>', text)
        self.assertIn('Unsupported: <code>2</code>', text)


class IbbUrlTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_exact_https_ibb_hosts_are_fetched_and_redirects_disabled(self):
        class Response:
            status = 200
            async def text(self): return '<meta property="og:image" content="https://i.ibb.co/x.jpg">'
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
        session = SimpleNamespace(get=Mock(return_value=Response()))
        for url in ('http://127.0.0.1/?ibb.co', 'https://ibb.co@localhost/private',
                    'https://ibb.co.attacker.example/', 'https://i.ibb.co/x.jpg',
                    'https://ibb.co:8080/image', 'http://ibb.co/image'):
            self.assertEqual(await post_routes.fetch_direct_ibb_url(session, url), url)
        session.get.assert_not_called()
        self.assertEqual(await post_routes.fetch_direct_ibb_url(session, 'https://ibb.co/abc'), 'https://i.ibb.co/x.jpg')
        session.get.assert_called_once_with('https://ibb.co/abc', timeout=10, allow_redirects=False)


class IndexIteratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_includes_last_message_and_deleted_placeholders(self):
        from bot import Bot
        async def get_messages(_chat, ids):
            return [SimpleNamespace(id=i, empty=(i == 50)) for i in ids]
        fake = SimpleNamespace(get_messages=AsyncMock(side_effect=get_messages))
        messages = [m async for m in Bot.iter_messages(fake, 'channel', 201, 0)]
        self.assertEqual([m.id for m in messages], list(range(1, 202)))
        self.assertTrue(messages[49].empty)
        self.assertEqual(fake.get_messages.await_args_list[0].args[1], list(range(1, 201)))
        self.assertEqual(fake.get_messages.await_args_list[1].args[1], [201])
        fake.get_messages.reset_mock()
        messages = [m async for m in Bot.iter_messages(fake, 'channel', 10, 8)]
        self.assertEqual([m.id for m in messages], [9, 10])

    async def test_fetch_error_propagates_instead_of_reporting_success(self):
        from bot import Bot
        fake = SimpleNamespace(get_messages=AsyncMock(side_effect=RuntimeError('offline')))
        with self.assertLogs('bot', level='ERROR'), self.assertRaisesRegex(RuntimeError, 'offline'):
            _ = [m async for m in Bot.iter_messages(fake, 'channel', 5)]


class AutoDeleteTimerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        from plugins.filter import ACTIVE_DELETE_TASKS
        tasks = list(ACTIVE_DELETE_TASKS.values())
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        ACTIVE_DELETE_TASKS.clear()

    async def test_failed_deletion_does_not_leak_task(self):
        from plugins.filter import ACTIVE_DELETE_TASKS, start_auto_delete_timer
        client = SimpleNamespace(delete_messages=AsyncMock(side_effect=RuntimeError('offline')))
        with self.assertLogs('plugins.filter', level='ERROR'):
            await start_auto_delete_timer(client, 1, 2, delay=0)
            await ACTIVE_DELETE_TASKS['1_2']
        self.assertNotIn('1_2', ACTIVE_DELETE_TASKS)

    async def test_old_cancelled_timer_does_not_remove_new_timer(self):
        from plugins.filter import ACTIVE_DELETE_TASKS, start_auto_delete_timer
        client = SimpleNamespace(delete_messages=AsyncMock())
        await start_auto_delete_timer(client, 1, 2, delay=100)
        old = ACTIVE_DELETE_TASKS['1_2']
        await asyncio.sleep(0)  # let the old task enter its sleep
        await start_auto_delete_timer(client, 1, 2, delay=100)
        replacement = ACTIVE_DELETE_TASKS['1_2']
        await old
        self.assertIs(ACTIVE_DELETE_TASKS['1_2'], replacement)


class PasswordStorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mongo = AsyncMongoMockClient()
        self.db = WebAuthDB(self.mongo.test)

    async def asyncTearDown(self):
        self.mongo.close()

    async def test_new_passwords_are_salted_and_authenticate(self):
        self.assertEqual(await self.db.create_user(7, 'a@example.com', 'password1'), (True, 'Account Created Successfully!'))
        self.assertEqual(await self.db.create_user(8, 'b@example.com', 'password1'), (True, 'Account Created Successfully!'))
        one = await self.db.col.find_one({'tg_id': 7})
        two = await self.db.col.find_one({'tg_id': 8})
        self.assertTrue(one['password'].startswith('pbkdf2_sha256$600000$'))
        self.assertNotEqual(one['password'], two['password'])
        self.assertIsNotNone(await self.db.verify_login('a@example.com', 'password1'))
        self.assertIsNone(await self.db.verify_login('a@example.com', 'wrong-password'))
        self.assertIsNone(await self.db.verify_login('no@example.com', 'password1'))

    async def test_legacy_sha256_is_upgraded_after_login(self):
        import hashlib
        old = hashlib.sha256(b'legacy-password').hexdigest()
        await self.db.col.insert_one({'tg_id': 7, 'email': 'legacy@example.com', 'password': old})
        self.assertIsNone(await self.db.verify_login('legacy@example.com', 'bad'))
        self.assertEqual((await self.db.col.find_one({'tg_id': 7}))['password'], old)
        self.assertIsNotNone(await self.db.verify_login('legacy@example.com', 'legacy-password'))
        new = (await self.db.col.find_one({'tg_id': 7}))['password']
        self.assertTrue(new.startswith('pbkdf2_sha256$'))
        self.assertTrue(verify_password('legacy-password', new))

    async def test_legacy_login_does_not_overwrite_concurrent_reset(self):
        import hashlib
        await self.db.col.insert_one({'tg_id': 7, 'email': 'legacy@example.com',
                                      'password': hashlib.sha256(b'oldpassword').hexdigest()})
        original = self.db.col.update_one
        replacement = hash_password('newpassword')
        async def reset_before_upgrade(*args, **kwargs):
            await original({'tg_id': 7}, {'$set': {'password': replacement}})
            return await original(*args, **kwargs)
        with patch.object(self.db.col, 'update_one', AsyncMock(side_effect=reset_before_upgrade)):
            self.assertIsNone(await self.db.verify_login('legacy@example.com', 'oldpassword'))
        self.assertEqual((await self.db.col.find_one({'tg_id': 7}))['password'], replacement)
        self.assertIsNotNone(await self.db.verify_login('legacy@example.com', 'newpassword'))

    def test_invalid_password_hashes_fail_safely(self):
        for stored in ('broken', '🤷', 'pbkdf2_sha256$999999999$00$00', 'pbkdf2_sha256$600000$zz$aaa', None):
            self.assertFalse(verify_password('password', stored))


class RegistrationSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app = web.Application()
        app.add_routes(login_routes.login_routes)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.saved_pending = temp.REG_PENDING
        temp.REG_PENDING = {}

    async def asyncTearDown(self):
        temp.REG_PENDING = self.saved_pending
        await self.client.close()

    async def test_failed_delivery_removes_pending_password(self):
        fake_db = SimpleNamespace(col=SimpleNamespace(find_one=AsyncMock(return_value=None)))
        with patch.object(login_routes, 'web_db', fake_db), patch.object(temp, 'BOT', SimpleNamespace(send_message=AsyncMock(side_effect=RuntimeError('offline')))):
            response = await self.client.post('/api/register_step1', data={'tg_id': '123', 'email': 'a@example.com', 'password': 'password'}, allow_redirects=False)
        self.assertIn('Failed+to+send+OTP', response.headers['Location'])
        self.assertNotIn(123, temp.REG_PENDING)

    async def test_expired_entries_are_cleaned_and_parallel_verification_is_consumed_once(self):
        temp.REG_PENDING[99] = {'expiry': time.time() - 1, 'password': 'expired'}
        started, proceed = asyncio.Event(), asyncio.Event()
        async def create(*args):
            started.set()
            await proceed.wait()
            return True, 'success'
        fake_db = SimpleNamespace(col=SimpleNamespace(find_one=AsyncMock(return_value=None)), create_user=AsyncMock(side_effect=create))
        with patch.object(login_routes, 'web_db', fake_db), patch.object(temp, 'BOT', SimpleNamespace(send_message=AsyncMock())):
            await self.client.post('/api/register_step1', data={'tg_id': '123', 'email': 'a@example.com', 'password': 'password'}, allow_redirects=False)
            self.assertNotIn(99, temp.REG_PENDING)
            otp = temp.REG_PENDING[123]['otp']
            task = asyncio.create_task(self.client.post('/api/register_step2', data={'tg_id': '123', 'otp': otp}, allow_redirects=False))
            await started.wait()
            second = await self.client.post('/api/register_step2', data={'tg_id': '123', 'otp': otp}, allow_redirects=False)
            proceed.set()
            first = await task
        self.assertIn('Session+expired', second.headers['Location'])
        self.assertIn('Account+created', first.headers['Location'])
        fake_db.create_user.assert_awaited_once()


class OTPSendLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_sends_enforce_rate_limit(self):
        from database.users_chats_db import OTP_MAX_SENDS, OTPRateLimited
        mongo = AsyncMongoMockClient()
        db = WebAuthDB(mongo.test)
        await db.col.insert_one({'tg_id': 99})
        original = db.col.find_one
        gate = asyncio.Event()
        reads = 0
        async def collide(*args, **kwargs):
            nonlocal reads
            result = await original(*args, **kwargs)
            reads += 1
            if reads <= 8:
                if reads == 8: gate.set()
                await gate.wait()
            return result
        with patch.object(db.col, 'find_one', AsyncMock(side_effect=collide)):
            results = await asyncio.gather(*(db.generate_otp(99) for _ in range(8)), return_exceptions=True)
        self.assertEqual(sum(isinstance(item, str) for item in results), OTP_MAX_SENDS)
        self.assertTrue(all(isinstance(item, (str, OTPRateLimited)) for item in results))
        self.assertEqual((await original({'tg_id': 99}))['otp_sends'], OTP_MAX_SENDS)
        mongo.close()
