"""Price% indicator with 'Разовая проверка' (single-check per cycle) semantics."""
from __future__ import annotations

from collections import deque

from .contracts import Side


class PricePercentIndicator:
    """
    Price% close-to-close over `period` 1-minute bars.
    For SHORT: fires when Price% > +threshold_pct (price moved up → short opportunity).
    For LONG:  fires when Price% < -threshold_pct (price moved down → long opportunity).
    """

    def __init__(self, period: int, threshold_pct: float, side: Side) -> None:
        self.period = period
        self.threshold_pct = threshold_pct
        self.side = side
        self._closes: deque[float] = deque(maxlen=period)

    def push(self, close: float) -> None:
        self._closes.append(close)

    def value(self) -> float | None:
        """Returns current Price% or None if not enough bars."""
        if len(self._closes) < self.period:
            return None
        first = self._closes[0]
        if first == 0.0:
            return None
        return (self._closes[-1] - first) / first * 100.0

    def is_triggered(self) -> bool:
        v = self.value()
        if v is None:
            return False
        if self.side == Side.SHORT:
            return v > self.threshold_pct
        return v < -self.threshold_pct
