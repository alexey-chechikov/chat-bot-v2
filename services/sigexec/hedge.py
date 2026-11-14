"""Источник размера страховки (executor sizing="hedge"): позиция лонг-сеток счёта в долларах.

Замер research/grid_hedge_20261114 (overlay2.py, «страховка от всего»): база = позиция BTC-сеток + позиция ETH-сетки в
пересчёте на BTC по цене часа, т. е. долларовая позиция лонгов обеих монет. Здесь — то же по бирже: сторона LONG
BTCUSDT и ETHUSDT (сетки ведут только LONG; ручные лонги оператора тоже попадут — страховка счёта, не бота) × середина
стакана. Любая неясность — ExposureError (исполнитель считает «неизвестно», эпизод не начинает): ответ не список,
размер не число или < 0, стакан пустой/перевёрнутый, итог больше max_usd (кривое чтение не должно открыть шорт на
весь депозит)."""
from __future__ import annotations

import math

DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT")
DEFAULT_MAX_USD = 30_000.0          # 2 × общий потолок сеток ($15 000, state/weex_portfolio_config.json)


class ExposureError(RuntimeError):
    pass


def _num(v, what: str) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ExposureError(f"{what}: не число ({v!r})") from None
    if not math.isfinite(x):
        raise ExposureError(f"{what}: {x}")
    return x


def long_exposure_usd(rows, books: dict, symbols=DEFAULT_SYMBOLS, max_usd: float = DEFAULT_MAX_USD) -> float:
    """rows — ответ позиций WEEX (список {symbol, side, size}); books — {символ: (bid, ask)}."""
    if not isinstance(rows, list):
        raise ExposureError(f"позиции: не список ({str(rows)[:120]})")
    total = 0.0
    for sym in symbols:
        size = 0.0
        for p in rows:
            if not isinstance(p, dict):
                raise ExposureError(f"позиции: строка не словарь ({str(p)[:80]})")
            if p.get("symbol") == sym and p.get("side") == "LONG":
                q = _num(p.get("size"), f"{sym} LONG size")
                if q < 0:
                    raise ExposureError(f"{sym} LONG size {q} < 0")
                size += q
        if size <= 0:
            continue
        if sym not in books:
            raise ExposureError(f"нет стакана {sym}")
        bid, ask = (_num(x, f"{sym} стакан") for x in books[sym])
        if not 0 < bid <= ask:
            raise ExposureError(f"{sym} стакан {bid}/{ask}")
        total += size * (bid + ask) / 2
    if total > max_usd:
        raise ExposureError(f"позиция лонгов ${total:,.0f} больше предела ${max_usd:,.0f} — проверить руками")
    return total


class WeexExposure:
    """Чтение с WEEX (services/weex_api/client.py): позиции счёта + стакан каждой монеты с лонгом. Только чтение."""

    def __init__(self, client, symbols=DEFAULT_SYMBOLS, max_usd: float = DEFAULT_MAX_USD):
        if not symbols or not all(isinstance(s, str) and s for s in symbols):
            raise ValueError(f"symbols {symbols!r}")
        if not (isinstance(max_usd, (int, float)) and math.isfinite(max_usd) and max_usd > 0):
            raise ValueError(f"max_usd {max_usd!r}")
        self.c, self.symbols, self.max_usd = client, tuple(symbols), float(max_usd)

    def __call__(self) -> float:
        rows = self.c.futures_positions()
        need = {p.get("symbol") for p in rows if isinstance(p, dict) and p.get("side") == "LONG"} if isinstance(rows, list) else set()
        books = {s: self.c.book(s) for s in self.symbols if s in need}
        return long_exposure_usd(rows, books, self.symbols, self.max_usd)


def make(hcfg: dict | None):
    """Конфиг {"source": "weex" | число $ (бумага и тесты), "symbols": [...], "max_usd": ...} → функция exposure()."""
    hcfg = dict(hcfg or {})
    src = hcfg.get("source", "weex")
    if isinstance(src, (int, float)) and not isinstance(src, bool):
        val = float(src)
        if not (math.isfinite(val) and val >= 0):
            raise ValueError(f"hedge.source {src!r}")
        return lambda: val
    if src == "weex":
        from services.weex_api.client import WeexClient
        return WeexExposure(WeexClient(), hcfg.get("symbols", DEFAULT_SYMBOLS), hcfg.get("max_usd", DEFAULT_MAX_USD))
    raise ValueError(f"hedge.source {src!r}: \"weex\" или число $")
