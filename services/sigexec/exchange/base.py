"""Интерфейс биржи для исполнителя сигналов. Адаптеры (sim, weex, bybit, okx) приводят ответы к этим типам.

Правила (CLAUDE.md, «Живой ордерный код»):
  * Rejected — биржа ЯВНО отказала, ордера нет;
  * Unknown — исход неизвестен (таймаут, 5xx, пустой ответ, нет номера): ордер мог встать — ищем по cid;
  * Incomplete — поиск не дал ответа (история неполная): «не нашли» ≠ «не было»;
  * order() → None только когда биржа ТОЧНО говорит, что такого cid нет.
Объёмы на интерфейсе — в монете (BTC); адаптер сам переводит в контракты (OKX: ctVal)."""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field

LIVE = frozenset({"NEW", "PARTIAL", "UNTRIGGERED"})
FINAL = frozenset({"FILLED", "CANCELED", "REJECTED"})
BUY, SELL = "BUY", "SELL"
LONG, SHORT = "LONG", "SHORT"


class ExchangeError(RuntimeError):
    pass


class Rejected(ExchangeError):
    """Явный отказ: ордера нет, повторять можно с новым cid."""


class Unknown(ExchangeError):
    """Исход неизвестен: ордер мог встать. Новый ордер той же роли — только после поиска по cid."""


class Incomplete(ExchangeError):
    """Поиск неполный: отсутствие не доказано."""


@dataclass(frozen=True)
class Instrument:
    symbol: str
    tick: float
    lot: float
    min_qty: float
    ct_val: float = 1.0  # монет в одном контракте (OKX BTC-USDT-SWAP = 0.01)

    def floor_qty(self, q: float) -> float:
        n = math.floor(q / self.lot + 1e-9)
        return round(n * self.lot, 12)

    def round_px(self, p: float, mode: str = "near") -> float:
        """mode: near | down | up — к сетке тика."""
        x = p / self.tick
        n = math.floor(x + 1e-9) if mode == "down" else math.ceil(x - 1e-9) if mode == "up" else round(x)
        return round(n * self.tick, 10)

    def fmt_qty(self, q: float) -> str:
        """Только вниз к шагу: округление вверх увеличило бы позицию сверх плана."""
        return _fmt(self.floor_qty(q), self.lot)

    def fmt_px(self, p: float, side: str | None = None) -> str:
        """Цена лимитки — в свою сторону (покупка вниз, продажа вверх), чтобы post-only не пересёк стакан; иначе к ближайшему."""
        mode = "down" if side == BUY else "up" if side == SELL else "near"
        return _fmt(self.round_px(p, mode), self.tick)


def _fmt(v: float, step: float) -> str:
    dec = max(0, -int(math.floor(math.log10(step)))) if step < 1 else 0
    return f"{v:.{dec}f}"


@dataclass
class OrderReq:
    cid: str
    symbol: str
    side: str            # BUY | SELL
    pos_side: str        # LONG | SHORT (в одностороннем режиме адаптер игнорирует)
    kind: str            # MARKET | LIMIT | STOP (стоп — рыночный по срабатыванию)
    qty: float           # в монете
    price: float | None = None
    trigger: float | None = None
    post_only: bool = False
    reduce_only: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OrderInfo:
    cid: str
    status: str          # NEW | PARTIAL | UNTRIGGERED | FILLED | CANCELED | REJECTED
    filled: float = 0.0  # исполнено, монет (накопленно)
    avg: float = 0.0     # средняя цена исполнения
    fee: float = 0.0     # комиссия в USDT, плюс = заплачено
    oid: str = ""
    raw: dict = field(default_factory=dict, repr=False)
    fee_known: bool = True  # False — комиссия не дочитана (поздние сделки), учёт пометит

    @property
    def final(self) -> bool:
        return self.status in FINAL


class Exchange(ABC):
    """Одна биржа, линейные USDT-перпы. Хедж-режим (LONG и SHORT раздельно) — рекомендуемый."""

    name = "base"
    hedge = True

    @abstractmethod
    def now(self) -> float: ...

    @abstractmethod
    def instrument(self, symbol: str) -> Instrument: ...

    @abstractmethod
    def book(self, symbol: str) -> tuple[float, float]:
        """(лучшая покупка, лучшая продажа)."""

    @abstractmethod
    def position(self, symbol: str) -> dict[str, float]:
        """{"LONG": монет, "SHORT": монет} — вся позиция счёта (свои + чужие сделки)."""

    @abstractmethod
    def place(self, req: OrderReq) -> OrderInfo:
        """→ состояние сразу после постановки. Rejected — отказ; Unknown — исход неизвестен."""

    @abstractmethod
    def cancel(self, symbol: str, cid: str, kind: str, oid: str = "", placed_at: float = 0.0) -> None:
        """Снять. Уже конечный — не ошибка. Unknown — не знаем, снят ли (проверить order())."""

    @abstractmethod
    def order(self, symbol: str, cid: str, kind: str, oid: str = "", placed_at: float = 0.0) -> OrderInfo | None:
        """Состояние по cid. None — биржа точно не знает такой заявки; Incomplete — поиск неполный."""
