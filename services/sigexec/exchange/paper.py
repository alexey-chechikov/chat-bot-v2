"""Бумажная биржа: имитатор (sim.SimExchange) с ценой выбранной площадки из публичного стакана — без ключей, заявки
никуда не уходят. Состояние переживает перезапуск (state_file). Комиссии — ставки площадки (без скидок)."""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

from .sim import SimExchange

FEES = {"weex": (0.00016, 0.00048), "bybit": (0.0002, 0.00055), "okx": (0.0002, 0.0005), "sim": (0.00016, 0.00048), "binance": (0.0002, 0.0005)}
SPECS = {"weex": (0.1, 0.0001, 0.0001), "bybit": (0.1, 0.001, 0.001), "okx": (0.1, 0.0001, 0.0001), "sim": (0.1, 0.0001, 0.0001), "binance": (0.1, 0.001, 0.001)}


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "bot7-sigexec/1.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def public_book(venue: str, symbol: str = "BTCUSDT", getter=_get) -> tuple[float, float]:
    if venue == "bybit":
        x = getter(f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={symbol}")["result"]["list"][0]
        return float(x["bid1Price"]), float(x["ask1Price"])
    if venue == "okx":
        inst = symbol.replace("USDT", "-USDT-SWAP")
        x = getter(f"https://www.okx.com/api/v5/market/ticker?instId={inst}")["data"][0]
        return float(x["bidPx"]), float(x["askPx"])
    if venue == "weex":
        x = getter(f"https://api-contract.weex.com/capi/v3/market/ticker/bookTicker?symbol={symbol}")
        x = x[0] if isinstance(x, list) else x
        return float(x["bidPrice"]), float(x["askPrice"])
    x = getter(f"https://api.binance.com/api/v3/ticker/bookTicker?symbol={symbol}")
    return float(x["bidPrice"]), float(x["askPrice"])


class PaperExchange(SimExchange):
    def __init__(self, symbol: str = "BTCUSDT", venue: str = "binance", state_file: Path | None = None, getter=_get):
        mk, tk = FEES.get(venue, FEES["binance"])
        tick, lot, mn = SPECS.get(venue, SPECS["binance"])
        super().__init__(symbol=symbol, price=1.0, tick=tick, lot=lot, min_qty=mn, maker=mk, taker=tk, slip=0.0, clock=time.time)
        self.name = f"paper-{venue}"
        self.venue, self.getter, self.state_file = venue, getter, state_file
        self.spread = (0.0, 0.0)
        if state_file:
            self.load(Path(state_file))
        self.refresh_price()

    def refresh_price(self) -> None:
        bid, ask = public_book(self.venue if self.venue != "sim" else "binance", self.inst.symbol, self.getter)
        self.spread = (bid, ask)
        self.move((bid + ask) / 2)

    def book(self, symbol: str) -> tuple[float, float]:
        return self.spread if self.spread[0] else super().book(symbol)

    def save(self) -> None:
        if self.state_file:
            self.dump(Path(self.state_file))
