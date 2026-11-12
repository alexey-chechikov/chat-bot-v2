"""Ансамбль окон 432 — не подобран ли набор: 6 соседних наборов против одного окна 30, Binance spot (frozen, как служба) и
перп Bybit (API), окна 3 и 2 года. Итог, просадка по закрытым, итог при той же просадке, что у окна 30, без 3 лучших сделок."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(Path(__file__).parent))
from services.btc_signals import run as rn  # noqa: E402
import ensemble_check as ec  # noqa: E402

SETS = [(30,), (20, 30, 45, 60), (25, 30, 40, 50), (20, 30, 40), (30, 45, 60), (20, 25, 30, 35, 40, 45), (15, 30, 60, 90), (30, 40, 50, 60)]


def main():
    R = rn.compute()
    a = R["a"]
    spot = (np.asarray(a["t"], np.int64), a["o"], a["h"], a["l"], a["c"])
    end = int(spot[0][-1])
    d = ec.hours("perp", end - 30000 * 3600, end)
    ks = sorted(d)
    perp = (np.array(ks, np.int64), *(np.array([d[k][i] for k in ks]) for i in range(4)))
    for src, data in (("spot", spot), ("perp", perp)):
        t, o, h, l, c = data
        cache = {}
        for s in SETS:
            for ch in s:
                if ch not in cache:
                    cache[ch] = ec.run_one(t, o, h, l, c, ch=ch)[1]
        for lab, yrs in (("3 года", 3), ("2 года", 2)):
            t0 = end - int(yrs * 365.25 * 86400)
            ref = ec.stats(cache[30], t0, end)
            print(f"\n=== {src}, {lab}: окно 30 — итог {ref['sum']:+.0f}$, просадка {ref['dd']:+.0f}$, без 3 лучших {ref['no_best3']:+.0f}$")
            for s in SETS[1:]:
                st = ec.stats([x for ch in s for x in cache[ch]], t0, end, 1 / len(s))
                eq = st["sum"] * ref["dd"] / st["dd"] if st["dd"] < 0 else float("nan")
                print(f"  {str(s):26s} итог {st['sum']:+6.0f}$  просадка {st['dd']:+5.0f}$  при просадке окна 30: {eq:+6.0f}$  без 3 лучших {st['no_best3']:+6.0f}$")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"\n{time.time() - t0:.0f} с")
