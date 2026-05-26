"""Shared Telegram send-with-retry helper.

Every bot7 service that ships messages to Telegram should route through
this. Centralises:
  - linear backoff (2s, 4s, 6s — total ~12s worst case)
  - structured logging on failure
  - best-effort semantics (never raises, never crashes the calling loop)

The Telegram REST API throws `requests.exceptions.ReadTimeout` once every
few hours on a busy bot. Without retry the alert is lost — the operator
silently never learns about a STALE feed, a cascade, an autotrader fill.

Usage:

    from services.common.tg_send_with_retry import send_with_retry
    send_with_retry(bot, [chat_id], "🔴 alert text")

Or as a `send_fn` adapter for older code paths:

    from services.common.tg_send_with_retry import make_send_fn
    send_fn = make_send_fn(bot, [chat_id_a, chat_id_b])
    send_fn("hello")
"""
from __future__ import annotations

import logging
import time
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

DEFAULT_RETRIES = 3
DEFAULT_BACKOFF_SEC = 2.0


def send_with_retry(bot: Any, chat_ids: Iterable[int], text: str, *,
                     retries: int = DEFAULT_RETRIES,
                     backoff_sec: float = DEFAULT_BACKOFF_SEC,
                     where: Optional[str] = None,
                     reply_markup: Any = None) -> dict[int, bool]:
    """Send `text` to each chat in `chat_ids`, retrying on failure.

    Returns {chat_id: delivered_ok} — caller can introspect partial
    failures, but doesn't need to (best-effort design).

    `where` is a short tag used in log messages (e.g. "cascade_alert" or
    "stale_monitor") so operators can grep their service quickly.

    Never raises. Never sleeps if no chat_ids are supplied.
    """
    cids = [int(c) for c in chat_ids if c is not None]
    result: dict[int, bool] = {cid: False for cid in cids}
    if not bot or not cids:
        return result
    tag = where or "tg_send"
    for cid in cids:
        for attempt in range(retries):
            try:
                if reply_markup is not None:
                    bot.send_message(cid, text, reply_markup=reply_markup)
                else:
                    bot.send_message(cid, text)
                result[cid] = True
                break  # success — next chat
            except Exception:
                if attempt + 1 >= retries:
                    logger.exception(
                        "%s.send_failed_giveup cid=%s attempt=%d/%d",
                        tag, cid, attempt + 1, retries,
                    )
                else:
                    logger.warning(
                        "%s.send_failed_retry cid=%s attempt=%d/%d",
                        tag, cid, attempt + 1, retries,
                    )
                    time.sleep(backoff_sec * (attempt + 1))
    return result


def make_send_fn(bot: Any, chat_ids: Iterable[int], *,
                  where: Optional[str] = None,
                  retries: int = DEFAULT_RETRIES,
                  backoff_sec: float = DEFAULT_BACKOFF_SEC):
    """Build a `send_fn(text, *, reply_markup=None, meta=None)` closure that
    delegates to send_with_retry. Drop-in for legacy call sites that
    expect a single-arg callable.

    Accepts `meta` kwarg (ignored — kept for compatibility with
    channel_router signatures)."""
    cids = list(chat_ids)
    tag = where or "tg_send"

    def _send(text: str, *, reply_markup: Any = None, meta: Any = None) -> None:
        send_with_retry(bot, cids, text, retries=retries,
                          backoff_sec=backoff_sec, where=tag,
                          reply_markup=reply_markup)

    return _send
