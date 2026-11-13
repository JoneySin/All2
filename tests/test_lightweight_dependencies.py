"""Regression coverage for dependency slimming, QR payments and local time."""
import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

for key, value in {
    'API_ID': '1', 'API_HASH': 'test', 'BOT_TOKEN': '1:test', 'ADMINS': '1',
    'LOG_CHANNEL': '-1001', 'BIN_CHANNEL': '-1002',
    'DATABASE_URL': 'mongodb://localhost:27017', 'URL': 'https://example.com',
}.items():
    os.environ.setdefault(key, value)

import png
import qrcode
from database import users_chats_db
from plugins import premium
import utils


class TimezoneCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_helpers_preserve_naive_and_aware_contracts(self):
        instant = datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)
        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)
        for zone in ('Asia/Kolkata', 'America/New_York', 'UTC'):
            with self.subTest(zone=zone), patch.object(utils, 'TIME_ZONE', zone), \
                    patch.object(users_chats_db, 'TIME_ZONE', zone), \
                    patch.object(utils, 'datetime', FrozenDatetime), \
                    patch.object(users_chats_db, 'datetime', FrozenDatetime):
                naive = utils.get_local_now()
                aware = users_chats_db.get_local_now()
                expected = instant.astimezone(ZoneInfo(zone))
                self.assertIsNone(naive.tzinfo)  # Existing premium strings are local, naive datetimes.
                self.assertEqual(naive, expected.replace(tzinfo=None))
                self.assertEqual(aware.tzinfo.key, zone)
                self.assertEqual(aware.astimezone(timezone.utc), instant)

    async def test_auto_delete_delay_uses_elapsed_time_across_dst(self):
        # Both DST spring-forward and fall-back must still wait exactly two hours.
        for now in (datetime(2026, 3, 8, 1, 30, tzinfo=ZoneInfo('America/New_York')),
                    datetime(2026, 11, 1, 0, 30, tzinfo=ZoneInfo('America/New_York'))):
            queue = SimpleNamespace(update_one=AsyncMock())
            with self.subTest(now=now), patch.object(users_chats_db, 'get_local_now', return_value=now):
                await users_chats_db.Database.add_to_delete_queue(SimpleNamespace(delete_queue=queue), 1, 2, 7200)
                deadline = queue.update_one.await_args.args[1]['$set']['delete_at']
                self.assertEqual(deadline.astimezone(timezone.utc), now.astimezone(timezone.utc) + timedelta(hours=2))

    async def test_login_window_remains_24_elapsed_hours_across_dst(self):
        class EmptyCursor:
            def __aiter__(self): return self
            async def __anext__(self): raise StopAsyncIteration
        for now in (datetime(2026, 3, 8, 3, 30, tzinfo=ZoneInfo('America/New_York')),
                    datetime(2026, 11, 1, 2, 30, tzinfo=ZoneInfo('America/New_York'))):
            col = SimpleNamespace(find=lambda query, projection: EmptyCursor())
            col.find = Mock(side_effect=col.find)
            instance = SimpleNamespace(db={'web_users': col})
            with self.subTest(now=now), patch.object(users_chats_db, 'get_local_now', return_value=now), \
                    patch.object(utils.temp, 'USER_SESSIONS', {}):
                self.assertEqual(await users_chats_db.Database.get_today_logged_in_users_count(instance), 0)
                cutoff = col.find.call_args.args[0]['last_login']['$gte']
                self.assertEqual(cutoff.astimezone(timezone.utc), now.astimezone(timezone.utc) - timedelta(days=1))


class PaymentQrTests(unittest.IsolatedAsyncioTestCase):
    async def test_payment_flow_generates_png_containing_expected_qr(self):
        response = SimpleNamespace(id=4, text='30')
        receipt = SimpleNamespace(photo=True, copy=AsyncMock())
        client = SimpleNamespace(listen=AsyncMock(side_effect=[response, receipt]))
        message = SimpleNamespace(chat=SimpleNamespace(id=99),
            edit=AsyncMock(return_value=SimpleNamespace(id=1)),
            reply_photo=AsyncMock(return_value=SimpleNamespace(id=2)),
            reply=AsyncMock(return_value=SimpleNamespace(id=3)))
        query = SimpleNamespace(from_user=SimpleNamespace(id=55, mention='Test'), message=message, answer=AsyncMock())
        try:
            with patch.object(premium, 'ADMINS', []), patch.object(premium, 'safe_del', new_callable=AsyncMock), \
                    patch.object(premium, 'UPI_ID', 'example@upi'), patch.object(premium, 'UPI_NAME', 'Test Merchant'), \
                    patch.object(premium, 'PRE_DAY_AMOUNT', 10):
                await premium.buy_callback(client, query)
            message.reply_photo.assert_awaited_once()
            payload = message.reply_photo.await_args.kwargs['photo'].getvalue()
            self.assertEqual(payload[:8], b'\x89PNG\r\n\x1a\n')
            width, height, pixels, metadata = png.Reader(bytes=payload).read()
            qr = qrcode.QRCode()
            qr.add_data('upi://pay?pa=example@upi&pn=Test Merchant&am=300&cu=INR')
            qr.make(fit=True)
            matrix = qr.get_matrix()
            self.assertEqual((width, height), (len(matrix) * qr.box_size,) * 2)
            self.assertEqual(metadata['planes'], 1)
            rows = list(pixels)
            # Every generated module must match the expected UPI payload's QR matrix.
            for y, row in enumerate(matrix):
                for x, black in enumerate(row):
                    self.assertEqual(rows[y * qr.box_size + qr.box_size // 2][x * qr.box_size + qr.box_size // 2], 0 if black else 1)
            receipt.copy.assert_awaited_once()
        finally:
            premium.VERIFY_CACHE.pop(55, None)
