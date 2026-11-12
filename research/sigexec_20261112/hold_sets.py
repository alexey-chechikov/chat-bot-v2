"""Тот же приём, что окна, но для выхода 432: ансамбль сроков удержания (сейчас выход через 20 свечей 4ч — так закрыты 24
сделки из 26 за 2 года). Окна 20–45 × сроки {20} (как выбрано) против окна 20–45 × сроки {15, 20, 25, 30}. Binance spot (frozen)
и перп Bybit, 3 и 2 года, при той же просадке, что у окна 30 со сроком 20."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, "/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(Path(__file__).parent))
from services.btc_signals import engine as en  # noqa: E402
from services.btc_signals import run as rn  # noqa: E402
import ensemble_check as ec  # noqa: E402

WINS = (20, 25, 30, 35, 40, 45)


def q_trades(t, o, h, l, c, ch, hold):
    old_ch, old_h = en.CH432, en.HOLD432
    en.CH432, en.HOLD432 = ch, hold
    try:
        ts = np.asarray(t, np.int64)
        a, _ = ec.L.build(ts, o, h, l, c, i0_t=int(ts[0]))
        ev, _, _ = en.simulate432(a)
    finally:
        en.CH432, en.HOLD432 = old_ch, old_h
    return [(int(e["pos"]["entry_t"]), int(e["t"]), e["res"] * 10) for e in ev if e["kind"] == "выход"]


def main():
    R = rn.compute()
    a = R["a"]
    spot = (np.asarray(a["t"], np.int64), a["o"], a["h"], a["l"], a["c"])
    end = int(spot[0][-1])
    d = ec.hours("perp", end - 30000 * 3600, end)
    ks = sorted(d)
    perp = (np.array(ks, np.int64), *(np.array([d[k][i] for k in ks]) for i in range(4)))
    variants = {"окно 30, срок 20 (как было)": [(30, 20)], "окна 20–45, срок 20 (выбрано)": [(w, 20) for w in WINS],
                "окна 20–45 × сроки 15/20/25/30": [(w, hd) for w in WINS for hd in (15, 20, 25, 30)],
                "окна 20–45 × сроки 20/25/30": [(w, hd) for w in WINS for hd in (20, 25, 30)],
                "окна 20–45 × сроки 15/20/25": [(w, hd) for w in WINS for hd in (15, 20, 25)]}
    for src, data in (("spot", spot), ("perp", perp)):
        cache = {}
        for parts in variants.values():
            for p in parts:
                if p not in cache:
                    cache[p] = q_trades(*data, *p)
        for lab, yrs in (("3 года", 3), ("2 года", 2)):
            t0 = end - int(yrs * 365.25 * 86400)
            ref = ec.stats(cache[(30, 20)], t0, end)
            print(f"\n=== 432, {src}, {lab} ===")
            for name, parts in variants.items():
                s = ec.stats([x for p in parts for x in cache[p]], t0, end, 1 / len(parts))
                eq = s["sum"] * ref["dd"] / s["dd"] if s["dd"] < 0 else float("nan")
                print(f"  {name:34s} итог {s['sum']:+6.0f}$  просадка {s['dd']:+5.0f}$  при просадке окна 30: {eq:+6.0f}$  без 3 лучших {s['no_best3']:+6.0f}$")


if __name__ == "__main__":
    main()
