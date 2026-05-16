"""Async loop — раз в минуту запускает watchdog.check_and_act."""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

from .watchdog import check_and_act

logger = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 60


async def short_bots_guard_loop(stop_event: asyncio.Event, *,
                                  send_fn: Optional[Callable[[str], None]] = None,
                                  interval_sec: int = POLL_INTERVAL_SEC) -> None:
    logger.info("short_bots_guard.start interval=%ds", interval_sec)
    while not stop_event.is_set():
        try:
            res = check_and_act(send_fn=send_fn)
            if res.get("paused") or res.get("resumed"):
                logger.info("short_bots_guard.tick %s", res)
        except Exception:
            logger.exception("short_bots_guard.tick_failed")
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            continue
    logger.info("short_bots_guard.stopped")
