"""Источник размера страховки (executor sizing="hedge"): позиция лонг-сеток счёта в долларах.

Замер research/grid_hedge_20261114 (overlay2.py, «страховка от всего»): база = позиция BTC-сеток + позиция ETH-сетки в
пересчёте на BTC по цене часа, т. е. долларовая позиция лонгов обеих монет. Здесь — то же по бирже: сторона LONG
BTCUSDT и ETHUSDT × середина стакана. Любая неясность — ExposureError (исполнитель считает «неизвестно», эпизод не
начинает).

Разбор GPT ead2ca4 (правдоподобное, но кривое чтение давало не тот размер) — строго:
- ответ — список словарей; у строки нашей монеты сторона LONG/SHORT, иначе ошибка (строка без side давала ноль);
- одна строка на (монета, сторона) — дубль ошибка (давал ×1.5);
- размер — число или строка-число, не bool, конечный, ≥ 0 (True давал 1 контракт);
- цена стакана сверяется с ценой позиции (openValue + unrealizePnl) / size: расхождение > mark_tol — ошибка (чужой стакан
  $2 000 для BTC давал вход в 35 раз меньше);
- позиция биржи сверяется с учётом сеток (сумма лотов в state/weex_grid*_state.json по монете): расхождение больше
  допуска — ошибка (ответ только с BTC при лотах ETH давал половину размера; ручные лонги тоже остановят вход — это
  страховка сеток, а не всего, что на стороне);
- итог больше max_usd — ошибка."""
from __future__ import annotations

import json
import math
from pathlib import Path

DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT")
DEFAULT_MAX_USD = 30_000.0          # 2 × общий потолок сеток ($15 000, state/weex_portfolio_config.json)
DEFAULT_MARK_TOL = 0.03
SIDES = ("LONG", "SHORT")


class ExposureError(RuntimeError):
    pass


def _num(v, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise ExposureError(f"{what}: не число ({v!r})")
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ExposureError(f"{what}: не число ({v!r})") from None
    if not math.isfinite(x):
        raise ExposureError(f"{what}: {x}")
    return x


def check_symbols(symbols) -> tuple:
    if isinstance(symbols, str) or not isinstance(symbols, (list, tuple)) or not symbols:
        raise ExposureError(f"symbols {symbols!r}: нужен список монет")
    if not all(isinstance(s, str) and s for s in symbols) or len(set(symbols)) != len(symbols):
        raise ExposureError(f"symbols {symbols!r}: строки без повторов")
    return tuple(symbols)


def long_exposure_usd(rows, books: dict, symbols=DEFAULT_SYMBOLS, max_usd: float = DEFAULT_MAX_USD, lots: dict | None = None,
                      mark_tol: float = DEFAULT_MARK_TOL) -> float:
    """rows — ответ позиций WEEX; books — {символ: (bid, ask)}; lots — {символ: (сумма лотов сеток, допуск)} или None."""
    symbols = check_symbols(symbols)
    if not isinstance(rows, list):
        raise ExposureError(f"позиции: не список ({str(rows)[:120]})")
    seen: dict[tuple, dict] = {}
    for p in rows:
        if not isinstance(p, dict):
            raise ExposureError(f"позиции: строка не словарь ({str(p)[:80]})")
        sym = p.get("symbol")
        if sym not in symbols:
            continue
        side = p.get("side")
        if side not in SIDES:
            raise ExposureError(f"{sym}: сторона {side!r}")
        if (sym, side) in seen:
            raise ExposureError(f"{sym} {side}: две строки позиции — неоднозначно")
        seen[(sym, side)] = p
    total = 0.0
    for sym in symbols:
        p = seen.get((sym, "LONG"))
        size = _num(p.get("size"), f"{sym} LONG size") if p else 0.0
        if size < 0:
            raise ExposureError(f"{sym} LONG size {size} < 0")
        if lots is not None and sym in lots:
            want, tol = lots[sym]
            if abs(size - want) > tol:
                raise ExposureError(f"{sym}: на бирже LONG {size:g}, в учёте сеток {want:g} (допуск {tol:g}) — не сходится")
        if size <= 0:
            continue
        if sym not in books:
            raise ExposureError(f"нет стакана {sym}")
        bid, ask = (_num(x, f"{sym} стакан") for x in books[sym])
        if not 0 < bid <= ask:
            raise ExposureError(f"{sym} стакан {bid}/{ask}")
        mid = (bid + ask) / 2
        mark = (_num(p.get("openValue"), f"{sym} openValue") + _num(p.get("unrealizePnl"), f"{sym} unrealizePnl")) / size
        if not mark > 0 or abs(mid / mark - 1) > mark_tol:
            raise ExposureError(f"{sym}: стакан {mid:,.2f} против цены позиции {mark:,.2f} — расхождение больше {mark_tol:.0%}")
        total += size * mid
    if total > max_usd:
        raise ExposureError(f"позиция лонгов ${total:,.0f} больше предела ${max_usd:,.0f} — проверить руками")
    return total


def grid_lots(paths_by_symbol: dict, rel_tol: float = 0.03, lots_tol: int = 3) -> dict:
    """{символ: [state-файлы сеток]} → {символ: (сумма лотов LONG, допуск)}. Допуск — больше из rel_tol суммы и lots_tol
    самых крупных лотов (частичные исполнения входов и тейков в момент чтения). Файл не читается — ExposureError."""
    out = {}
    for sym, paths in paths_by_symbol.items():
        total, big = 0.0, 0.0
        for path in paths:
            try:
                st = json.loads(Path(path).read_text(encoding="utf-8"))
                lots = st["LONG"]["lots"]
                qs = [_num(l["qty"], f"{path} qty") for l in lots]
            except (OSError, ValueError, KeyError, TypeError) as e:
                raise ExposureError(f"учёт сетки {path}: {e!r}") from None
            total += sum(qs)
            big = max([big] + qs)
        out[sym] = (total, max(rel_tol * total, lots_tol * big, 1e-12))
    return out


class WeexExposure:
    """Чтение с WEEX (services/weex_api/client.py): позиции счёта + стакан каждой монеты с лонгом. Только чтение."""

    def __init__(self, client, symbols=DEFAULT_SYMBOLS, max_usd: float = DEFAULT_MAX_USD, grid_states: dict | None = None,
                 mark_tol: float = DEFAULT_MARK_TOL):
        self.symbols = check_symbols(symbols)
        if not (isinstance(max_usd, (int, float)) and not isinstance(max_usd, bool) and math.isfinite(max_usd) and max_usd > 0):
            raise ExposureError(f"max_usd {max_usd!r}")
        if grid_states is not None and (not isinstance(grid_states, dict) or set(grid_states) - set(self.symbols)
                                        or not all(isinstance(v, list) and v for v in grid_states.values())):
            raise ExposureError(f"grid_states {grid_states!r}: {{символ: [пути]}} по монетам из symbols")
        self.c, self.max_usd, self.grid_states, self.mark_tol = client, float(max_usd), grid_states, float(mark_tol)

    def __call__(self) -> float:
        lots = grid_lots(self.grid_states) if self.grid_states else None
        rows = self.c.futures_positions()
        held = {p.get("symbol") for p in rows if isinstance(p, dict) and p.get("side") == "LONG"} if isinstance(rows, list) else set()
        books = {s: self.c.book(s) for s in self.symbols if s in held}
        return long_exposure_usd(rows, books, self.symbols, self.max_usd, lots, self.mark_tol)


def make(hcfg: dict | None, live: bool = False):
    """Конфиг {"source": "weex" | число $ (только бумага и тесты), "symbols": [...], "max_usd": ..., "grid_states":
    {символ: [пути state сеток]}} → функция exposure(). Живой — только "weex" и с grid_states (разбор ead2ca4)."""
    hcfg = dict(hcfg or {})
    src = hcfg.get("source", "weex")
    if isinstance(src, (int, float)) and not isinstance(src, bool):
        if live:
            raise ValueError("hedge.source числом — только бумага: живой размер берётся с биржи")
        val = float(src)
        if not (math.isfinite(val) and val >= 0):
            raise ValueError(f"hedge.source {src!r}")
        return lambda: val
    if src == "weex":
        if live:
            gs, syms = hcfg.get("grid_states"), hcfg.get("symbols", list(DEFAULT_SYMBOLS))
            # разбор b056816: grid_states только для ETH пропускал BTC мимо сверки
            if not isinstance(gs, dict) or not isinstance(syms, (list, tuple)) or set(gs) != set(syms):
                raise ValueError("живая страховка: hedge.grid_states — учёт сеток для КАЖДОЙ монеты из symbols")
        from services.weex_api.client import WeexClient
        try:
            return WeexExposure(WeexClient(), hcfg.get("symbols", list(DEFAULT_SYMBOLS)), hcfg.get("max_usd", DEFAULT_MAX_USD),
                                hcfg.get("grid_states"), hcfg.get("mark_tol", DEFAULT_MARK_TOL))
        except ExposureError as e:
            raise ValueError(str(e)) from None
    raise ValueError(f"hedge.source {src!r}: \"weex\" или число $")
