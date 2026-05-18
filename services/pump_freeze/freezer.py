"""Freezer — apply pause via BotsAPI + journal + TG notification.

State file: state/pump_freeze_state.json
  {
    "frozen": {
      "4525648417": {
        "freeze_ts": "ISO",
        "freeze_pump_pct": 1.85,
        "freeze_peak_price": 67100.0,
        "freeze_position_btc": -0.45,
        "tg_alert_id": "pf_20260518_HHMMSS_TB"
      }
    }
  }

Journal: state/pump_freeze_events.jsonl per event:
  {
    "alert_id": "pf_..._TB",
    "ts_freeze":, "ts_resume":,
    "bot_id":, "alias":, "tier":,
    "freeze_price":, "freeze_pump_pct":, "freeze_position_btc":,
    "resume_price":, "resume_reason":,
    "peak_price_during_freeze":,
    "estimated_saved_usd":   # 0.5 × position × (peak - freeze_price)
  }
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from services.pump_freeze.config import JOURNAL_PATH, STATE_PATH
from services.pump_freeze.detector import PumpEvent

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
    state = _read_state()
    return bot_id in state.get("frozen", {})


def frozen_info(bot_id: str) -> Optional[dict]:
    state = _read_state()
    return state.get("frozen", {}).get(bot_id)


def freeze(*, bot_id: str, alias: str, tier: str,
           event: PumpEvent, position_btc: float,
           pause_api_fn: Callable[[int], dict],
           send_fn: Optional[Callable] = None,
           now: Optional[datetime] = None) -> bool:
    """Apply pause to bot via API, record state + journal + TG notify."""
    if now is None:
        now = datetime.now(timezone.utc)

    # Try GinArea pause
    try:
        pause_api_fn(int(bot_id))
    except Exception as e:
        logger.exception("pump_freeze.api_pause_failed bot=%s err=%s", bot_id, e)
        return False

    alert_id = f"pf_{now.strftime('%Y%m%d_%H%M%S')}_{tier}"

    # Record state
    state = _read_state()
    state.setdefault("frozen", {})
    state["frozen"][bot_id] = {
        "freeze_ts": now.isoformat(timespec="seconds"),
        "freeze_pump_pct": event.move_pct,
        "freeze_peak_price": event.price_now,
        "freeze_position_btc": position_btc,
        "alert_id": alert_id,
    }
    _write_state(state)

    # TG notification
    if send_fn is not None:
        from datetime import timedelta
        from services.pump_freeze.config import RESUME_TIMEOUT_HOURS, RESUME_RETRACEMENT_PCT
        expected_resume = now + timedelta(hours=RESUME_TIMEOUT_HOURS)
        msg = (
            f"🛑 PUMP FREEZE [{tier}]  BTC +{event.move_pct:.2f}% за 30мин\n"
            f"  Price: ${event.price_window_start:,.0f} → ${event.price_now:,.0f}\n"
            f"  Position: {position_btc:.4f} BTC SHORT  (≈${abs(position_btc * event.price_now):,.0f})\n"
            f"  Pause до: {expected_resume.strftime('%H:%M UTC')} (+{RESUME_TIMEOUT_HOURS}h timeout)\n"
            f"        OR откат -{RESUME_RETRACEMENT_PCT}% от peak (что раньше)\n"
            f"  Goal: остановить добор пока pump не закончится"
        )
        try:
            send_fn(msg)
        except Exception:
            logger.exception("pump_freeze.tg_freeze_send_failed")

    logger.info("pump_freeze.frozen bot=%s pump=%.2f%% price=%.0f pos=%.4f",
                bot_id, event.move_pct, event.price_now, position_btc)
    return True


def resume(*, bot_id: str, alias: str, tier: str,
           current_price: float, resume_reason: str, peak_during_freeze: float,
           resume_api_fn: Callable[[int], dict],
           send_fn: Optional[Callable] = None,
           now: Optional[datetime] = None) -> bool:
    """Unpause bot + record + notify."""
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

    # Estimated saved DD = 0.5 × |position| × (peak - freeze_price)
    pos = abs(float(fz.get("freeze_position_btc", 0)))
    freeze_price = float(fz.get("freeze_peak_price", 0))
    est_saved = 0.5 * pos * max(peak_during_freeze - freeze_price, 0)

    record = {
        "alert_id": fz.get("alert_id"),
        "ts_freeze": fz.get("freeze_ts"),
        "ts_resume": now.isoformat(timespec="seconds"),
        "bot_id": bot_id, "alias": alias, "tier": tier,
        "freeze_price": freeze_price,
        "freeze_pump_pct": fz.get("freeze_pump_pct"),
        "freeze_position_btc": fz.get("freeze_position_btc"),
        "resume_price": round(current_price, 2),
        "resume_reason": resume_reason,
        "peak_price_during_freeze": round(peak_during_freeze, 2),
        "estimated_saved_usd": round(est_saved, 2),
    }
    _append_journal(record)

    # Remove from frozen state
    del state["frozen"][bot_id]
    _write_state(state)

    if send_fn is not None:
        msg = (
            f"▶ RESUME [{tier}]  reason: {resume_reason}\n"
            f"  Freeze price: ${freeze_price:,.0f} → Current: ${current_price:,.0f}\n"
            f"  Peak during freeze: ${peak_during_freeze:,.0f}\n"
            f"  Estimated saved DD: ${est_saved:,.0f}"
        )
        try:
            send_fn(msg)
        except Exception:
            logger.exception("pump_freeze.tg_resume_send_failed")

    logger.info("pump_freeze.resumed bot=%s reason=%s saved=$%.0f",
                bot_id, resume_reason, est_saved)
    return True


def update_peak(bot_id: str, current_price: float) -> None:
    """Track max price during freeze для estimated_saved_usd."""
    state = _read_state()
    fz = state.get("frozen", {}).get(bot_id)
    if not fz:
        return
    cur_peak = float(fz.get("peak_during_freeze") or fz.get("freeze_peak_price", 0))
    if current_price > cur_peak:
        fz["peak_during_freeze"] = current_price
        _write_state(state)


def get_peak_during_freeze(bot_id: str) -> float:
    fz = frozen_info(bot_id) or {}
    return float(fz.get("peak_during_freeze") or fz.get("freeze_peak_price", 0))
