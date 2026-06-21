"""B5 Mega-setup detector — confluence of long_dump_reversal + long_pdl_bounce.

Discovered via tools/_setup_correlation_matrix.py (Stage C2):
  Pair: long_dump_reversal × long_pdl_bounce
  N co-fires (60min bucket): 425
  WR(co-fire): 42.8%   vs   WR(alone): 35.9% / 37.1%
  Boost: +5.7 pp WR over the better leg alone

This detector fires LONG_MEGA_DUMP_BOUNCE only when BOTH constituent setups
have been emitted in the last MEGA_WINDOW_MIN minutes for the same pair.
Reads recent setups from `state/setups.jsonl` and matches by detected_at.

The signal is high-conviction (strength=10, confidence=85) and uses tighter
SL than either constituent for tighter R:R with the boosted WR.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.setup_detector.models import Setup, SetupBasis, SetupType, make_setup

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
SETUPS_PATH = ROOT / "state" / "setups.jsonl"

# 2026-05-10 LOCK: do NOT adaptive-tune these. Walk-forward validation
# (tools/_mega_adaptive_retune.py) showed FIXED +24.40% vs ADAPTIVE +3.83%
# (-84.3%) over 815d. Fixed params are stable across regimes; adaptive
# overfits to recent window and degrades next fold. Rationale in commit
# history under "mega adaptive REJECTED".
MEGA_WINDOW_MIN = 60   # both constituents must fire within this window
MEGA_DEDUP_HOURS = 4   # don't fire mega twice in 4h on the same pair
MEGA_SL_PCT = 0.8      # tighter than dump_reversal/pdl_bounce defaults
MEGA_TP1_RR = 2.5
MEGA_TP2_RR = 5.0

CONSTITUENT_TYPES = {"long_dump_reversal", "long_pdl_bounce"}


def _read_recent_setups(window_min: int, pair: str | None = None) -> list[dict]:
    """Read setups.jsonl entries with detected_at within last `window_min`
    minutes. Optionally filter by pair."""
    if not SETUPS_PATH.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_min)
    out: list[dict] = []
    # 2026-05-10 fix: open as binary then decode per-line, otherwise text-mode
    # f.seek() into middle of multi-byte UTF-8 sequence raises UnicodeDecodeError
    # (observed in app.log: 'utf-8' codec can't decode byte 0xb6).
    try:
        with SETUPS_PATH.open("rb") as f:
            try:
                f.seek(0, 2)  # SEEK_END
                size = f.tell()
                seek_to = max(0, size - 256_000)
                f.seek(seek_to)
                if seek_to > 0:
                    f.readline()  # discard possibly-partial line in bytes
                raw_lines = f.readlines()
            except OSError:
                raw_lines = []
        lines = []
        for rb in raw_lines:
            try:
                lines.append(rb.decode("utf-8"))
            except UnicodeDecodeError:
                continue  # skip corrupt line
        for raw in lines:
            try:
                rec = json.loads(raw)
            except (ValueError, TypeError):
                continue
            ts_str = rec.get("detected_at") or ""
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except ValueError:
                continue
            if ts < cutoff:
                continue
            if pair and str(rec.get("pair") or "").upper() != pair.upper():
                continue
            out.append(rec)
    except OSError:
        logger.exception("mega_setup.read_failed")
    return out


def _last_mega_fire_ts(pair: str) -> datetime | None:
    """Find timestamp of the most recent LONG_MEGA_DUMP_BOUNCE for this pair
    in setups.jsonl. Returns None if no prior fire."""
    setups = _read_recent_setups(MEGA_DEDUP_HOURS * 60, pair=pair)
    last: datetime | None = None
    for rec in setups:
        if str(rec.get("setup_type") or "") != SetupType.LONG_MEGA_DUMP_BOUNCE.value:
            continue
        ts_str = rec.get("detected_at") or ""
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except ValueError:
            continue
        if last is None or ts > last:
            last = ts
    return last


def detect_long_mega_dump_bounce(ctx) -> Setup | None:
    """Fire LONG_MEGA when both long_dump_reversal AND long_pdl_bounce have
    emitted for the same pair within MEGA_WINDOW_MIN minutes, and we haven't
    already fired a mega for this pair in the last MEGA_DEDUP_HOURS."""
    pair = str(getattr(ctx, "pair", "")).upper()
    if not pair:
        return None

    recent = _read_recent_setups(MEGA_WINDOW_MIN, pair=pair)
    if not recent:
        return None

    types_fired = {str(rec.get("setup_type") or "") for rec in recent}
    if not CONSTITUENT_TYPES.issubset(types_fired):
        return None

    # Dedup against own previous fires.
    last_mega = _last_mega_fire_ts(pair)
    if last_mega is not None:
        delta = datetime.now(timezone.utc) - last_mega
        if delta.total_seconds() < MEGA_DEDUP_HOURS * 3600:
            return None

    # Reference prices from the most recent constituent of each type.
    by_type: dict[str, dict] = {}
    for rec in sorted(recent, key=lambda r: r.get("detected_at") or ""):
        t = str(rec.get("setup_type") or "")
        if t in CONSTITUENT_TYPES:
            by_type[t] = rec  # last wins

    dump_rec = by_type.get("long_dump_reversal", {})
    bounce_rec = by_type.get("long_pdl_bounce", {})

    entry = float(ctx.current_price or 0)
    if entry <= 0:
        return None
    stop = entry * (1 - MEGA_SL_PCT / 100.0)
    risk = entry - stop
    tp1 = entry + risk * MEGA_TP1_RR
    tp2 = entry + risk * MEGA_TP2_RR
    rr = (tp1 - entry) / max(risk, 1e-9)

    basis = (
        SetupBasis("dump_reversal_ts", str(dump_rec.get("detected_at", "")), 0.30),
        SetupBasis("pdl_bounce_ts", str(bounce_rec.get("detected_at", "")), 0.30),
        SetupBasis("dump_strength", int(dump_rec.get("strength", 0) or 0), 0.15),
        SetupBasis("bounce_strength", int(bounce_rec.get("strength", 0) or 0), 0.15),
        SetupBasis("window_min", MEGA_WINDOW_MIN, 0.10),
        SetupBasis("backtest_boost_pp", 5.7, 0.0),  # historical edge from C2
        SetupBasis("backtest_n_co_fire", 425, 0.0),
    )

    return make_setup(
        setup_type=SetupType.LONG_MEGA_DUMP_BOUNCE,
        pair=ctx.pair,
        current_price=entry,
        regime_label=ctx.regime_label,
        session_label=ctx.session_label,
        entry_price=entry,
        stop_price=stop,
        tp1_price=tp1,
        tp2_price=tp2,
        risk_reward=round(rr, 2),
        strength=10,        # max — both constituents agreed
        confidence_pct=85.0,
        basis=basis,
        cancel_conditions=(
            "Свежий LL ниже dump_reversal стопа — отскок отменён",
            f"Mega-сетап fired в той же паре в последние {MEGA_DEDUP_HOURS}h "
            "(используем актуальный, не старый)",
        ),
        window_minutes=240,
        portfolio_impact_note=(
            f"MEGA-setup: long_dump_reversal + long_pdl_bounce confluence. "
            f"Historical C2 boost +5.7pp WR vs single-detector firing "
            f"(N=425 co-fires). High-conviction LONG entry."
        ),
        recommended_size_btc=0.05,
    )
