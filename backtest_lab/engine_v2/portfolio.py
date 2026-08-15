"""Cross-margin portfolio tracker for a set of GinareaBot instances."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .bot import GinareaBot


@dataclass
class PortfolioSnapshot:
    wallet_balance_usd: float
    equity_usd: float
    total_notional_usd: float
    margin_ratio: float
    unrealized_pnl_usd: float
    realized_pnl_usd: float
    max_drawdown: float
    liquidated: bool


class Portfolio:
    """
    Cross-margin pool shared by all bots.

    wallet_balance_usd = initial_balance + sum(realized_pnl → USD)
    equity_usd         = wallet_balance + sum(unrealized_pnl → USD)
    margin_ratio       = equity / total_notional

    Liquidation fires when margin_ratio < min_margin_ratio (with open positions).
    """

    def __init__(
        self,
        initial_balance_usd: float,
        min_margin_ratio: float = 0.0055,
    ) -> None:
        self.initial_balance_usd = initial_balance_usd
        self.min_margin_ratio = min_margin_ratio
        self._peak_equity: float = initial_balance_usd
        self._max_drawdown: float = 0.0
        self.liquidated: bool = False

    def snapshot(self, bots: list[GinareaBot], price: float) -> PortfolioSnapshot:
        """Compute current cross-margin state from all bot positions."""
        unrealized_usd = 0.0
        realized_usd = 0.0
        total_notional = 0.0

        for bot in bots:
            contract = bot.cfg.contract

            unrealized_usd += contract.pnl_to_usd(bot.unrealized_pnl(price), price)
            realized_usd += contract.pnl_to_usd(bot.realized_pnl, price)

            for order in bot.active_orders:
                total_notional += contract.notional_usd(order.qty, price)
            if bot.out_stop_group:
                for order in bot.out_stop_group.orders:
                    total_notional += contract.notional_usd(order.qty, price)

        wallet_balance = self.initial_balance_usd + realized_usd
        equity_usd = wallet_balance + unrealized_usd
        margin_ratio = equity_usd / total_notional if total_notional > 0 else float("inf")

        if equity_usd > self._peak_equity:
            self._peak_equity = equity_usd
        dd = (
            (self._peak_equity - equity_usd) / self._peak_equity
            if self._peak_equity > 0
            else 0.0
        )
        if dd > self._max_drawdown:
            self._max_drawdown = dd

        if not self.liquidated and margin_ratio < self.min_margin_ratio and total_notional > 0:
            self.liquidated = True

        return PortfolioSnapshot(
            wallet_balance_usd=wallet_balance,
            equity_usd=equity_usd,
            total_notional_usd=total_notional,
            margin_ratio=margin_ratio,
            unrealized_pnl_usd=unrealized_usd,
            realized_pnl_usd=realized_usd,
            max_drawdown=self._max_drawdown,
            liquidated=self.liquidated,
        )
