"""Freezer — bidirectional pause/resume + journal + TG notification."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from services.pump_freeze.config import (
    JOURNAL_PATH,
    RESUME_RETRACEMENT_PCT,
    RESUME_TIMEOUT_HOURS,
    STATE_PATH,
)
from services.pump_freeze.detector import MoveEvent

logger = logging.getLogger(__name__)


def _read_state() -> dict:
    if not STATE_PATH.exists():
        return {"frozen": {}}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"frozen": {}}


def _write_state(state: dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                                encoding="utf-8")
    except OSError:
        logger.exception("pump_freeze.write_state_failed")


def _append_journal(record: dict) -> None:
    try:
        JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with JOURNAL_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("pump_freeze.append_journal_failed")


def is_frozen(bot_id: str) -> bool:
    return bot_id in _read_state().get("frozen", {})


def frozen_info(bot_id: str) -> Optional[dict]:
    return _read_state().get("frozen", {}).get(bot_id)


def position_usd_abs(raw_pos: float, side: str, mid_btc: float) -> float:
    """SHORT inverse XBTUSD: |BTC| × mid; LONG linear XBTUSDT: |USDT|."""
    if side == "short":
        return abs(raw_pos) * mid_btc
    return abs(raw_pos)


def freeze(*, bot_id: str, alias: str, tier: str, side: str,
           event: MoveEvent, raw_position: float, position_usd: float,
           pause_api_fn: Callable[[int], dict],
           send_fn: Optional[Callable] = None,
           now: Optional[datetime] = None) -> bool:
    if now is None:
        now = datetime.now(timezone.utc)
    try:
        pause_api_fn(int(bot_id))
    except Exception as e:
        logger.exception("pump_freeze.api_pause_failed bot=%s err=%s", bot_id, e)
        return False

    alert_id = f"pf_{now.strftime('%Y%m%d_%H%M%S')}_{tier}"
    state = _read_state()
    state.setdefault("frozen", {})
    state["frozen"][bot_id] = {
        "freeze_ts": now.isoformat(timespec="seconds"),
        "freeze_move_pct": event.move_pct,
        "freeze_direction": event.direction,
        "freeze_side": side,
        "freeze_extreme_price": event.price_now,
        "freeze_position_raw": raw_position,
        "freeze_position_usd": position_usd,
        "alert_id": alert_id,
    }
    _write_state(state)

    if send_fn is not None:
        from datetime import timedelta
        expected_resume = now + timedelta(hours=RESUME_TIMEOUT_HOURS)
        emoji = "🛑 PUMP" if event.direction == "up" else "🛑 DUMP"
        action_word = "PUMP" if event.direction == "up" else "DUMP"
        msg = (
            f"{emoji} FREEZE [{tier}]  BTC {event.move_pct:+.2f}% за 30мин\n"
            f"  Price: ${event.price_window_start:,.0f} → ${event.price_now:,.0f}\n"
            f"  Position: {raw_position:+.4f}  (≈${position_usd:,.0f} {side.upper()})\n"
            f"  Pause до: {expected_resume.strftime('%H:%M UTC')} (+{RESUME_TIMEOUT_HOURS}h)\n"
            f"        OR откат -{RESUME_RETRACEMENT_PCT}% от extreme\n"
            f"  Goal: остановить добор {side.upper()} пока {action_word.lower()} не закончится"
        )
        try:
            send_fn(msg)
        except Exception:
            logger.exception("pump_freeze.tg_freeze_send_failed")

    logger.info("pump_freeze.frozen bot=%s side=%s move=%.2f%% price=%.0f pos_usd=%.0f",
                bot_id, side, event.move_pct, event.price_now, position_usd)
    return True


def resume(*, bot_id: str, alias: str, tier: str, side: str,
           current_price: float, resume_reason: str, extreme_during_freeze: float,
           resume_api_fn: Callable[[int], dict],
           send_fn: Optional[Callable] = None,
           now: Optional[datetime] = None) -> bool:
    if now is None:
        now = datetime.now(timezone.utc)
    state = _read_state()
    fz = state.get("frozen", {}).get(bot_id)
    if not fz:
        return False
    try:
        resume_api_fn(int(bot_id))
    except Exception:
        logger.exception("pump_freeze.api_resume_failed bot=%s", bot_id)
        return False

    pos_usd = abs(float(fz.get("freeze_position_usd", 0)))
    freeze_price = float(fz.get("freeze_extreme_price", 0))
    # Estimated saved DD = 0.5 × pos × |extreme - freeze_price|
    est_saved = 0.5 * pos_usd * abs(extreme_during_freeze - freeze_price) / max(freeze_price, 1)

    record = {
        "alert_id": fz.get("alert_id"),
        "ts_freeze": fz.get("freeze_ts"),
        "ts_resume": now.isoformat(timespec="seconds"),
        "bot_id": bot_id, "alias": alias, "tier": tier, "side": side,
        "direction": fz.get("freeze_direction"),
        "freeze_price": freeze_price,
        "freeze_move_pct": fz.get("freeze_move_pct"),
        "freeze_position_raw": fz.get("freeze_position_raw"),
        "freeze_position_usd": fz.get("freeze_position_usd"),
        "resume_price": round(current_price, 2),
        "resume_reason": resume_reason,
        "extreme_price_during_freeze": round(extreme_during_freeze, 2),
        "estimated_saved_usd": round(est_saved, 2),
    }
    _append_journal(record)
    del state["frozen"][bot_id]
    _write_state(state)

    if send_fn is not None:
        msg = (
            f"▶ RESUME [{tier}]  reason: {resume_reason}\n"
            f"  Freeze price: ${freeze_price:,.0f} → Current: ${current_price:,.0f}\n"
            f"  Extreme during freeze: ${extreme_during_freeze:,.0f}\n"
            f"  Estimated saved DD: ${est_saved:,.0f}"
        )
        try:
            send_fn(msg)
        except Exception:
            logger.exception("pump_freeze.tg_resume_send_failed")

    logger.info("pump_freeze.resumed bot=%s side=%s reason=%s saved=$%.0f",
                bot_id, side, resume_reason, est_saved)
    return True


def update_extreme(bot_id: str, current_price: float, side: str) -> None:
    """Track max (SHORT freeze) или min (LONG freeze) price during freeze."""
    state = _read_state()
    fz = state.get("frozen", {}).get(bot_id)
    if not fz:
        return
    cur_extreme = float(fz.get("extreme_during_freeze")
                          or fz.get("freeze_extreme_price", 0))
    if side == "short":
        if current_price > cur_extreme:
            fz["extreme_during_freeze"] = current_price
            _write_state(state)
    else:  # long: track minimum
        if current_price < cur_extreme:
            fz["extreme_during_freeze"] = current_price
            _write_state(state)


def get_extreme_during_freeze(bot_id: str) -> float:
    fz = frozen_info(bot_id) or {}
    return float(fz.get("extreme_during_freeze") or fz.get("freeze_extreme_price", 0))
