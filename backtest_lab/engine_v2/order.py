"""Per-order state for GinArea IN-orders."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .contracts import Side


class OrderState(Enum):
    PENDING_INSTOP = "pending_instop"  # waiting for instop reversal
    ACTIVE = "active"                  # open, waiting for target
    TRIGGERED = "triggered"            # target hit, stop placed
    IN_GROUP = "in_group"              # merged into OutStopGroup
    CLOSED = "closed"


@dataclass
class InOrder:
    order_id: int
    side: Side
    grid_level_price: float   # the price level that created this order
    qty: float                # BTC (linear) or USD contracts (inverse)
    target_profit_pct: float
    min_stop_pct: float
    max_stop_pct: float
    state: OrderState

    # Set on activation
    entry_price: float = 0.0
    opened_bar_idx: int = 0
    is_combined: bool = False
    combined_count: int = 1

    # Set when target is triggered
    trigger_price: float = 0.0
    stop_price: float = 0.0

    # Set on close
    closed_at_price: float = 0.0
    closed_pnl: float = 0.0
    closed_bar_idx: int = 0

    # ------------------------------------------------------------------ lifecycle

    def activate(
        self,
        entry_price: float,
        bar_idx: int,
        combined_count: int = 1,
    ) -> None:
        assert self.state == OrderState.PENDING_INSTOP, self.state
        self.entry_price = entry_price
        self.state = OrderState.ACTIVE
        self.opened_bar_idx = bar_idx
        self.combined_count = combined_count
        self.is_combined = combined_count > 1
        if self.side == Side.SHORT:
            self.trigger_price = entry_price * (1.0 - self.target_profit_pct / 100.0)
        else:
            self.trigger_price = entry_price * (1.0 + self.target_profit_pct / 100.0)

    def set_triggered(self) -> None:
        assert self.state == OrderState.ACTIVE, self.state
        self.state = OrderState.TRIGGERED
        if self.side == Side.SHORT:
            # stop placed ABOVE trigger (price must bounce up for min_stop)
            self.stop_price = self.trigger_price * (1.0 + self.min_stop_pct / 100.0)
        else:
            self.stop_price = self.trigger_price * (1.0 - self.min_stop_pct / 100.0)

    def join_group(self) -> None:
        assert self.state == OrderState.TRIGGERED, self.state
        self.state = OrderState.IN_GROUP

    def close(self, price: float, pnl: float, bar_idx: int) -> None:
        assert self.state in (
            OrderState.TRIGGERED,
            OrderState.IN_GROUP,
        ), self.state
        self.state = OrderState.CLOSED
        self.closed_at_price = price
        self.closed_pnl = pnl
        self.closed_bar_idx = bar_idx
