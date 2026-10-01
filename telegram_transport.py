"""Bounded resilience for Bot API requests.

Telegram network timeouts are transient and should not turn an otherwise
healthy handler into a user-facing internal error. Retries are deliberately
bounded because a timed-out write may already have been accepted by Telegram.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError

logger = logging.getLogger(__name__)


class ResilientAiohttpSession(AiohttpSession):
    """Aiohttp Bot API session with one bounded network retry."""

    def __init__(self, *, max_network_retries: int = 1,
                 retry_delay: float = 0.75, **kwargs):
        self.max_network_retries = max(0, int(max_network_retries))
        self.retry_delay = max(0.1, float(retry_delay))
        super().__init__(**kwargs)

    async def make_request(self, bot, method, timeout: Optional[int] = None):
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
