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
    ML_GATE_ENABLED,
    MIN_POSITION_USD_TO_TRIGGER,
    PUMP_COOLDOWN_MIN,
    REFREEZE_RETURN_PCT,
    RESUME_RETRACEMENT_PCT,
    RESUME_STALL_MIN,
    RESUME_TIMEOUT_HOURS,
    TICK_INTERVAL_SEC,
)
from services.pump_freeze.detector import detect_move, should_resume
from services.pump_freeze.freezer import (
    freeze,
    frozen_info,
    get_extreme_during_freeze,
    get_last_extreme_ts,
    is_frozen,
    last_resume_info,
    last_resume_ts,
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


def _median(xs: list) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return 0.0
    m = n // 2
    return s[m] if n % 2 else (s[m - 1] + s[m]) / 2.0


def _load_feature_bars(needed: int = 1600) -> list:
    """Rich 1m bars (ts, open, high, low, close, volume) for the ML feature
    pipeline — longer history + open/volume, unlike _load_recent_bars()."""
    if not MARKET_1M_CSV.exists():
        return []
    bars: list = []
    try:
        with MARKET_1M_CSV.open("r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    ts = datetime.fromisoformat(row["ts_utc"].replace("Z", "+00:00"))
                    bars.append((ts, float(row["open"]), float(row["high"]),
                                 float(row["low"]), float(row["close"]),
                                 float(row["volume"])))
                except (KeyError, ValueError):
                    continue
    except OSError:
        return []
    return bars[-needed:] if len(bars) > needed else bars


def _funding_at(freeze_ts: datetime) -> Optional[float]:
    """funding_rate_8h (BTCUSDT) from deriv_live_history.jsonl — the record
    nearest freeze_ts. Funding is 8h-constant so ~5min log resolution is
    ample. None if unavailable."""
    path = ROOT / "state" / "deriv_live_history.jsonl"
    if not path.exists():
        return None
    best: Optional[tuple] = None
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                ts = datetime.fromisoformat(
                    rec["last_updated"].replace("Z", "+00:00"))
                fr = (rec.get("BTCUSDT") or {}).get("funding_rate_8h")
                if fr is None:
                    continue
                d = abs((ts - freeze_ts).total_seconds())
                if best is None or d < best[0]:
                    best = (d, float(fr))
            except (KeyError, ValueError, TypeError, json.JSONDecodeError):
                continue
    except OSError:
        return None
    return best[1] if best else None


def _compute_bar_features(bars: list, freeze_ts: datetime,
                          window: int = 30) -> dict:
    """The 8 bar-derived reliable features — computed to match
    build_event_catalog.py profile_event() column-for-column.

    `bars`: (ts, open, high, low, close, volume), chronological. Returns {}
    when the freeze anchor or required history is missing; omits any single
    feature it cannot compute (→ score_event None → gate dormant — safe).
    """
    feats: dict = {}
    if len(bars) < window + 3:
        return feats
    # anchor = last bar at/before freeze_ts
    a = None
    for i in range(len(bars) - 1, -1, -1):
        if bars[i][0] <= freeze_ts:
            a = i
            break
    if a is None or a < window:
        return feats
    op = [b[1] for b in bars]
    hi = [b[2] for b in bars]
    lo = [b[3] for b in bars]
    cl = [b[4] for b in bars]
    vol = [b[5] for b in bars]
    n = len(bars)
    ws = a - window
    trig = cl[a]
    if trig <= 0 or cl[ws] <= 0:
        return feats

    feats["move_pct"] = (trig - cl[ws]) / cl[ws] * 100.0

    wick = [hi[i] - lo[i] for i in range(ws, a + 1)]
    body = [abs(cl[i] - op[i]) for i in range(ws, a + 1)]
    feats["wick_ratio"] = (sum(wick) / len(wick)) / (sum(body) / len(body) + 1e-9)

    w = cl[ws:a + 1]
    d2 = [w[i + 2] - 2 * w[i + 1] + w[i] for i in range(len(w) - 2)]
    feats["accel"] = sum(abs(x) for x in d2) / len(d2) if d2 else 0.0

    win_vol = sum(vol[ws:a + 1])
    look = vol[max(0, a - 1440):a]
    base = _median(look) * window if look else 0.0
    if base > 0:
        feats["vol_spike"] = win_vol / base

    for h in (5, 15, 30, 60):
        j = min(a + h, n - 1)
        feats[f"move_t{h}"] = (cl[j] - trig) / trig * 100.0

    return feats


def build_live_features(bot_id: str, freeze_ts: datetime) -> dict:
    """Live feature vector for the ML resume-gate — 9 of the 10 reliable
    features from PUMP_FILTER_FEATURE_CONTRACT.md, matching
    build_event_catalog.py column-for-column.

    OMITTED: n_triggers — its catalog definition (full-event trigger count)
    has no clean live equivalent; pending Win's importance check. While it
    is absent, score_event() returns None for any model whose feature_order
    includes n_triggers → the gate stays dormant (safe). If Win drops
    n_triggers, the 9-feature model scores normally.
    """
    feats = _compute_bar_features(_load_feature_bars(), freeze_ts)
    if not feats:
        return {}
    fr = _funding_at(freeze_ts)
    if fr is not None:
        feats["funding_at_anchor"] = fr
    return feats


def _ml_gate_check(bot_id: str, side: str, freeze_ts: datetime,
                   now: datetime, bars: list) -> Optional[str]:
    """Return a resume-reason string if the ML-gate confidently calls the
    frozen event a whipsaw; else None (→ reactive logic decides).

    Dormant until the model artifact lands: model_available() is False, so
    this returns None and the reactive path runs unchanged.
    """
    if not ML_GATE_ENABLED:
        return None
    from services.pump_freeze import resume_model
    if not resume_model.model_available():
        return None
    age_min = (now - freeze_ts).total_seconds() / 60.0
    if age_min < resume_model.horizon_min():
        return None
    feats = build_live_features(bot_id, freeze_ts)
    score = resume_model.score_event(feats)
    if score is None:
        return None
    if resume_model.gate_decision(score) == "whipsaw":
        return f"ml_gate: whipsaw P={score:.2f} @age{age_min:.0f}m"
    return None


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
            update_extreme(bot_id, current_price, side, now=now)
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
                last_extreme_ts=get_last_extreme_ts(bot_id),
                stall_min=RESUME_STALL_MIN,
            )
            # ML resume-gate (Phase 4): if reactive says hold, a confident
            # whipsaw verdict from the model resumes early. Dormant until the
            # model artifact lands — _ml_gate_check returns None until then.
            if not done:
                ml_reason = _ml_gate_check(bot_id, side, freeze_ts, now, bars)
                if ml_reason:
                    done, reason = True, ml_reason
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

        # Re-freeze gate (2026-05-22 pullback research): time-cooldown заменён
        # price-based gate. После resume не фризим заново на том же откате —
        # ждём пока цена вернётся ≥REFREEZE_RETURN_PCT% к extreme движения
        # (возврат к hi для SHORT / к lo для LONG). Это «дыхание»: пауза на
        # росте к hi, работа на откате. Time-cooldown душил повторный freeze
        # на затяжном тренде, оставляя бота незащищённым.
        if PUMP_COOLDOWN_MIN > 0:
            last_resume = last_resume_ts(bot_id)
            if last_resume is not None:
                elapsed_min = (now - last_resume).total_seconds() / 60.0
                if elapsed_min < PUMP_COOLDOWN_MIN:
                    continue

        ri = last_resume_info(bot_id)
        if ri is not None:
            resume_price = float(ri.get("resume_price", 0) or 0)
            if resume_price > 0:
                if side == "short":
                    back_pct = (current_price - resume_price) / resume_price * 100.0
                else:
                    back_pct = (resume_price - current_price) / resume_price * 100.0
                # цена ещё не вернулась к extreme-стороне — не re-freeze
                if back_pct < REFREEZE_RETURN_PCT:
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
