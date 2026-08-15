"""Contract models: LINEAR (USDT-M) and INVERSE (coin-margined).

SHORT bots use LINEAR BTCUSDT: qty in BTC, PnL in USDT.
LONG  bots use INVERSE XBTUSD:  qty in USD contracts, PnL in BTC.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class Side(Enum):
    LONG = 1
    SHORT = 2


class ContractType(Enum):
    LINEAR = "linear"
    INVERSE = "inverse"


class ContractModel(ABC):
    contract_type: ContractType
    pnl_currency: str
    qty_unit: str

    @abstractmethod
    def notional_usd(self, qty: float, price: float) -> float: ...

    @abstractmethod
    def unrealized_pnl(
        self, side: Side, qty: float, entry: float, current: float
    ) -> float:
        """PnL in pnl_currency."""
        ...

    @abstractmethod
    def liq_price_approx(
        self, side: Side, avg_entry: float, margin_ratio: float
    ) -> float: ...

    def pnl_to_usd(self, pnl: float, price: float) -> float:
        if self.contract_type == ContractType.LINEAR:
            return pnl
        return pnl * price  # BTC → USD at current price


@dataclass(frozen=True)
class LinearContract(ContractModel):
    """Linear USDT-M (BTCUSDT): qty in BTC, PnL in USDT."""

    contract_type: ContractType = ContractType.LINEAR
    pnl_currency: str = "USDT"
    qty_unit: str = "BTC"

    def notional_usd(self, qty: float, price: float) -> float:
        return qty * price

    def unrealized_pnl(
        self, side: Side, qty: float, entry: float, current: float
    ) -> float:
        if side == Side.SHORT:
            return qty * (entry - current)
        return qty * (current - entry)

    def liq_price_approx(
        self, side: Side, avg_entry: float, margin_ratio: float
    ) -> float:
        """
        Cross-margin liquidation price approximation.

        margin_ratio = wallet_balance / total_notional_at_entry (≈ equity/notional).
        Derivation (SHORT):
          liq = (wallet + qty*entry) / (qty*(1+mm))
              = entry*(1+margin_ratio) / (1+mm)
        Sanity: entry=77856, mr=0.343 → liq ≈ 104 000  (matches UI at 100x).
        """
        mm = LINEAR_MM_RATE
        if side == Side.SHORT:
            return avg_entry * (1.0 + margin_ratio) / (1.0 + mm)
        return avg_entry * (1.0 - margin_ratio) / (1.0 - mm)


@dataclass(frozen=True)
class InverseContract(ContractModel):
    """Inverse coin-margined (XBTUSD): qty in USD contracts, PnL in BTC."""

    contract_type: ContractType = ContractType.INVERSE
    pnl_currency: str = "BTC"
    qty_unit: str = "USD"

    def notional_usd(self, qty: float, price: float) -> float:
        return qty  # 1 contract = $1

    def unrealized_pnl(
        self, side: Side, qty: float, entry: float, current: float
    ) -> float:
        if side == Side.LONG:
            return qty * (1.0 / entry - 1.0 / current)
        return qty * (1.0 / current - 1.0 / entry)

    def liq_price_approx(
        self, side: Side, avg_entry: float, margin_ratio: float
    ) -> float:
        if side == Side.LONG:
            return avg_entry * (1.0 - margin_ratio)
        return avg_entry / (1.0 - margin_ratio)


# Maintenance margin rate for linear USDT-M at 100x leverage (Binance/BitMEX)
LINEAR_MM_RATE: float = 0.0055  # 0.55% of notional

# Singletons for convenience
LINEAR = LinearContract()
INVERSE = InverseContract()
