"""Bidirectional one-way move detector.

direction='up'   → pump events (для SHORT botов: цена ушла вверх, шорт страдает)
direction='down' → dump events (для LONG botов: цена ушла вниз, лонг страдает)
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
class MoveEvent:
    detected_at: datetime
    direction: str            # "up" | "down"
    move_pct: float           # signed % move over window (negative for down)
    price_window_start: float
    price_now: float
    max_opposite_retracement_pct: float


def detect_move(bars: list[tuple[datetime, float, float, float]],
                *, direction: str,
                threshold_pct: float = PUMP_THRESHOLD_PCT,
                window_min: int = PUMP_WINDOW_MIN,
                max_retrace_pct: float = MIN_PULLBACK_PCT,
                ) -> Optional[MoveEvent]:
    """Generic one-way move detector.

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
        # max opposite retracement = max DOWN deviation from start during climb
        min_low = min(b[2] for b in tail)
        retrace = (start_close - min_low) / start_close * 100.0
    else:  # down
        if move_pct > -threshold_pct:
            return None
        # max opposite retracement = max UP deviation from start during dump
        max_high = max(b[1] for b in tail)
        retrace = (max_high - start_close) / start_close * 100.0

    if retrace >= max_retrace_pct:
        return None

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
                   timeout_hours: float) -> tuple[bool, str]:
    """Resume when retracement OR timeout.

    side='short' (frozen on pump): wait for price to retrace DOWN.
    side='long'  (frozen on dump): wait for price to retrace UP.
    """
    elapsed_h = (now - freeze_ts).total_seconds() / 3600.0
    if elapsed_h >= timeout_hours:
        return True, f"timeout {elapsed_h:.1f}h ≥ {timeout_hours}h"
    if freeze_extreme_price <= 0:
        return False, ""
    if side == "short":
        retrace = (freeze_extreme_price - current_price) / freeze_extreme_price * 100.0
    else:
        retrace = (current_price - freeze_extreme_price) / freeze_extreme_price * 100.0
    if retrace >= retrace_pct:
        return True, f"retracement {retrace:+.2f}% ≥ {retrace_pct}%"
    return False, ""


# Backwards-compat wrappers for tests/legacy code
def detect(bars, **kw):
    """Deprecated; default to up-direction (SHORT). Use detect_move()."""
    return detect_move(bars, direction="up", **kw)
