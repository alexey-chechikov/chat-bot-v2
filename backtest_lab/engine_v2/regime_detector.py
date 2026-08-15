"""Regime detection for TZ-H1: classifies BTC market state per minute bar."""
from __future__ import annotations

from enum import Enum

from .bot import OHLCBar


class Regime(Enum):
    NORMAL = "normal"
    STRONG_UP = "strong_up"
    CRITICAL_UP = "critical_up"
    STRONG_DOWN = "strong_down"
    CRITICAL_DOWN = "critical_down"


class RegimeDetector:
    """
    Classifies market regime at each 1-minute bar using:
    1. 1-hour return vs thresholds (60-bar lookback).
    2. N consecutive complete hourly candles all green (no red).

    All parameters match TZ-H1 §3.1 defaults.
    """

    def __init__(
        self,
        threshold_1h_strong_pct: float = 2.0,
        threshold_1h_critical_pct: float = 3.0,
        no_pullback_bars: int = 3,
    ) -> None:
        self.threshold_1h_strong_pct = threshold_1h_strong_pct
        self.threshold_1h_critical_pct = threshold_1h_critical_pct
        self.no_pullback_bars = no_pullback_bars

    def classify(self, bars: list[OHLCBar], current_idx: int) -> Regime:
        if current_idx < 60:
            return Regime.NORMAL

        close_now = bars[current_idx].close
        close_60_ago = bars[current_idx - 60].close
        pct_1h = (close_now - close_60_ago) / close_60_ago * 100.0

        if pct_1h > self.threshold_1h_critical_pct:
            return Regime.CRITICAL_UP
        if pct_1h < -self.threshold_1h_critical_pct:
            return Regime.CRITICAL_DOWN
        if pct_1h > self.threshold_1h_strong_pct:
            return Regime.STRONG_UP
        if pct_1h < -self.threshold_1h_strong_pct:
            return Regime.STRONG_DOWN
        if self._has_n_consecutive_green_hours(bars, current_idx, self.no_pullback_bars):
            return Regime.STRONG_UP
        if self._has_n_consecutive_red_hours(bars, current_idx, self.no_pullback_bars):
            return Regime.STRONG_DOWN
        return Regime.NORMAL

    def _has_n_consecutive_green_hours(
        self, bars: list[OHLCBar], current_idx: int, n: int
    ) -> bool:
        """True if the last n complete hourly candles are all green (close > open).

        Hourly candle k = bars[k*60 : (k+1)*60]. Complete when end bar <= current_idx.
        Boundary is 60-bar multiples aligned to absolute bar index (per spec §3.1).
        """
        max_complete_hour = (current_idx + 1) // 60 - 1
        if max_complete_hour < n - 1:
            return False
        for k in range(max_complete_hour - n + 1, max_complete_hour + 1):
            start = k * 60
            end = (k + 1) * 60
            if start < 0 or end > len(bars):
                return False
            if bars[end - 1].close <= bars[start].open:
                return False
        return True

    def _has_n_consecutive_red_hours(
        self, bars: list[OHLCBar], current_idx: int, n: int
    ) -> bool:
        """True if the last n complete hourly candles are all red (close < open)."""
        max_complete_hour = (current_idx + 1) // 60 - 1
        if max_complete_hour < n - 1:
            return False
        for k in range(max_complete_hour - n + 1, max_complete_hour + 1):
            start = k * 60
            end = (k + 1) * 60
            if start < 0 or end > len(bars):
                return False
            if bars[end - 1].close >= bars[start].open:
                return False
        return True
