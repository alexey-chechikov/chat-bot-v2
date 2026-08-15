"""TZ-H1 policy interface and concrete policies (v1 + v2)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from enum import Enum

from .bot import GinareaBot, OHLCBar
from .contracts import Side
from .regime_detector import Regime


class ActionType(Enum):
    STOP_BOT = "stop_bot"
    RESUME_BOT = "resume_bot"
    RAISE_BORDER_TOP = "raise_border_top"
    LOWER_BORDER_BOTTOM = "lower_border_bottom"  # v2: lower boundaries_lower for LONG


@dataclass
class Action:
    type: ActionType
    value: float = 0.0  # new boundary value for RAISE_BORDER_TOP / LOWER_BORDER_BOTTOM


class Policy(ABC):
    def pre_bar(self, bar: OHLCBar, bar_idx: int) -> None:
        """Called once per bar before per-bot on_bar calls. Override for stateful policies."""

    @abstractmethod
    def on_bar(
        self,
        bot: GinareaBot,
        regime: Regime,
        bar: OHLCBar,
        local_high: float,
        local_low: float = 0.0,
    ) -> list[Action]: ...


# ------------------------------------------------------------------ v1 policies (unchanged)

class PassivePolicy(Policy):
    """Do nothing. Bot runs as-is. Baseline."""

    def on_bar(self, bot, regime, bar, local_high, local_low=0.0) -> list[Action]:
        return []


class StopOnStrongUpPolicy(Policy):
    """v1: SHORT-only stop on STRONG_UP/CRITICAL_UP. Kept for backwards compat."""

    def on_bar(self, bot, regime, bar, local_high, local_low=0.0) -> list[Action]:
        is_strong = regime in (Regime.STRONG_UP, Regime.CRITICAL_UP)
        if is_strong and bot.is_active:
            return [Action(ActionType.STOP_BOT)]
        if not is_strong and not bot.is_active:
            return [Action(ActionType.RESUME_BOT)]
        return []


class RaiseTopOnStrongUpPolicy(Policy):
    """v1: raise boundaries_upper on STRONG_UP. Kept for backwards compat."""

    def __init__(self, raise_top_offset_pct: float = 0.3) -> None:
        self.raise_top_offset_pct = raise_top_offset_pct

    def on_bar(self, bot, regime, bar, local_high, local_low=0.0) -> list[Action]:
        if regime not in (Regime.STRONG_UP, Regime.CRITICAL_UP):
            return []
        if local_high <= 0.0:
            return []
        new_top = local_high * (1.0 + self.raise_top_offset_pct / 100.0)
        if new_top > bot.cfg.boundaries_upper:
            return [Action(ActionType.RAISE_BORDER_TOP, new_top)]
        return []


# ------------------------------------------------------------------ v2 policies

class StopOnExtremePolicy(Policy):
    """
    SHORT: STOP on STRONG_UP/CRITICAL_UP, RESUME on return to NORMAL/DOWN.
    LONG:  STOP on STRONG_DOWN/CRITICAL_DOWN, RESUME on return to NORMAL/UP.
    """

    def on_bar(self, bot, regime, bar, local_high, local_low=0.0) -> list[Action]:
        if bot.cfg.side == Side.SHORT:
            is_extreme = regime in (Regime.STRONG_UP, Regime.CRITICAL_UP)
        else:
            is_extreme = regime in (Regime.STRONG_DOWN, Regime.CRITICAL_DOWN)

        if is_extreme and bot.is_active:
            return [Action(ActionType.STOP_BOT)]
        if not is_extreme and not bot.is_active:
            return [Action(ActionType.RESUME_BOT)]
        return []


class RaiseBoundaryPolicy(Policy):
    """
    SHORT: raise boundaries_upper at every new local_high during STRONG_UP/CRITICAL_UP.
    LONG:  lower boundaries_lower at every new local_low during STRONG_DOWN/CRITICAL_DOWN.
    Boundary stays at raised/lowered level after regime returns to NORMAL.
    """

    def __init__(self, offset_pct: float = 0.3) -> None:
        self.offset_pct = offset_pct

    def on_bar(self, bot, regime, bar, local_high, local_low=0.0) -> list[Action]:
        if bot.cfg.side == Side.SHORT:
            if regime not in (Regime.STRONG_UP, Regime.CRITICAL_UP) or local_high <= 0.0:
                return []
            new_top = local_high * (1.0 + self.offset_pct / 100.0)
            if new_top > bot.cfg.boundaries_upper:
                return [Action(ActionType.RAISE_BORDER_TOP, new_top)]
        else:
            if regime not in (Regime.STRONG_DOWN, Regime.CRITICAL_DOWN) or local_low <= 0.0:
                return []
            new_bottom = local_low * (1.0 - self.offset_pct / 100.0)
            if new_bottom < bot.cfg.boundaries_lower:
                return [Action(ActionType.LOWER_BORDER_BOTTOM, new_bottom)]
        return []


class ControlledRaisePolicy(Policy):
    """
    Fires only on confirmed trend: (Δ1h > 3%) OR (Δ4h > 4.5%).
    SHORT: RAISE_BORDER_TOP = bar.high × (1 + offset).
    LONG:  LOWER_BORDER_BOTTOM = bar.low × (1 − offset).
    Cooldown: 60 bars between fires per bot.
    """

    def __init__(self, offset_pct: float = 0.5, cooldown_minutes: int = 60) -> None:
        self.offset_pct = offset_pct
        self.cooldown = cooldown_minutes
        self._closes: deque[float] = deque(maxlen=241)
        self._bar_count: int = 0
        self._last_fire: dict[str, int] = {}  # bot_id -> _bar_count at last fire

    def pre_bar(self, bar: OHLCBar, bar_idx: int) -> None:
        self._bar_count += 1
        self._closes.append(bar.close)

    def _delta(self, lookback: int) -> float | None:
        if len(self._closes) <= lookback:
            return None
        prev = self._closes[-(lookback + 1)]
        if prev == 0.0:
            return None
        return (self._closes[-1] - prev) / prev * 100.0

    def on_bar(self, bot, regime, bar, local_high, local_low=0.0) -> list[Action]:
        last = self._last_fire.get(bot.cfg.bot_id, -(self.cooldown + 1))
        if self._bar_count - last < self.cooldown:
            return []

        d1h = self._delta(60)
        d4h = self._delta(240)

        if bot.cfg.side == Side.SHORT:
            triggered = (d1h is not None and d1h > 3.0) or (d4h is not None and d4h > 4.5)
            if not triggered:
                return []
            new_top = bar.high * (1.0 + self.offset_pct / 100.0)
            if new_top > bot.cfg.boundaries_upper:
                self._last_fire[bot.cfg.bot_id] = self._bar_count
                return [Action(ActionType.RAISE_BORDER_TOP, new_top)]
        else:
            triggered = (d1h is not None and d1h < -3.0) or (d4h is not None and d4h < -4.5)
            if not triggered:
                return []
            new_bottom = bar.low * (1.0 - self.offset_pct / 100.0)
            if new_bottom < bot.cfg.boundaries_lower:
                self._last_fire[bot.cfg.bot_id] = self._bar_count
                return [Action(ActionType.LOWER_BORDER_BOTTOM, new_bottom)]
        return []
