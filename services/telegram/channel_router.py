"""Build a send_fn that routes by emitter type into PRIMARY vs ROUTINE chats.

Every emitter-loop in app_runner constructs a `send_fn(text)` closure that
posts to all `allowed_chat_ids`. This module replaces that pattern with
`build_send_fn(telegram_app, emitter)` which:

  - looks up the channel for the emitter via alert_router.channel_for(emitter)
  - sends to ALLOWED_CHAT_IDS if PRIMARY (default)
  - sends to ROUTINE_CHAT_IDS if emitter is ROUTINE-class
  - silently no-ops if no chat ids are configured for that channel

Backward-compat: if `ROUTINE_CHAT_IDS` is not set in the environment, ROUTINE
emitters fall back to the primary chat — current behavior, nothing breaks.

Severity prefix:
  - The returned send_fn accepts an optional `meta` kwarg. If passed, it is
    forwarded to severity_prefix.classify_severity() to pick 🔴/🟠/🟡/⚪.
  - If `meta` is not passed (most legacy callers), the prefix is derived
    from the emitter alone (no meta-based escalation to CRITICAL).
"""
from __future__ import annotations

import logging
import os
from typing import Any

from services.telegram.alert_router import PRIMARY, ROUTINE, channel_for
from services.telegram.severity_prefix import classify_severity, with_prefix

logger = logging.getLogger(__name__)


def _parse_chat_ids(raw: str) -> list[int]:
    out: list[int] = []
    for piece in raw.replace(";", ",").split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            out.append(int(piece))
        except ValueError:
            logger.warning("channel_router.bad_chat_id raw=%r", piece)
    return out


def get_routine_chat_ids() -> list[int]:
    """Read ROUTINE_CHAT_IDS env var. Empty list → fall back to PRIMARY chats."""
    return _parse_chat_ids(os.getenv("ROUTINE_CHAT_IDS", ""))


def build_send_fn(telegram_app: Any, emitter: str):
    """Return send_fn(text, *, meta=None) that routes by emitter channel.

    Uses services.common.tg_send_with_retry under the hood (3 attempts,
    linear backoff) so transient telegram.org timeouts don't drop alerts.
    """
    if telegram_app is None or not getattr(telegram_app, "allowed_chat_ids", None):
        return None

    primary_chat_ids = list(telegram_app.allowed_chat_ids)
    routine_chat_ids = get_routine_chat_ids() or primary_chat_ids
    bot = telegram_app.bot
    channel = channel_for(emitter)

    target_chat_ids = routine_chat_ids if channel == ROUTINE else primary_chat_ids

    from services.common.tg_send_with_retry import send_with_retry

    def _send(text: str, *, meta: dict | None = None,
                reply_markup: Any = None) -> None:
        try:
            sev = classify_severity(emitter, text, meta)
            text = with_prefix(sev, text)
        except Exception:
            logger.exception("channel_router.prefix_failed emitter=%s", emitter)
        send_with_retry(
            bot, target_chat_ids, text,
            where=f"channel_router.{emitter}.{channel.lower()}",
            reply_markup=reply_markup,
        )

    return _send
