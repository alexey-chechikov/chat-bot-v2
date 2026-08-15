"""Instop Semantics A: grid accumulation with delayed entry.

Three scenarios (SHORT bot, same logic mirrored for LONG):
  A1 — price rises with pullbacks: each level waits for instop_pct reversal, opens one IN.
  A2 — first IN after indicator pass: waits for instop_pct move FROM extremum.
  A3 — price runs through N levels without reversal: one combined IN for all N levels.

When instop_pct == 0: no waiting, open immediately at grid level crossing.
"""
from __future__ import annotations

import math

from .contracts import Side


class InstopTracker:
    """Tracks local extremum and pending grid count for one bot."""

    def __init__(self, side: Side, instop_pct: float, grid_step_pct: float) -> None:
        self.side = side
        self.instop_pct = instop_pct
        self.grid_step_pct = grid_step_pct

        self.local_extremum: float | None = None
        self.pending_levels: int = 0
        # A2 phase: False = track adverse extremum, fire on reversal back toward grid.
        # True  = price crossed a grid level (A1/A3), track continuation extremum, fire on pullback.
        self._above_base: bool = False

    # ------------------------------------------------------------------ state reset

    def reset(self, price: float) -> None:
        """Call after opening an IN (instop fired or immediate open)."""
        self.local_extremum = price
        self.pending_levels = 0
        self._above_base = False

    def init_extremum(self, price: float) -> None:
        """Called when indicator passes — set starting extremum, no pending levels."""
        self.local_extremum = price
        self.pending_levels = 0
        self._above_base = False

    # ------------------------------------------------------------------ per-price-point update

    def update_extremum(self, price: float) -> None:
        """Update local extremum with current price point."""
        if self.local_extremum is None:
            self.local_extremum = price
            return
        if self.side == Side.SHORT:
            if self._above_base:
                # A1/A3: track MAX — fire when price pulls back from it
                if price > self.local_extremum:
                    self.local_extremum = price
            else:
                # A2: track MIN — fire when price bounces back up from it
                if price < self.local_extremum:
                    self.local_extremum = price
        else:
            if self._above_base:
                # LONG A1/A3: track MIN
                if price < self.local_extremum:
                    self.local_extremum = price
            else:
                # LONG A2: track MAX
                if price > self.local_extremum:
                    self.local_extremum = price

    def count_new_levels(self, price: float, last_in_price: float) -> int:
        """
        How many NEW grid levels (above pending_levels) has price crossed since last_in_price?
        Each level: last_in_price × (1 + gs%)^(pending + k) for k = 1, 2, ...
        """
        if last_in_price <= 0:
            return 0
        step = self.grid_step_pct / 100.0
        if self.side == Side.SHORT:
            # Levels go UP for SHORT
            new = 0
            k = self.pending_levels + 1
            while True:
                lvl = last_in_price * ((1.0 + step) ** k)
                if price >= lvl:
                    new += 1
                    k += 1
                else:
                    break
            return new
        else:
            # Levels go DOWN for LONG
            new = 0
            k = self.pending_levels + 1
            while True:
                lvl = last_in_price * ((1.0 - step) ** k)
                if price <= lvl:
                    new += 1
                    k += 1
                else:
                    break
            return new

    def next_grid_level(self, last_in_price: float) -> float:
        """Price level for the NEXT (pending_levels+1)-th grid step from last_in_price."""
        step = self.grid_step_pct / 100.0
        k = self.pending_levels + 1
        if self.side == Side.SHORT:
            return last_in_price * ((1.0 + step) ** k)
        return last_in_price * ((1.0 - step) ** k)

    # ------------------------------------------------------------------ fire check

    def should_fire(self, price: float) -> bool:
        """
        Instop fires when price reverses from local_extremum by instop_pct
        AND there are pending levels waiting.
        """
        if self.instop_pct == 0.0:
            return False
        if self.local_extremum is None or self.pending_levels == 0:
            return False
        if self.side == Side.SHORT:
            if self._above_base:
                # A1/A3: pullback DOWN from MAX
                return (
                    (self.local_extremum - price) / self.local_extremum * 100.0
                    >= self.instop_pct
                )
            else:
                # A2: bounce UP from MIN
                return (
                    (price - self.local_extremum) / self.local_extremum * 100.0
                    >= self.instop_pct
                )
        else:
            if self._above_base:
                # LONG A1/A3: bounce UP from MIN
                return (
                    (price - self.local_extremum) / self.local_extremum * 100.0
                    >= self.instop_pct
                )
            else:
                # LONG A2: pullback DOWN from MAX
                return (
                    (self.local_extremum - price) / self.local_extremum * 100.0
                    >= self.instop_pct
                )
