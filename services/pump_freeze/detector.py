"""Pure pump detection — no I/O, testable.

Detect one-way pump: BTC ≥ PUMP_THRESHOLD_PCT за PUMP_WINDOW_MIN with no
pullback ≥ MIN_PULLBACK_PCT during the climb.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from services.pump_freeze.config import (
    MIN_PULLBACK_PCT,
    PUMP_THRESHOLD_PCT,
    PUMP_WINDOW_MIN,
)


@dataclass
class PumpEvent:
    detected_at: datetime
    move_pct: float           # actual price move % over window
    price_window_start: float
    price_now: float
    max_pullback_pct: float   # observed pullback during climb


def detect(bars: list[tuple[datetime, float, float, float]],
           *, threshold_pct: float = PUMP_THRESHOLD_PCT,
           window_min: int = PUMP_WINDOW_MIN,
           max_pullback_pct: float = MIN_PULLBACK_PCT,
           ) -> Optional[PumpEvent]:
    """Detect pump on tail of bars.

    bars: list of (ts, high, low, close) sorted ascending. Need at least
          window_min bars в хвосте.
    Returns PumpEvent if last bar's close vs (-window_min) close shows
            ≥threshold_pct one-way move (no -max_pullback_pct retracement).
    """
    if len(bars) < window_min + 1:
        return None
    tail = bars[-(window_min + 1):]  # last N+1 bars
    start_ts, _, _, start_close = tail[0]
    last_ts, _, _, last_close = tail[-1]
    if start_close <= 0:
        return None
    move_pct = (last_close - start_close) / start_close * 100.0
    if move_pct < threshold_pct:
        return None

    # During the window, check pullback from start
    min_low = min(b[2] for b in tail)
    pullback = (start_close - min_low) / start_close * 100.0
    if pullback >= max_pullback_pct:
        return None  # not one-way

    return PumpEvent(
        detected_at=last_ts,
        move_pct=round(move_pct, 3),
        price_window_start=round(start_close, 2),
        price_now=round(last_close, 2),
        max_pullback_pct=round(pullback, 3),
    )


def should_resume(*, freeze_peak_price: float, current_price: float,
                   freeze_ts: datetime, now: datetime,
                   retrace_pct: float, timeout_hours: float) -> tuple[bool, str]:
    """Decide if frozen state can be lifted.

    Returns (True, reason) if resume conditions met, else (False, "").
    """
    # Timeout?
    elapsed_h = (now - freeze_ts).total_seconds() / 3600.0
    if elapsed_h >= timeout_hours:
        return True, f"timeout {elapsed_h:.1f}h ≥ {timeout_hours}h"
    # Retracement?
    if freeze_peak_price > 0:
        retrace = (freeze_peak_price - current_price) / freeze_peak_price * 100.0
        if retrace >= retrace_pct:
            return True, f"retracement -{retrace:.2f}% ≥ {retrace_pct}%"
    return False, ""
