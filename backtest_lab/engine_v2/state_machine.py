"""TRADING ↔ STOP state machine — TZ-S3-N1.

Direction-aware: SHORT bots stop on BTC rally; LONG bots stop on BTC drop.
Applied externally via bot.is_active flag — no engine changes needed.
"""
from __future__ import annotations

import datetime
from collections import deque
from dataclasses import dataclass, field

from .contracts import Side


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------

@dataclass
class StopTriggerConfig:
    movement_pct: float | None  # None = always TRADING (baseline/disabled)
    window_min: int
    no_pullback_bars: int

    def label(self) -> str:
        if self.movement_pct is None:
            return "disabled"
        return f"m{self.movement_pct:.1f}_w{self.window_min}_p{self.no_pullback_bars}"


@dataclass
class ResumeTriggerConfig:
    pullback_pct: float
    stable_minutes: int

    def label(self) -> str:
        return f"pb{self.pullback_pct:.1f}_s{self.stable_minutes}"


@dataclass
class StopEvent:
    kind: str   # 'STOP_ENTERED' | 'STOP_EXITED'
    ts: str
    price: float


# ---------------------------------------------------------------------------
# Timestamp helpers  (use 'YYYY-MM-DD HH:MM' format throughout)
# ---------------------------------------------------------------------------

def _parse16(ts: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(ts[:16].replace("T", " "))


def _subtract_min(ts: str, minutes: int) -> str:
    return (_parse16(ts) - datetime.timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")


def _min_diff(ts_start: str, ts_end: str) -> float:
    return (_parse16(ts_end) - _parse16(ts_start)).total_seconds() / 60.0


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

class StopStateMachine:
    """Direction-aware TRADING ↔ STOP controller for one bot.

    Usage:
        sm = StopStateMachine(side, stop_cfg, resume_cfg)
        for bar in window_bars:
            state = sm.update(bar)   # 'TRADING' or 'STOP'
            bot.is_active = (state == "TRADING")
            bot.step(bar, bar_idx)
    """

    def __init__(
        self,
        side: Side,
        stop_cfg: StopTriggerConfig,
        resume_cfg: ResumeTriggerConfig,
    ) -> None:
        self.side = side
        self.stop_cfg = stop_cfg
        self.resume_cfg = resume_cfg
        self.state = "TRADING"

        # Rolling 1m close price history for btc_change_pct window
        self._prices: deque[tuple[str, float]] = deque()

        # Completed hourly bars (key, open, close) — max 12 kept
        self._h_bars: list[tuple[str, float, float]] = []
        # In-progress hourly bar accumulator
        self._h_key: str | None = None
        self._h_open = self._h_high = self._h_low = self._h_close = 0.0

        # STOP state tracking
        self._peak: float | None = None           # worst price during STOP for this side
        self._stable_since: str | None = None     # ts when peak was last updated

        # Stats
        self.n_stop_events: int = 0
        self.total_stop_bars: int = 0
        self.events: list[StopEvent] = []

    # ------------------------------------------------------------------ public

    def update(self, bar) -> str:
        """Process one 1m bar. Returns 'TRADING' or 'STOP'."""
        ts = bar.ts[:16]
        price = bar.close

        self._push_price(ts, price)
        self._push_hourly(bar)

        if self.stop_cfg.movement_pct is None:
            return "TRADING"   # disabled baseline — always trade

        if self.state == "TRADING":
            if self._stop_triggered(price):
                self.state = "STOP"
                self.n_stop_events += 1
                self._peak = price
                self._stable_since = ts
                self.events.append(StopEvent("STOP_ENTERED", ts, price))
        else:
            self.total_stop_bars += 1
            # Update extremum (worst price for this bot's side)
            if self.side == Side.SHORT:
                if price > (self._peak or 0.0):
                    self._peak = price
                    self._stable_since = ts
            else:
                if price < (self._peak if self._peak is not None else float("inf")):
                    self._peak = price
                    self._stable_since = ts

            if self._resume_triggered(price, ts):
                self.state = "TRADING"
                self.events.append(StopEvent("STOP_EXITED", ts, price))
                self._peak = None
                self._stable_since = None

        return self.state

    # ------------------------------------------------------------------ private

    def _push_price(self, ts: str, price: float) -> None:
        self._prices.append((ts, price))
        cutoff = _subtract_min(ts, self.stop_cfg.window_min)
        while self._prices and self._prices[0][0] < cutoff:
            self._prices.popleft()

    def _push_hourly(self, bar) -> None:
        key = bar.ts[:13]
        if self._h_key is None:
            self._h_key = key
            self._h_open = bar.open
            self._h_high = bar.high
            self._h_low = bar.low
            self._h_close = bar.close
        elif key != self._h_key:
            # Finalize completed hour (store open + close only — enough for direction)
            self._h_bars.append((self._h_key, self._h_open, self._h_close))
            if len(self._h_bars) > 12:
                self._h_bars.pop(0)
            self._h_key = key
            self._h_open = bar.open
            self._h_high = bar.high
            self._h_low = bar.low
            self._h_close = bar.close
        else:
            self._h_high = max(self._h_high, bar.high)
            self._h_low = min(self._h_low, bar.low)
            self._h_close = bar.close

    def _stop_triggered(self, price: float) -> bool:
        if len(self._prices) < 2:
            return False
        oldest = self._prices[0][1]
        chg = (price - oldest) / oldest * 100.0
        if self.side == Side.SHORT and chg < self.stop_cfg.movement_pct:
            return False
        if self.side == Side.LONG and chg > -self.stop_cfg.movement_pct:
            return False
        return self._count_trend_bars() >= self.stop_cfg.no_pullback_bars

    def _count_trend_bars(self) -> int:
        """Count consecutive completed hourly bars trending against this bot."""
        n = 0
        for (_, o, c) in reversed(self._h_bars):
            if self.side == Side.SHORT and c > o:   # bullish = bad for SHORT
                n += 1
            elif self.side == Side.LONG and c < o:  # bearish = bad for LONG
                n += 1
            else:
                break
        return n

    def _resume_triggered(self, price: float, ts: str) -> bool:
        if self._peak is None or self._stable_since is None:
            return False
        if self.side == Side.SHORT:
            pb = (self._peak - price) / self._peak * 100.0
        else:
            pb = (price - self._peak) / self._peak * 100.0
        if pb < self.resume_cfg.pullback_pct:
            return False
        return _min_diff(self._stable_since, ts) >= self.resume_cfg.stable_minutes
