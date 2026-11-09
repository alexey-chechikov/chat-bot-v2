"""Сверка таблиц Вина по запискам 07.11 своим кодом: закрытие лонга под жёлтой, чистый шорт, сколько дней под синей. И ожидаемые числа Простого+ на графике."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import bybit_check as bc  # noqa: E402
import plus as pl  # noqa: E402
import state_card as sc  # noqa: E402
import state_map as sm  # noqa: E402
import words2 as w2  # noqa: E402
import words3_sweep as ws  # noqa: E402

pd.set_option("display.width", 220, "display.max_columns", 30)
SC = 0.068


def dwell(a, f, days=(0, 2, 3, 7, 14, 21, 30)):
    """Шорт с дня D под синей до 2 закрытий над ней: начало эпизода — первое закрытие 4ч под синей, конец — 2 закрытия над ней."""
    t, c, j = a["t"], a["c"], a["j"]
    rB = a["f_run_B"]
    out = {}
    new4 = np.flatnonzero(np.r_[True, j[1:] != j[:-1]])
    new4 = new4[new4 >= a["i0"]]
    eps, st = [], None
    for i in new4:
        if st is None and rB[i] < 0:
            st = i
        elif st is not None and rB[i] >= 2:
            eps.append((st, i))
            st = None
    for D in days:
        v = []
        for s, e in eps:
            k = new4[(new4 >= s) & (new4 < e) & (t[new4] >= t[s] + D * 86400)]
            if len(k):
                v.append(w2.net(f, (int(k[0]), int(e), float(c[k[0]]), float(c[e]), -1)))
        out[D] = (round(float(np.mean(v)), 1), len(v))
    return out


def main():
    cut = sm.T("2026-11-07")
    S = []
    for k in ("BTC", "ETH"):
        a, f, _ = sc.load_coin(k)
        S.append((k, a, f))
    for k, grp, a, f in ws.series():
        if k in ("Bitstamp", "XRP"):
            S.append((k, a, f))
    for k, a, f in S:
        lay = pl.layer(a)
        print(k, "выход лонга под Y", {x: pl.stats(a, f, pl.run(a, lx="Y", lay=lay, cut=cut))[x] for x in ("итог", "просадка", "с2025")}, flush=True)
        print(k, "дни под синей", dwell(a, f), flush=True)
    by = bc.load_bybit()
    frm = sm.T("2025-01-01")
    bn, _, _ = sc.load_coin("BTC")
    for lab, a in (("BYBIT:BTCUSDT.P", by), ("BINANCE:BTCUSDT", bn)):
        legs = [x for x in pl.run(a) if x[6] != "конец" and a["t"][x[0]] >= frm]
        v = np.array([x[7] * (x[4] * (x[3] / x[2] - 1) * 100 - SC - SC * x[3] / x[2]) for x in legs])
        s = np.array([x[4] for x in legs])
        print(lab, "Простое+ на графике: закрытых", len(v), "итог", round(float(v.sum()), 1), "лонг", round(float(v[s == 1].sum()), 1), "шорт", round(float(v[s == -1].sum()), 1), "последняя", sm.utc(a["t"][legs[-1][0]]), sm.utc(a["t"][legs[-1][1]]), legs[-1][4], round(float(v[-1]), 2), flush=True)


if __name__ == "__main__":
    main()
