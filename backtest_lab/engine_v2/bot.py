"""GinareaBot: per-bot state machine for one minute-resolution simulation step."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple

from .contracts import ContractModel, Side
from .group import OutStopGroup
from .indicator import PricePercentIndicator
from .instop import InstopTracker
from .order import InOrder, OrderState


class OHLCBar(NamedTuple):
    ts: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class BotConfig:
    bot_id: str
    alias: str
    side: Side
    contract: ContractModel
    order_size: float
    order_count: int
    grid_step_pct: float
    target_profit_pct: float
    min_stop_pct: float
    max_stop_pct: float
    instop_pct: float
    boundaries_lower: float
    boundaries_upper: float
    indicator_period: int          # e.g. 30
    indicator_threshold_pct: float # e.g. 0.3
    use_once_check: bool = True    # «Разовая проверка»
    dsblin: bool = False
    leverage: int = 100
    cap_pos_btc: float | None = None  # max abs position in BTC; None = unlimited


class GinareaBot:
    def __init__(self, config: BotConfig) -> None:
        self.cfg = config
        self._order_counter: int = 0
        self.active_orders: list[InOrder] = []  # ACTIVE + TRIGGERED
        self.closed_orders: list[InOrder] = []
        self.out_stop_group: OutStopGroup | None = None

        self.last_in_price: float | None = None
        self.is_indicator_passed: bool = False

        self.indicator = PricePercentIndicator(
            config.indicator_period,
            config.indicator_threshold_pct,
            config.side,
        )
        self.instop = InstopTracker(
            config.side,
            config.instop_pct,
            config.grid_step_pct,
        )

        # Cumulative realized PnL (in contract's pnl_currency)
        self.realized_pnl: float = 0.0
        self.in_count: int = 0
        self.out_count: int = 0
        self.n_caps_blocked: int = 0  # IN openings blocked by cap_pos_btc
        # Notional fill volume in USD (sum of |notional| for every IN and OUT fill)
        self.in_qty_notional: float = 0.0
        self.out_qty_notional: float = 0.0

        # Policy control: when False, no new grid orders open; indicator cycle not reset
        self.is_active: bool = True

    # ------------------------------------------------------------------ properties

    def position_size(self) -> float:
        """Total qty in contract's qty_unit across all open orders."""
        total = sum(o.qty for o in self.active_orders)
        if self.out_stop_group:
            total += sum(o.qty for o in self.out_stop_group.orders)
        return total

    def avg_entry(self) -> float:
        """Weighted average entry price of all open positions."""
        orders = list(self.active_orders)
        if self.out_stop_group:
            orders += self.out_stop_group.orders
        if not orders:
            return 0.0
        total_qty = sum(o.qty for o in orders)
        if total_qty == 0:
            return 0.0
        return sum(o.entry_price * o.qty for o in orders) / total_qty

    def unrealized_pnl(self, price: float) -> float:
        """Total unrealized PnL at `price` in pnl_currency."""
        orders = list(self.active_orders)
        if self.out_stop_group:
            orders += self.out_stop_group.orders
        return sum(
            self.cfg.contract.unrealized_pnl(self.cfg.side, o.qty, o.entry_price, price)
            for o in orders
        )

    def open_order_count(self) -> int:
        n = len(self.active_orders)
        if self.out_stop_group:
            n += len(self.out_stop_group.orders)
        return n

    # ------------------------------------------------------------------ main step

    def step(self, bar: OHLCBar, bar_idx: int) -> None:
        # 1. Update indicator (uses close price)
        self.indicator.push(bar.close)

        # 2. Check indicator if not yet passed
        if not self.is_indicator_passed:
            if self.indicator.is_triggered():
                self.is_indicator_passed = True
                self.instop.init_extremum(bar.close)
                if self.last_in_price is None:
                    self.last_in_price = bar.close
                    # Seed first pending level so A2 scenario fires on instop_pct reversal
                    if self.cfg.instop_pct > 0.0:
                        self.instop.pending_levels = 1
                    # Don't process this bar's OHLC — indicator fired at close,
                    # OHLC prices are stale. Start fresh from next bar.
                    return
            else:
                return  # waiting for indicator signal

        # 3. Simulate intrabar price sequence
        for price in self._bar_prices(bar):
            self._process_price(price, bar_idx, bar)

    # ------------------------------------------------------------------ intrabar

    def _bar_prices(self, bar: OHLCBar) -> list[float]:
        """OHLC simulation order: bullish = O→L→H→C, bearish = O→H→L→C."""
        if bar.close >= bar.open:
            return [bar.open, bar.low, bar.high, bar.close]
        return [bar.open, bar.high, bar.low, bar.close]

    def _process_price(self, price: float, bar_idx: int, bar: OHLCBar) -> None:
        # Update extremum for instop
        self.instop.update_extremum(price)

        # --- Check if out-stop group trailing or fires ---
        if self.out_stop_group is not None:
            self.out_stop_group.update_trailing(price)
            if self.out_stop_group.should_close(price):
                self._close_out_stop_group(price, bar_idx)

        # --- Check ACTIVE orders: trigger reached → join/create OutStopGroup ---
        for order in list(self.active_orders):
            if order.state != OrderState.ACTIVE:
                continue
            if self._trigger_hit(price, order):
                order.set_triggered()
                if self.out_stop_group is None:
                    self.out_stop_group = OutStopGroup.from_triggered(
                        [order], price, self.cfg.contract
                    )
                else:
                    self.out_stop_group.add_order(order)
                self.active_orders.remove(order)

        # --- Check instop fire or new grid opening ---
        self._try_open_new_in(price, bar_idx, bar)

    def _trigger_hit(self, price: float, order: InOrder) -> bool:
        if self.cfg.side == Side.SHORT:
            return price <= order.trigger_price
        return price >= order.trigger_price

    def _stop_hit(self, price: float, order: InOrder) -> bool:
        if self.cfg.side == Side.SHORT:
            return price >= order.stop_price
        return price <= order.stop_price

    def _handle_triggered_stop(
        self, order: InOrder, price: float, bar_idx: int
    ) -> None:
        """Individual stop hit. Check if we should form/join a group."""
        # Find other TRIGGERED orders not yet in a group
        other_triggered = [
            o for o in self.active_orders
            if o.state == OrderState.TRIGGERED and o is not order
        ]

        if other_triggered or self.out_stop_group is not None:
            # Form or join group
            if self.out_stop_group is None:
                first_other = other_triggered[0]
                self.out_stop_group = OutStopGroup.from_two_triggered(
                    order, first_other, price, self.cfg.contract
                )
                self.out_stop_group.extreme_price = price
                self.active_orders.remove(order)
                self.active_orders.remove(first_other)
                # Add remaining triggered to group
                for extra in other_triggered[1:]:
                    self.out_stop_group.add_order(extra)
                    self.active_orders.remove(extra)
            else:
                self.out_stop_group.add_order(order)
                self.active_orders.remove(order)
        else:
            # Solo close
            pnl = self.cfg.contract.unrealized_pnl(
                self.cfg.side, order.qty, order.entry_price, price
            )
            order.close(price, pnl, bar_idx)
            self.active_orders.remove(order)
            self.closed_orders.append(order)
            self.realized_pnl += pnl
            self.out_count += 1
            self.out_qty_notional += self.cfg.contract.notional_usd(order.qty, price)
            self._check_full_close()

    def _close_out_stop_group(self, price: float, bar_idx: int) -> None:
        grp = self.out_stop_group
        assert grp is not None
        pnl = grp.close_all(price, bar_idx)
        self.realized_pnl += pnl
        self.out_count += len(grp.orders)
        self.out_qty_notional += sum(
            self.cfg.contract.notional_usd(o.qty, price) for o in grp.orders
        )
        self.closed_orders.extend(grp.orders)
        self.out_stop_group = None
        self._check_full_close()

    # ------------------------------------------------------------------ grid / instop

    def _try_open_new_in(self, price: float, bar_idx: int, bar: OHLCBar) -> None:
        if not self.is_active:
            return
        if self.last_in_price is None:
            return
        if not self._within_boundaries(price):
            return
        if self.open_order_count() >= self.cfg.order_count:
            return

        if self.cfg.instop_pct == 0.0:
            # Open immediately at each grid level crossing
            self._open_immediate(price, bar_idx)
        else:
            # Check for new levels crossed, then check instop fire
            new_levels = self.instop.count_new_levels(price, self.last_in_price)
            if new_levels > 0:
                self.instop.pending_levels += new_levels
                # Transition to A1/A3 mode: track continuation extremum from here
                self.instop._above_base = True
                self.instop.local_extremum = price
            elif not self.instop._above_base and self.instop.pending_levels > 0:
                # Seeded level: count_new_levels starts from level 2 because pending is pre-seeded
                # to 1. Detect level 1 crossing manually to switch to A1 mode.
                _step = self.cfg.grid_step_pct / 100.0
                if self.cfg.side == Side.SHORT:
                    if price >= self.last_in_price * (1.0 + _step):
                        self.instop._above_base = True
                        self.instop.local_extremum = price
                else:
                    if price <= self.last_in_price * (1.0 - _step):
                        self.instop._above_base = True
                        self.instop.local_extremum = price

            if self.instop.should_fire(price):
                n = min(
                    self.instop.pending_levels,
                    self.cfg.order_count - self.open_order_count(),
                )
                if n > 0:
                    n = self._apply_cap(n)
                    if n > 0:
                        self._open_in(price, bar_idx, combined_count=n)
                    else:
                        # Cap blocked: skip this entry, reset instop from current price
                        # so next grid level is counted fresh from here
                        self.last_in_price = price
                        self.instop.reset(price)

    def _apply_cap(self, n: int) -> int:
        """Cap planned combined_count by cap_pos_btc. Returns allowed n (0 = fully blocked)."""
        if self.cfg.cap_pos_btc is None:
            return n
        current = self.position_size()
        remaining = self.cfg.cap_pos_btc - current
        n_allowed = int(remaining / self.cfg.order_size)
        if n_allowed <= 0:
            self.n_caps_blocked += 1
            return 0
        return min(n, n_allowed)

    def _open_immediate(self, price: float, bar_idx: int) -> None:
        """instop=0: open one IN per grid level crossing."""
        step = self.cfg.grid_step_pct / 100.0
        if self.cfg.side == Side.SHORT:
            next_lvl = self.last_in_price * (1.0 + step)
            while price >= next_lvl and self.open_order_count() < self.cfg.order_count:
                if not self._within_boundaries(next_lvl):
                    break
                if self._apply_cap(1) == 0:
                    # Skip level, advance base price so next level is counted from here
                    self.last_in_price = next_lvl
                    self.instop.reset(next_lvl)
                    break
                self._open_in(next_lvl, bar_idx, combined_count=1)
                next_lvl = self.last_in_price * (1.0 + step)
        else:
            next_lvl = self.last_in_price * (1.0 - step)
            while price <= next_lvl and self.open_order_count() < self.cfg.order_count:
                if not self._within_boundaries(next_lvl):
                    break
                if self._apply_cap(1) == 0:
                    self.last_in_price = next_lvl
                    self.instop.reset(next_lvl)
                    break
                self._open_in(next_lvl, bar_idx, combined_count=1)
                next_lvl = self.last_in_price * (1.0 - step)

    def _open_in(self, price: float, bar_idx: int, combined_count: int) -> None:
        """Create and immediately activate one IN order."""
        self._order_counter += 1
        qty = self.cfg.order_size * combined_count
        order = InOrder(
            order_id=self._order_counter,
            side=self.cfg.side,
            grid_level_price=price,
            qty=qty,
            target_profit_pct=self.cfg.target_profit_pct,
            min_stop_pct=self.cfg.min_stop_pct,
            max_stop_pct=self.cfg.max_stop_pct,
            state=OrderState.PENDING_INSTOP,
        )
        order.activate(price, bar_idx, combined_count)
        self.active_orders.append(order)
        self.last_in_price = price
        self.instop.reset(price)
        self.in_count += 1
        self.in_qty_notional += self.cfg.contract.notional_usd(qty, price)

    # ------------------------------------------------------------------ helpers

    def _within_boundaries(self, price: float) -> bool:
        if self.cfg.boundaries_lower > 0 and price < self.cfg.boundaries_lower:
            return False
        if self.cfg.boundaries_upper > 0 and price > self.cfg.boundaries_upper:
            return False
        return True

    def _check_full_close(self) -> None:
        """After any close: if position = 0, reset indicator cycle (unless stopped)."""
        if not self.is_active:
            return
        if self.position_size() == 0.0 and self.out_stop_group is None:
            if len(self.active_orders) == 0:
                self.is_indicator_passed = False
                self.last_in_price = None
                self.instop.reset(0.0)
                self.instop.local_extremum = None
