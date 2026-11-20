"""Native coloured inline buttons for Kurigram (Telegram Bot API styles).

Telegram clients released after 9 February 2026 understand an optional button
``style``: PRIMARY (blue), SUCCESS (green) and DANGER (red). Kurigram 2.2.27
exposes it as ``InlineKeyboardButton(style=enums.ButtonStyle.X)``.

Editing every keyboard call site is noisy and easy to miss, so this module
styles an ``InlineKeyboardMarkup`` as soon as it is built: any button that has
not chosen a style explicitly gets one from its action. An explicit ``style=``
at the call site always wins, and every row ends up fully coloured. Within one
row colours are unique for rows of up to three buttons: if two actions want the
same colour, the later button moves to the next unused colour. Longer rows
cycle colours while keeping neighbouring buttons different. Importing this
module installs the behaviour (bot.py imports it before plugins load).

Colours are semantic, not decorative:
- red    : close/cancel/delete/reject/stop/leave/ban/off/restart
- green  : watch/play/download/stream/buy/premium/activate/approve/confirm/
           join/subscribe/renew/start/index/send/add/link
- blue   : navigation, settings, stats, help, links and anything else
"""

from __future__ import annotations

import re

from pyrogram import enums
from pyrogram.types import InlineKeyboardMarkup

DANGER = enums.ButtonStyle.DANGER
SUCCESS = enums.ButtonStyle.SUCCESS
PRIMARY = enums.ButtonStyle.PRIMARY
DEFAULT = enums.ButtonStyle.DEFAULT

_DANGER_WORDS = (
    "close", "cancel", "reject", "delete", "remove", "stop", "leave", "ban",
    "disable", "logout", "log out", "clear", "reset", "restart", "decline",
)
_SUCCESS_WORDS = (
    "watch", "play", "download", "stream", "buy", "premium", "activate",
    "approve", "confirm", "join", "subscribe", "renew", "start", "index",
    "send", "add", "link", "resume", "verify",
)
_DANGER_SIGNS = ("❌", "✖", "🗑")
_SUCCESS_SIGNS = ("✅", "➕", "🔗")


def _word_hit(text: str, words: tuple) -> bool:
    return any(re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", text) for word in words)


def style_for(text: str = "", callback_data: str | bytes = "") -> enums.ButtonStyle:
    """Pick a semantic style from a button's visible text and callback data."""
    if isinstance(callback_data, bytes):
        callback_data = callback_data.decode("utf-8", "ignore")
    probe = f"{text or ''} {callback_data or ''}".lower()
    if any(sign in probe for sign in _DANGER_SIGNS) or _word_hit(probe, _DANGER_WORDS):
        return DANGER
    if any(sign in probe for sign in _SUCCESS_SIGNS) or _word_hit(probe, _SUCCESS_WORDS):
        return SUCCESS
    return PRIMARY


_CYCLE = (SUCCESS, PRIMARY, DANGER)


def apply_to(markup):
    """Colour every default-styled button; explicit styles are left untouched.

    Telegram rows look best with one colour each for the first three buttons.
    Intent (action) picks the first colour, then duplicates inside the same row
    are moved to the next unused colour, so a row of up to three buttons never
    repeats a colour. Longer rows cycle colours while keeping neighbours
    different. Explicit ``style=`` values at call sites are treated as already
    used and never changed.
    """
    rows = getattr(markup, "inline_keyboard", None)
    if not rows:
        return markup

    for row in rows:
        buttons = [button for button in (row or []) if button is not None]
        used = {
            getattr(button, "style", DEFAULT)
            for button in buttons
            if getattr(button, "style", DEFAULT) not in (None, DEFAULT)
        }
        previous = None

        for button in buttons:
            current = getattr(button, "style", DEFAULT)
            if current not in (None, DEFAULT):
                previous = current
                continue

            wanted = style_for(getattr(button, "text", ""),
                               getattr(button, "callback_data", ""))
            if wanted not in used:
                chosen = wanted
            else:
                chosen = next((color for color in _CYCLE if color not in used), None)
                if chosen is None:
                    # More than three buttons in one row: repeat is unavoidable,
                    # but keep neighbouring buttons visibly different.
                    chosen = next((color for color in _CYCLE if color != previous), PRIMARY)

            button.style = chosen
            used.add(chosen)
            previous = chosen
    return markup


_installed = False


def install() -> None:
    """Make every newly-built InlineKeyboardMarkup fully coloured."""
    global _installed
    if _installed:
        return
    original = InlineKeyboardMarkup.__init__

    def styled_init(self, inline_keyboard, *args, **kwargs):
        original(self, inline_keyboard, *args, **kwargs)
        apply_to(self)

    InlineKeyboardMarkup.__init__ = styled_init
    _installed = True


install()
