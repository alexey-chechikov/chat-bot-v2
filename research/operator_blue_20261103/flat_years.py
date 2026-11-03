"""Флет-правило оператора по годам (после study.py, описательно): две сетки 0.6/1.4, закрытие стороны только при закрытии 4ч
дальше X от голубой 4ч; θ 0.4%, X 2 / 3%. Сравнение: обе сетки всегда, лонг по дневной SMA100. Итог $ полного капитала.
Запуск: flat_years.py --pk-btc=<pkl>"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from study import TS, S, gridk  # noqa: E402


def main():
    pk = Path(next(a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--pk-btc=")))
    m, h1, h4, d1, fund = pd.read_pickle(pk)
    mk = gridk.Market(m["ts"].to_numpy(), m["open"].to_numpy(), m["high"].to_numpy(), m["low"].to_numpy(),
                      m["close"].to_numpy(), fund)
    c4, k4 = h4["close"].to_numpy(), h4["known"].to_numpy()
    B4 = S.ema(c4, 200)
    sl = B4 / np.r_[np.full(6, np.nan), B4[:-6]] - 1
    end_ts = int(m["ts"].iloc[-1]) + 60

    def eps_rule(th, X):
        with np.errstate(invalid="ignore"):
            arm = (np.abs(sl) <= th) & (np.abs(c4 / B4 - 1) <= X)
            kill = {1: c4 < B4 * (1 - X), -1: c4 > B4 * (1 + X)}
        out = {}
        for side in (1, -1):
            on, start, ep = False, 0, []
            for i in range(400, len(c4)):
                if on and kill[side][i]:
                    ep.append((start, int(k4[i])))
                    on = False
                elif not on and arm[i]:
                    on, start = True, int(k4[i])
            if on:
                ep.append((start, end_ts))
            out[side] = ep
        return out

    def total(eps, side, ta, tb, cap):
        cl = [(max(x, ta), min(y, tb)) for x, y in eps if y > ta and x < tb]
        if not cl:
            return 0.0
        return float(mk.run(mk.idx([x for x, _ in cl]), mk.idx([y for _, y in cl]), side, cap=cap)[:, 0].sum())

    reg = d1["reg0"]
    on = (reg == 1).to_numpy()
    days = reg.index.to_numpy()
    sma_eps, s0 = [], None
    for d_, o_ in zip(days, on):
        if o_ and s0 is None:
            s0 = int(d_)
        elif not o_ and s0 is not None:
            sma_eps.append((s0, int(d_)))
            s0 = None
    if s0 is not None:
        sma_eps.append((s0, end_ts))
    rules = {f"флет X {x * 100:g}%": eps_rule(0.004, x) for x in (0.02, 0.03)}
    years = [(str(y), f"{y}-01-01", f"{y + 1}-01-01") for y in range(2018, 2026)] + [("2026 янв–02.11", "2026-01-01", "2026-11-03")]
    print("| Год | " + " | ".join(list(rules) + ["обе всегда", "лонг по SMA100"]) + " |")
    print("|---|" + "---:|" * (len(rules) + 2))
    tot = np.zeros(len(rules) + 2)
    for nm, a, b in years:
        ta, tb = TS(a), min(TS(b), end_ts)
        vals = [total(e[1], 1, ta, tb, 3000.0) + total(e[-1], -1, ta, tb, 3000.0) for e in rules.values()]
        both = total([(ta, tb)], 1, ta, tb, 3000.0) + total([(ta, tb)], -1, ta, tb, 3000.0)
        vals += [both, total(sma_eps, 1, ta, tb, 6000.0)]
        tot += vals
        print(f"| {nm} | " + " | ".join(f"{v:+.0f}" for v in vals) + " |")
    print("| всего | " + " | ".join(f"**{v:+.0f}**" for v in tot) + " |")


if __name__ == "__main__":
    main()
