"""OutStopGroup — combines triggered IN-orders into a single trailing stop."""
from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import ContractModel, Side
from .order import InOrder, OrderState


@dataclass
class OutStopGroup:
    side: Side
    contract: ContractModel
    max_stop_pct: float

    orders: list[InOrder] = field(default_factory=list)
    combo_stop_price: float = 0.0  # trailing stop: extreme × (1 ± max_stop_pct%)
    extreme_price: float = 0.0    # best price reached (profit direction)
    base_stop: float = 0.0        # SHORT: max(stop_prices); LONG: min(stop_prices)

    # ------------------------------------------------------------------ construction

    @classmethod
    def from_triggered(
        cls,
        orders: list[InOrder],
        current_price: float,
        contract: ContractModel,
    ) -> "OutStopGroup":
        """Create group from one or more TRIGGERED orders.

        combo_stop_price = extreme × (1 ± max_stop_pct%) — trailing component.
        base_stop = max/min of individual stop_prices — floor/ceiling from order geometry.
        When max_stop_pct == 0: both set to trigger_price (fires on first touch, §3 GINAREA_MECHANICS).
        """
        assert orders, "at least one order required"
        side = orders[0].side
        max_stop_pct = orders[0].max_stop_pct

        if side == Side.SHORT:
            extreme = min(min(o.trigger_price for o in orders), current_price)
            if max_stop_pct == 0.0:
                init_stop = min(o.trigger_price for o in orders)
                init_base = init_stop
            else:
                raw_stop = extreme * (1.0 + max_stop_pct / 100.0)
                entry_cap = min(o.entry_price for o in orders)
                init_stop = min(raw_stop, entry_cap)
                init_base = max(o.stop_price for o in orders)
        else:
            extreme = max(max(o.trigger_price for o in orders), current_price)
            if max_stop_pct == 0.0:
                init_stop = max(o.trigger_price for o in orders)
                init_base = init_stop
            else:
                raw_stop = extreme * (1.0 - max_stop_pct / 100.0)
                entry_floor = max(o.entry_price for o in orders)
                init_stop = max(raw_stop, entry_floor)
                init_base = min(o.stop_price for o in orders)

        group = cls(
            side=side,
            contract=contract,
            max_stop_pct=max_stop_pct,
            combo_stop_price=init_stop,
            extreme_price=extreme,
            base_stop=init_base,
        )
        for o in orders:
            o.join_group()
        group.orders = list(orders)
        return group

    @classmethod
    def from_two_triggered(
        cls,
        order_a: InOrder,
        order_b: InOrder,
        current_price: float,
        contract: ContractModel,
    ) -> "OutStopGroup":
        """Deprecated: use from_triggered([a, b], ...) instead."""
        return cls.from_triggered([order_a, order_b], current_price, contract)

    def add_order(self, order: InOrder) -> None:
        """Merge a newly-triggered order into this group.

        Updates base_stop and extreme_price; combo_stop_price is NOT touched here —
        it is purely a function of extreme_price and is updated by update_trailing().
        """
        assert order.state == OrderState.TRIGGERED
        order.join_group()
        self.orders.append(order)

        if self.side == Side.SHORT:
            # base_stop: for max_stop_pct=0 track min trigger; otherwise track max stop_price
            if self.max_stop_pct == 0.0:
                if order.trigger_price < self.base_stop:
                    self.base_stop = order.trigger_price
            else:
                if order.stop_price > self.base_stop:
                    self.base_stop = order.stop_price
            # Extreme only improves (lower = better for SHORT)
            if order.trigger_price < self.extreme_price:
                self.extreme_price = order.trigger_price
        else:
            if self.max_stop_pct == 0.0:
                if order.trigger_price > self.base_stop:
                    self.base_stop = order.trigger_price
            else:
                if order.stop_price < self.base_stop:
                    self.base_stop = order.stop_price
            if order.trigger_price > self.extreme_price:
                self.extreme_price = order.trigger_price

    # ------------------------------------------------------------------ per-price-point update

    def update_trailing(self, price: float) -> None:
        """Update extreme_price and trail combo_stop_price by max_stop_pct.

        Called for each intrabar price point. combo_stop only moves in profit direction.
        """
        if self.max_stop_pct == 0.0:
            return

        if self.side == Side.SHORT:
            # Profit direction is DOWN; extreme = lowest price seen
            if price < self.extreme_price:
                self.extreme_price = price
                new_stop = self.extreme_price * (1.0 + self.max_stop_pct / 100.0)
                if new_stop < self.combo_stop_price:
                    self.combo_stop_price = new_stop
        else:
            # Profit direction is UP; extreme = highest price seen
            if price > self.extreme_price:
                self.extreme_price = price
                new_stop = self.extreme_price * (1.0 - self.max_stop_pct / 100.0)
                if new_stop > self.combo_stop_price:
                    self.combo_stop_price = new_stop

    def should_close(self, price: float) -> bool:
        """True if price crossed the effective stop.

        effective_stop = max(combo_stop, base_stop) for SHORT  — whichever is harder to hit.
        effective_stop = min(combo_stop, base_stop) for LONG.
        """
        if self.side == Side.SHORT:
            return price >= max(self.combo_stop_price, self.base_stop)
        return price <= min(self.combo_stop_price, self.base_stop)

    # ------------------------------------------------------------------ close

    def close_all(self, close_price: float, bar_idx: int) -> float:
        """Close all orders in group at close_price.

        Returns total realized PnL in pnl_currency.
        """
        total_pnl = 0.0
        for order in self.orders:
            pnl = self.contract.unrealized_pnl(
                self.side, order.qty, order.entry_price, close_price
            )
            order.close(close_price, pnl, bar_idx)
            total_pnl += pnl
        return total_pnl
