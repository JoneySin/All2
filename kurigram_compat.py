"""Small shims for APIs this bot used from Hydrogram but Kurigram lacks.

Kurigram (Pyrogram fork) does not ship ``Client.listen()`` or
``ListenerTimeout``. Payments and indexing wait for the user's next message, so
this module re-implements that one-shot listener with a temporary handler and
installs it on ``pyrogram.Client``. Everything else (sessions, file ids, raw
requests) is used through the public Kurigram API or Pyrogram's own helpers.

Importing this module is enough; it is imported once in bot.py.
"""

from __future__ import annotations

import asyncio
import logging

from pyrogram import Client, StopPropagation
from pyrogram import filters as tg_filters
from pyrogram.handlers import MessageHandler

logger = logging.getLogger(__name__)


class ListenerTimeout(asyncio.TimeoutError):
    """Raised by ``listen()`` when no matching message arrives in time."""


async def listen(client, chat_id=None, user_id=None, timeout=None, filters=None):
    """Wait for one incoming message matching chat/user, like Hydrogram's listen.

    The temporary handler runs in group -1 and raises StopPropagation so the
    captured input is not also treated as a search or another command.
    """
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    async def _capture(_client, message):
        if not future.done():
            future.set_result(message)
        raise StopPropagation

    combined = filters if filters is not None else tg_filters.all
    combined = combined & tg_filters.incoming
    if chat_id is not None:
        combined = combined & tg_filters.chat(chat_id)
    if user_id is not None:
        combined = combined & tg_filters.user(user_id)

    handler = MessageHandler(_capture, combined)
    client.add_handler(handler, -1)
    try:
        return await asyncio.wait_for(future, timeout)
    except TimeoutError:
        raise ListenerTimeout() from None
    finally:
        try:
            client.remove_handler(handler, -1)
        except Exception:
            logger.debug("Could not remove temporary listen handler", exc_info=True)


if not hasattr(Client, "listen"):
    Client.listen = listen
