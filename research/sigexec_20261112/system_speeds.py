"""Ансамбль скоростей для системы оператора (оператор 12.11: «проверь ещё и на моей стратегии»).
Источник идеи: Man AHL «The Need for Speed in Trend-Following» — разные скорости тренда слабо коррелируют, смесь режет
просадку; для 432 тот же приём (ансамбль окон) дал +76% при той же просадке.
Система — те же правила, длины линий (TEMA 50/100/200, EMA 200) × масштаб; части по 1/N базы. Наборы масштабов — соседние,
чтобы не подобрать удачный. Binance spot (frozen, как служба) и перп Bybit, окна 3 и 2 года; плюс 2018–26 по годам."""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, "/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(Path(__file__).parent))
from services.btc_signals import engine as en  # noqa: E402
from services.btc_signals import run as rn  # noqa: E402
import ensemble_check as ec  # noqa: E402

L = ec.L
SETS = [(1.0,), (0.8, 0.9, 1.0, 1.1, 1.2), (0.75, 1.0, 1.25), (0.9, 1.0, 1.1), (0.7, 0.85, 1.0, 1.15, 1.3), (0.6, 0.8, 1.0, 1.2, 1.4), (0.5, 0.75, 1.0, 1.5, 2.0)]


def sys_trades(t, o, h, l, c, k):
    lens = tuple(max(5, int(round(x * k))) for x in L.LENS)
    a, lay = L.build(t, o, h, l, c, i0_t=int(t[0]), lens=lens)
    ev, _ = en.simulate(a, lay)
    return [(int(e["pos"]["entry_t"]), int(e["t"]), e["res"] * 10) for e in ev if e["kind"] == "выход"]


def main():
    R = rn.compute()
    a = R["a"]
    spot = (np.asarray(a["t"], np.int64), a["o"], a["h"], a["l"], a["c"])
    end = int(spot[0][-1])
    d = ec.hours("perp", end - 30000 * 3600, end)
    ks = sorted(d)
    perp = (np.array(ks, np.int64), *(np.array([d[k][i] for k in ks]) for i in range(4)))
    ks_all = sorted({k for s in SETS for k in s})
    for src, data in (("spot", spot), ("perp", perp)):
        cache = {k: sys_trades(*data, k) for k in ks_all}
        for lab, yrs in (("3 года", 3), ("2 года", 2)):
            t0 = end - int(yrs * 365.25 * 86400)
            ref = ec.stats(cache[1.0], t0, end)
            print(f"\n=== система, {src}, {lab}: как есть — итог {ref['sum']:+.0f}$, просадка {ref['dd']:+.0f}$, без 3 лучших {ref['no_best3']:+.0f}$")
            for k in ks_all:
                if k != 1.0:
                    s = ec.stats(cache[k], t0, end)
                    print(f"     одна скорость ×{k:<4}: итог {s['sum']:+6.0f}$  просадка {s['dd']:+5.0f}$")
            for st in SETS[1:]:
                s = ec.stats([x for k in st for x in cache[k]], t0, end, 1 / len(st))
                eq = s["sum"] * ref["dd"] / s["dd"] if s["dd"] < 0 else float("nan")
                print(f"  {str(st):30s} итог {s['sum']:+6.0f}$  просадка {s['dd']:+5.0f}$  при той же просадке {eq:+6.0f}$  без 3 лучших {s['no_best3']:+6.0f}$")
        if src == "spot":
            print("\nсистема spot по годам: как есть / ансамбль 0.8–1.2 (×1/5)")
            for y in range(2018, 2027):
                one = sum(r for a0, _, r in cache[1.0] if datetime.fromtimestamp(a0, timezone.utc).year == y)
                ens = sum(r / 5 for k in SETS[1] for a0, _, r in cache[k] if datetime.fromtimestamp(a0, timezone.utc).year == y)
                print(f"  {y}: {one:+7.0f}  {ens:+7.0f}")


if __name__ == "__main__":
    main()
