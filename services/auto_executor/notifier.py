"""Telegram notifier for auto_executor — uses MICRO_BOT_TOKEN + MICRO_CHAT_ID.

Standalone telebot instance (not bot7's main bot) so:
  - bot7's main TG flow is untouched
  - autotrader can post even if main bot's polling crashes
  - operator can mute/leave the autotrader chat independently

Every notification is best-effort: logs on send failure, does NOT raise.
The autotrader must keep trading even if Telegram is down.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_bot: Optional[object] = None  # telebot.TeleBot, lazy-init
_chat_ids: list[int] = []


def _init() -> bool:
    """Lazy-init the telebot instance from env. Returns True if ready."""
    global _bot, _chat_ids
    if _bot is not None:
        return True
    token = os.environ.get("MICRO_BOT_TOKEN", "").strip()
    chat_raw = os.environ.get("MICRO_CHAT_ID", "").strip()
    if not token or not chat_raw:
        logger.warning("auto_executor.notifier.disabled — MICRO_BOT_TOKEN / MICRO_CHAT_ID not set")
        return False
    try:
        import telebot  # type: ignore
    except ImportError:
        logger.warning("auto_executor.notifier.disabled — telebot not installed")
        return False
    try:
        _bot = telebot.TeleBot(token)
        _chat_ids = []
        for piece in chat_raw.replace(";", ",").split(","):
            piece = piece.strip()
            if not piece:
                continue
            try:
                _chat_ids.append(int(piece))
            except ValueError:
                logger.warning("auto_executor.notifier.bad_chat_id raw=%r", piece)
        if not _chat_ids:
            logger.warning("auto_executor.notifier.no_chat_ids_parsed")
            _bot = None
            return False
        return True
    except Exception:
        logger.exception("auto_executor.notifier.init_failed")
        _bot = None
        return False


def send(text: str) -> None:
    """Send `text` to every configured chat. Best-effort; never raises."""
    if not _init():
        return
    for cid in _chat_ids:
        try:
            _bot.send_message(cid, text)  # type: ignore[attr-defined]
        except Exception:
            logger.exception("auto_executor.notifier.send_failed cid=%s", cid)


# ─── Cards ─────────────────────────────────────────────────────────
def _hh_mm(iso: Optional[str]) -> str:
    if not iso:
        return "?"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%H:%M UTC")
    except ValueError:
        return iso


def card_placed(pos) -> str:
    return (
        f"🟡 PLACED  {pos.setup_type}\n"
        f"  symbol: {pos.bitmex_symbol}\n"
        f"  entry:  ${pos.entry_price:.1f}  (post-only limit BUY)\n"
        f"  sl:     ${pos.sl_price:.1f}\n"
        f"  tp1:    ${pos.tp1_price:.1f}\n"
        f"  size:   {pos.qty_lots} lots = {pos.qty_btc:.6f} BTC ≈ ${pos.nominal_usd:.2f}\n"
        f"  expires: {_hh_mm(pos.expires_at)}"
    )


def card_filled(pos) -> str:
    return (
        f"🟢 FILLED  {pos.setup_type}\n"
        f"  avg_entry: ${(pos.avg_entry_price or pos.entry_price):.1f}\n"
        f"  size:      {pos.qty_lots} lots = {pos.qty_btc:.6f} BTC\n"
        f"  managing:  SL ${pos.sl_price:.1f}  TP1 ${pos.tp1_price:.1f}  exp {_hh_mm(pos.expires_at)}"
    )


def card_closed(pos) -> str:
    pnl = pos.realized_pnl_usd or 0.0
    sign = "🎯" if pnl > 0 else ("🛑" if pnl < 0 else "⏰")
    return (
        f"{sign} CLOSED [{pos.exit_reason}]  {pos.setup_type}\n"
        f"  avg_entry: ${(pos.avg_entry_price or pos.entry_price):.1f}\n"
        f"  avg_exit:  ${(pos.avg_exit_price or 0):.1f}\n"
        f"  pnl:       ${pnl:+.4f}\n"
        f"  setup_id:  {pos.setup_id}"
    )


def card_skipped(setup_type: str, reason: str) -> str:
    return f"⚪ SKIPPED  {setup_type}  ({reason})"


def card_freeze(scope: str, reason: str) -> str:
    return f"🧊 FREEZE  {scope}  ({reason})"


def card_error(where: str, exc: BaseException) -> str:
    return f"⚠️ ERROR  {where}\n  {type(exc).__name__}: {str(exc)[:300]}"
