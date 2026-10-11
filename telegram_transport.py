"""Bounded resilience for Bot API requests.

Telegram network timeouts are transient and should not turn an otherwise
healthy handler into a user-facing internal error. Retries are deliberately
bounded because a timed-out write may already have been accepted by Telegram.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError

logger = logging.getLogger(__name__)

# Telegram limits text to 4096 UTF-16 code units and media captions to 1024.
# Keep a small margin because Python's ``len`` counts Unicode code points, not
# UTF-16 units (emoji can therefore count as two units on the Bot API side).
_MESSAGE_SAFE_LIMIT = 3900
_CAPTION_SAFE_LIMIT = 980


def _plain_text(value: str) -> str:
    """Remove HTML/Markdown-looking tags for an emergency oversized payload."""
    return re.sub(r"</?[A-Za-z][^>]*>", "", value)


def _utf16_units(value: str) -> int:
    return len(value.encode('utf-16-le')) // 2


def _trim_utf16(value: str, limit: int) -> str:
    """Trim by Telegram's UTF-16 unit limit without splitting a code point."""
    if _utf16_units(value) <= limit:
        return value
    low, high = 0, len(value)
    while low < high:
        middle = (low + high + 1) // 2
        if _utf16_units(value[:middle]) <= limit:
            low = middle
        else:
            high = middle - 1
    return value[:low]


def _split_text(value: str, limit: int = _MESSAGE_SAFE_LIMIT) -> list[str]:
    """Split long text on line/sentence boundaries before falling back to hard cut."""
    text = _plain_text(value)
    chunks = []
    while _utf16_units(text) > limit:
        # Use a generous character window first, then trim precisely by UTF-16
        # units for emoji-heavy messages.
        window = _trim_utf16(text, limit)
        cut = max(window.rfind("\n"), window.rfind(". "))
        if cut < len(window) // 2:
            cut = window.rfind(" ")
        if cut < len(window) // 2:
            cut = len(window)
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text or not chunks:
        chunks.append(text)
    return chunks


def _clone_method(method, **updates):
    """Copy an aiogram method on both Pydantic v2 and older aiogram builds."""
    copier = getattr(method, "model_copy", None)
    if copier:
        return copier(update=updates)
    return method.copy(update=updates)


class ResilientAiohttpSession(AiohttpSession):
    """Aiohttp Bot API session with one bounded network retry."""

    def __init__(self, *, max_network_retries: int = 1,
                 retry_delay: float = 0.75, **kwargs):
        self.max_network_retries = max(0, int(max_network_retries))
        self.retry_delay = max(0.1, float(retry_delay))
        super().__init__(**kwargs)

    async def _make_once(self, bot, method, timeout: Optional[int] = None):
        for attempt in range(self.max_network_retries + 1):
            try:
                return await super().make_request(bot, method, timeout=timeout)
            except (TelegramNetworkError, asyncio.TimeoutError) as error:
                if attempt >= self.max_network_retries:
                    raise
                delay = self.retry_delay * (attempt + 1)
                logger.warning(
                    "Telegram Bot API network timeout for %s; bounded retry %s/%s in %.2fs",
                    type(method).__name__, attempt + 1, self.max_network_retries, delay,
                )
                await asyncio.sleep(delay)
        return None  # pragma: no cover - loop always returns or raises

    async def make_request(self, bot, method, timeout: Optional[int] = None):
        # A long private-chat/report notification must not turn into an
        # unhandled MESSAGE_TOO_LONG and abort the surrounding handler. Split
        # SendMessage into plain-text chunks; edits and captions are truncated
        # because Telegram has no multi-message equivalent for those methods.
        text = getattr(method, 'text', None)
        if isinstance(text, str) and _utf16_units(text) > _MESSAGE_SAFE_LIMIT:
            if type(method).__name__ == 'SendMessage':
                chunks = _split_text(text)
                first = None
                for index, chunk in enumerate(chunks):
                    updates = {
                        'text': chunk,
                        'parse_mode': None,
                        'entities': None,
                    }
                    if index < len(chunks) - 1:
                        updates['reply_markup'] = None
                    current = _clone_method(method, **updates)
                    result = await self._make_once(bot, current, timeout=timeout)
                    if first is None:
                        first = result
                return first
            method = _clone_method(method, **{
                'text': _trim_utf16(_plain_text(text), _MESSAGE_SAFE_LIMIT).rstrip() + '…',
                'parse_mode': None,
                'entities': None,
            })

        caption = getattr(method, 'caption', None)
        if isinstance(caption, str) and _utf16_units(caption) > _CAPTION_SAFE_LIMIT:
            method = _clone_method(method, **{
                'caption': _trim_utf16(_plain_text(caption), _CAPTION_SAFE_LIMIT).rstrip() + '…',
                'parse_mode': None,
                'caption_entities': None,
            })

        return await self._make_once(bot, method, timeout=timeout)
