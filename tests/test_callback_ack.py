"""Callback buttons must be acknowledged before slow database work.

Telegram keeps the button spinner until answerCallbackQuery arrives.  A
pagination callback that waits for Mongo before answering therefore looks
broken even when the query itself succeeds.
"""
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

from plugins import commands
from plugins import filter as bot_filter


class CallbackAcknowledgementTests(unittest.IsolatedAsyncioTestCase):
    async def test_pagination_answers_before_searching(self):
        key = '1-77'
        bot_filter.BUTTONS[key] = {
            'query': 'Film',
            'counts': {'all': {'primary': 1, 'cloud': 0, 'archive': 0}},
        }
        events = []
        message = SimpleNamespace(
            chat=SimpleNamespace(id=1), id=77,
            edit_text=AsyncMock(side_effect=lambda *a, **k: events.append('edit')),
        )
        query = SimpleNamespace(
            data=f'nav_1_{key}_0_all',
            from_user=SimpleNamespace(id=1),
            message=message,
            answer=AsyncMock(side_effect=lambda *a, **k: events.append('answer')),
        )

        async def search(*args, **kwargs):
            events.append('search')
            return [{'file_id': 'x', 'file_name': 'Film.mkv', 'file_size': 1}], '', 1, 'Primary'

        with patch.object(bot_filter, 'IS_PREMIUM', False), \
                patch.object(bot_filter, 'get_search_results', AsyncMock(side_effect=search)), \
                patch.object(bot_filter, 'get_settings', AsyncMock(return_value={'simple_mode': True})), \
                patch.object(bot_filter, 'get_filter_ui', return_value=('results', None)), \
                patch.object(bot_filter, 'start_auto_delete_timer', AsyncMock()):
            await bot_filter.pagination_handler(None, query)
            self.assertEqual(events, ['answer', 'search', 'edit'])
        query.answer.assert_awaited_once()
        bot_filter.BUTTONS.pop(key, None)

    async def test_help_menu_answers_instead_of_leaving_spinner(self):
        query = SimpleNamespace(
            data='help',
            from_user=SimpleNamespace(id=1, mention='Admin'),
            answer=AsyncMock(),
            message=SimpleNamespace(edit_caption=AsyncMock(), edit_text=AsyncMock()),
        )
        with patch.object(commands, 'ADMINS', [1]):
            await commands.ui_cb(None, query)
        query.answer.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
