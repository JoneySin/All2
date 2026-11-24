"""Kurigram-native one-shot input waiting for bot flows.

Payments and indexing ask the user for one follow-up message. Kurigram's
dispatcher makes that straightforward: register a temporary ``MessageHandler``
in group ``-1``, resolve a future with the next matching message, and raise
``StopPropagation`` so the same text is not also handled as a search or another
command. The handler is always removed afterwards.

No third-party classes are patched.
"""

from __future__ import annotations

import asyncio
import logging

from pyrogram import Client, StopPropagation
from pyrogram import filters as tg_filters
from pyrogram.handlers import MessageHandler

logger = logging.getLogger(__name__)


class InputTimeout(asyncio.TimeoutError):
    """Raised when the user does not send the requested message in time."""


async def wait_for_user_message(
    client: Client,
    *,
    chat_id: int | str | None = None,
    user_id: int | None = None,
    timeout: float | None = None,
):
    """Wait for the next incoming message from ``user_id`` in ``chat_id``.

    Raises :class:`InputTimeout` on timeout. The temporary handler captures the
    message before normal handlers can process it.
    """
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    async def _capture(_client, message):
        if not future.done():
            future.set_result(message)
        raise StopPropagation

    message_filter = tg_filters.incoming
    if chat_id is not None:
        message_filter &= tg_filters.chat(chat_id)
    if user_id is not None:
        message_filter &= tg_filters.user(user_id)

    handler = MessageHandler(_capture, message_filter)
    client.add_handler(handler, -1)
    try:
        return await asyncio.wait_for(future, timeout)
    except TimeoutError:
        raise InputTimeout() from None
    finally:
        try:
            client.remove_handler(handler, -1)
        except Exception:
            logger.debug("Could not remove temporary input handler", exc_info=True)
