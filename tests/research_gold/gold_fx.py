"""Синтетические минутки для тестов research/gold (разбор GPT 13.10, §4–6). Никаких CSV, сети и живого кода."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

GOLD = Path(__file__).resolve().parents[2] / "research" / "gold"
if str(GOLD) not in sys.path:
    sys.path.insert(0, str(GOLD))

import sweep_backtest as sb  # noqa: E402

PRE_CUT_DAY = 20_000      # 2024-10-04 UTC — у PAXG шаг цены 1.00
POST_CUT_DAY = 20_300     # 2025-07-31 UTC — у PAXG шаг цены 0.01


def block(day: int, start_min: int, minutes: int, price: float, volume: float = 1.0) -> dict:
    ts = day * sb.DAY + np.arange(start_min, start_min + minutes) * sb.MIN
    return {"ts": ts.astype(np.int64), **{k: np.full(minutes, price, dtype=float)
            for k in ("open", "high", "low", "close")}, "volume": np.full(minutes, volume, dtype=float)}


def combine(*parts) -> dict:
    out = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
    order = np.argsort(out["ts"], kind="stable")
    return {k: v[order] for k, v in out.items()}


def set_bar(a: dict, day: int, bar_min: int, *, o, h, l, c, volume=None) -> None:
    """Все минуты 15m-свечи [bar_min, bar_min+15) дня `day` получают o/h/l/c (минимум/максимум свечи = l/h)."""
    mask = (a["ts"] >= day * sb.DAY + bar_min * sb.MIN) & (a["ts"] < day * sb.DAY + (bar_min + 15) * sb.MIN)
    for k, val in (("open", o), ("high", h), ("low", l), ("close", c)):
        a[k][mask] = val
    if volume is not None:
        a["volume"][mask] = volume


def set_minute(a: dict, day: int, minute: int, **kw) -> None:
    i = int(np.flatnonzero(a["ts"] == day * sb.DAY + minute * sb.MIN)[0])
    for k, v in kw.items():
        a[k][i] = v


def normal_fixture(day0: int, minutes: int = 360, rest: float = 104.0) -> dict:
    """День day0: 15 минут по 100 (минимум 100 → уровень L следующего дня). День day0+1: сигнал в 00:00
    (low 99 < 100 < close 100.5), подтверждение в 00:15 (close 101.5 > high 101), вход в 00:30 по open `rest`."""
    a = combine(block(day0, 0, 15, 100), block(day0 + 1, 0, minutes, rest))
    set_bar(a, day0 + 1, 0, o=100.5, h=101, l=99, c=100.5)
    set_bar(a, day0 + 1, 15, o=100.5, h=102, l=99.5, c=101.5)
    return a


def first_trade(a: dict, inst: str = "PAXG", costs: str = "net", version: str = "A", **mattrs) -> dict:
    m = sb.Market(a, inst, False)
    for k, v in mattrs.items():
        setattr(m, k, v)
    out = sb.simulate(m, version, 3000.0, costs)
    assert out["trades"], "фикстура не дала задуманной сделки"
    return out["trades"][0]
