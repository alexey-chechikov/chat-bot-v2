"""Pump-freeze async loop — bidirectional.

For each bot in APPLIES_TO_BOTS:
  side='short' → check up-pump, freeze on confirmed pump
  side='long'  → check down-dump, freeze on confirmed dump
"""
from __future__ import annotations

import asyncio
import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from services.pump_freeze.config import (
    APPLIES_TO_BOTS,
    MIN_POSITION_USD_TO_TRIGGER,
    RESUME_RETRACEMENT_PCT,
    RESUME_TIMEOUT_HOURS,
    TICK_INTERVAL_SEC,
)
from services.pump_freeze.detector import detect_move, should_resume
from services.pump_freeze.freezer import (
    freeze,
    frozen_info,
    get_extreme_during_freeze,
    is_frozen,
    position_usd_abs,
    resume,
    update_extreme,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
MARKET_1M_CSV = ROOT / "market_live" / "market_1m.csv"
SNAPSHOTS_CSV = ROOT / "ginarea_live" / "snapshots.csv"
MANAGED_JSON = ROOT / "state" / "short_bots_managed.json"


def _load_recent_bars(needed_min: int = 35) -> list:
    if not MARKET_1M_CSV.exists():
        return []
    bars: list = []
    try:
        with MARKET_1M_CSV.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    ts = datetime.fromisoformat(row["ts_utc"].replace("Z", "+00:00"))
                    hi = float(row["high"]); lo = float(row["low"]); cl = float(row["close"])
                    bars.append((ts, hi, lo, cl))
                except (KeyError, ValueError):
                    continue
    except OSError:
        return []
    return bars[-needed_min:] if len(bars) > needed_min else bars


def _read_bot_meta(bot_id: str) -> tuple[Optional[float], str, str]:
    """Latest raw position + alias + tier."""
    pos = None
    if SNAPSHOTS_CSV.exists():
        try:
            with SNAPSHOTS_CSV.open("rb") as f:
                f.seek(0, 2); size = f.tell()
                f.seek(max(0, size - 200_000))
                tail = f.read().decode("utf-8", errors="ignore")
            lines = tail.splitlines()[1:]
            with SNAPSHOTS_CSV.open("r", encoding="utf-8") as fh:
                header = next(csv.reader(fh))
            for row in csv.reader(lines):
                if len(row) != len(header):
                    continue
                r = dict(zip(header, row))
                if str(r.get("bot_id", "")).split(".")[0] != bot_id:
                    continue
                try:
                    pos = float(r.get("position", "") or 0)
                except ValueError:
                    pass
        except OSError:
            pass
    alias, tier = bot_id, bot_id
    if MANAGED_JSON.exists():
        try:
            mgd = json.loads(MANAGED_JSON.read_text(encoding="utf-8"))
            for entry in mgd.get("managed_bots", []):
                if str(entry.get("bot_id")) == bot_id:
                    alias = entry.get("alias", bot_id)
                    tier = entry.get("tier", bot_id)
                    break
        except (OSError, json.JSONDecodeError):
            pass
    return pos, alias, tier


def _api_pause(bot_id: int) -> dict:
    from services.short_bots_guard.control import _build_api
    api, err = _build_api()
    if api is None:
        raise RuntimeError(f"api_build_failed: {err}")
    return api.pause_bot(bot_id)


def _api_resume(bot_id: int) -> dict:
    from services.short_bots_guard.control import _build_api
    api, err = _build_api()
    if api is None:
        raise RuntimeError(f"api_build_failed: {err}")
    return api.resume_bot(bot_id)


def tick(*, send_fn: Optional[Callable] = None,
         now: Optional[datetime] = None) -> dict:
    if now is None:
        now = datetime.now(timezone.utc)
    bars = _load_recent_bars()
    if len(bars) < 31:
        return {"frozen": 0, "resumed": 0}
    current_price = bars[-1][3]

    # Detect both directions (single read of bars)
    up_event = detect_move(bars, direction="up")
    down_event = detect_move(bars, direction="down")

    frozen_count = 0
    resumed_count = 0
    for bot_id, side in APPLIES_TO_BOTS.items():
        raw_pos, alias, tier = _read_bot_meta(bot_id)
        if raw_pos is None:
            continue

        if is_frozen(bot_id):
            update_extreme(bot_id, current_price, side)
            fz = frozen_info(bot_id)
            try:
                freeze_ts = datetime.fromisoformat(fz["freeze_ts"])
            except (KeyError, ValueError):
                continue
            done, reason = should_resume(
                freeze_extreme_price=get_extreme_during_freeze(bot_id),
                current_price=current_price,
                freeze_ts=freeze_ts, now=now, side=side,
                retrace_pct=RESUME_RETRACEMENT_PCT,
                timeout_hours=RESUME_TIMEOUT_HOURS,
            )
            if done:
                resume(bot_id=bot_id, alias=alias, tier=tier, side=side,
                       current_price=current_price, resume_reason=reason,
                       extreme_during_freeze=get_extreme_during_freeze(bot_id),
                       resume_api_fn=_api_resume, send_fn=send_fn, now=now)
                resumed_count += 1
            continue

        # Direction relevant to this bot
        event = up_event if side == "short" else down_event
        if event is None:
            continue

        pos_usd = position_usd_abs(raw_pos, side, current_price)
        if pos_usd < MIN_POSITION_USD_TO_TRIGGER:
            continue

        freeze(bot_id=bot_id, alias=alias, tier=tier, side=side,
               event=event, raw_position=raw_pos, position_usd=pos_usd,
               pause_api_fn=_api_pause, send_fn=send_fn, now=now)
        frozen_count += 1

    return {"frozen": frozen_count, "resumed": resumed_count}


async def pump_freeze_loop(stop_event: asyncio.Event, *,
                            send_fn: Optional[Callable] = None,
                            interval_sec: int = TICK_INTERVAL_SEC) -> None:
    logger.info("pump_freeze.loop.start interval=%ds applies_to=%s",
                interval_sec, list(APPLIES_TO_BOTS.items()))
    while not stop_event.is_set():
        try:
            r = tick(send_fn=send_fn)
            if r["frozen"] or r["resumed"]:
                logger.info("pump_freeze.tick frozen=%d resumed=%d",
                            r["frozen"], r["resumed"])
        except Exception:
            logger.exception("pump_freeze.tick_failed")
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()),
                                    timeout=interval_sec)
        except asyncio.TimeoutError:
            continue
    logger.info("pump_freeze.loop.stopped")
