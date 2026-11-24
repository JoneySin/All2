"""Inline keyboard builders with Kurigram's native button styles.

Telegram clients released after 9 February 2026 understand the optional button
``style`` field. Kurigram exposes it directly as
``InlineKeyboardButton(style=enums.ButtonStyle.X)``, so this project builds every
keyboard through :func:`ui_button` and :func:`ui_keyboard` instead of the raw
types.

Design:
* ``ui_button`` gives each button a semantic colour from its action, while an
  explicit ``style=`` still wins.
* ``ui_keyboard`` enforces the visual rule that a row must not repeat a colour:
  if two actions resolve to the same colour, the later button moves to the next
  unused colour. Rows longer than three buttons cycle while keeping neighbours
  different (Telegram has three colour styles).
* Importing this module has no side effects and no third-party classes are
  patched.
"""

from __future__ import annotations

import re

from pyrogram import enums
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

PRIMARY = enums.ButtonStyle.PRIMARY
SUCCESS = enums.ButtonStyle.SUCCESS
DANGER = enums.ButtonStyle.DANGER
DEFAULT = enums.ButtonStyle.DEFAULT

_CYCLE = (SUCCESS, PRIMARY, DANGER)
_DANGER_WORDS = (
    "close", "cancel", "reject", "delete", "remove", "stop", "leave", "ban",
    "disable", "logout", "log out", "clear", "reset", "restart", "decline",
    "abort", "destroy", "wipe", "purge", "truncate",
)
_SUCCESS_WORDS = (
    "watch", "play", "download", "stream", "buy", "premium", "activate",
    "approve", "confirm", "join", "subscribe", "renew", "start", "index",
    "send", "add", "link", "resume", "verify",
)
_DANGER_SIGNS = ("❌", "✖", "🗑")
_SUCCESS_SIGNS = ("✅", "➕", "🔗")


def _word_hit(text: str, words: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", text) for word in words)


def style_for(text: str = "", action: str | bytes = "") -> enums.ButtonStyle:
    """Return the semantic colour for a button label and its callback/URL."""
    if isinstance(action, bytes):
        action = action.decode("utf-8", "ignore")
    probe = f"{text or ''} {action or ''}".lower()
    if any(sign in probe for sign in _DANGER_SIGNS) or _word_hit(probe, _DANGER_WORDS):
        return DANGER
    if any(sign in probe for sign in _SUCCESS_SIGNS) or _word_hit(probe, _SUCCESS_WORDS):
        return SUCCESS
    return PRIMARY


def ui_button(
    text: str,
    *,
    callback_data: str | None = None,
    url: str | None = None,
    style: enums.ButtonStyle | None = None,
    **kwargs,
) -> InlineKeyboardButton:
    """Build a Kurigram inline button with a native, semantic colour."""
    if style is None:
        style = style_for(text, callback_data if callback_data is not None else url)
    if callback_data is not None:
        kwargs["callback_data"] = callback_data
    if url is not None:
        kwargs["url"] = url
    return InlineKeyboardButton(text, style=style, **kwargs)


def _colour_row(buttons: list[InlineKeyboardButton]) -> None:
    used = set()
    previous = None
    for button in buttons:
        preferred = getattr(button, "style", DEFAULT)
        if preferred in (None, DEFAULT):
            preferred = style_for(getattr(button, "text", ""),
                                  getattr(button, "callback_data", "") or "")
        if preferred not in used:
            chosen = preferred
        else:
            chosen = next((colour for colour in _CYCLE if colour not in used), None)
            if chosen is None:
                # More than three buttons in one row: a repeat is unavoidable,
                # but neighbours must still be visibly different.
                chosen = next((colour for colour in _CYCLE if colour != previous), PRIMARY)
        button.style = chosen
        used.add(chosen)
        previous = chosen


def ui_keyboard(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    """Build a Kurigram keyboard and enforce one colour per row."""
    markup = InlineKeyboardMarkup(rows)
    for row in markup.inline_keyboard:
        _colour_row([button for button in row if button is not None])
    return markup


__all__ = [
    "DANGER",
    "PRIMARY",
    "SUCCESS",
    "style_for",
    "ui_button",
    "ui_keyboard",
]
