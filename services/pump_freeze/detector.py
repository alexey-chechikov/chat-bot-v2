"""Bidirectional one-way move detector.

direction='up'   → pump events (для SHORT botов: цена ушла вверх, шорт страдает)
direction='down' → dump events (для LONG botов: цена ушла вниз, лонг страдает)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from services.pump_freeze.config import (
    PUMP_THRESHOLD_PCT,
    PUMP_WINDOW_MIN,
)


@dataclass
class MoveEvent:
    detected_at: datetime
    direction: str            # "up" | "down"
    move_pct: float           # signed % move over window (negative for down)
    price_window_start: float
    price_now: float
    max_opposite_retracement_pct: float  # informational, no longer filter


def detect_move(bars: list[tuple[datetime, float, float, float]],
                *, direction: str,
                threshold_pct: float = PUMP_THRESHOLD_PCT,
                window_min: int = PUMP_WINDOW_MIN,
                ) -> Optional[MoveEvent]:
    """Generic move detector — fires on ANY ≥threshold_pct move regardless
    of intermediate retracement (whipsaw events тоже включаются — оператор
    хочет паузить и их per Win-колеги verification 2026-05-18).

    bars: [(ts, high, low, close)] sorted ascending. Need ≥window_min+1.
    direction: 'up' (pump) или 'down' (dump).
    """
    if len(bars) < window_min + 1:
        return None
    if direction not in ("up", "down"):
        return None

    tail = bars[-(window_min + 1):]
    _, _, _, start_close = tail[0]
    last_ts, _, _, last_close = tail[-1]
    if start_close <= 0:
        return None

    move_pct = (last_close - start_close) / start_close * 100.0

    if direction == "up":
        if move_pct < threshold_pct:
            return None
        min_low = min(b[2] for b in tail)
        retrace = (start_close - min_low) / start_close * 100.0
    else:
        if move_pct > -threshold_pct:
            return None
        max_high = max(b[1] for b in tail)
        retrace = (max_high - start_close) / start_close * 100.0

    return MoveEvent(
        detected_at=last_ts, direction=direction,
        move_pct=round(move_pct, 3),
        price_window_start=round(start_close, 2),
        price_now=round(last_close, 2),
        max_opposite_retracement_pct=round(retrace, 3),
    )


def should_resume(*, freeze_extreme_price: float, current_price: float,
                   freeze_ts: datetime, now: datetime,
                   side: str, retrace_pct: float,
                   timeout_hours: float,
                   last_extreme_ts: Optional[datetime] = None,
                   stall_min: Optional[float] = None) -> tuple[bool, str]:
    """Resume when ANY of: retracement / stall / timeout.

    side='short' (frozen on pump): wait for price to retrace DOWN.
    side='long'  (frozen on dump): wait for price to retrace UP.

    Resume conditions, checked in order of preference:
      1. retracement — price pulled back >= retrace_pct from the extreme
         (the move reversed).
      2. stall       — no new extreme for >= stall_min minutes (the move
         died into a range under the hi; bot should work the range instead
         of standing idle). Needs last_extreme_ts + stall_min.
      3. timeout     — far safety net only.
    """
    # 1. retracement
    if freeze_extreme_price > 0:
        if side == "short":
            retrace = (freeze_extreme_price - current_price) / freeze_extreme_price * 100.0
        else:
            retrace = (current_price - freeze_extreme_price) / freeze_extreme_price * 100.0
        if retrace >= retrace_pct:
            return True, f"retracement {retrace:+.2f}% ≥ {retrace_pct}%"

    # 2. stall — no new extreme for stall_min minutes
    if stall_min is not None and last_extreme_ts is not None:
        idle_min = (now - last_extreme_ts).total_seconds() / 60.0
        if idle_min >= stall_min:
            return True, f"stall {idle_min:.0f}min ≥ {stall_min}min (no new extreme)"

    # 3. timeout — far safety net
    elapsed_h = (now - freeze_ts).total_seconds() / 3600.0
    if elapsed_h >= timeout_hours:
        return True, f"timeout {elapsed_h:.1f}h ≥ {timeout_hours}h"

    return False, ""


# Backwards-compat wrappers for tests/legacy code
def detect(bars, **kw):
    """Deprecated; default to up-direction (SHORT). Use detect_move()."""
    return detect_move(bars, direction="up", **kw)
