"""PREREG_trade_ext_1109.md: шорт под жёлтой — размер и пропуск по расхождению цены и RSI (и соседи). Запуск: python div_check_1109.py"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import trade_scan as ts  # noqa: E402

RNG = np.random.default_rng(91110)
MULT = np.array([0.5, 0.75, 1.0, 1.25, 1.5])
FEATS = ["цена минус RSI в канале 30 свечей 4ч", "цена минус MACD в канале 30 свечей 4ч", "медв. дивергенция RSI 4ч за 6 свечей"]


def bins(x, edges):
    q = np.searchsorted(edges, x, side="right")
    return np.clip(np.where(np.isfinite(x), q, 2), 0, 4)


def main():
    D = pd.read_pickle(ts.OUT / "trade_table_btc.pkl")
    P = ts.periods(D, "шорт под жёлтой")
    rows = []
    for ft in FEATS:
        x0 = P["открытие 2018–22"][ft].to_numpy(float)
        edges = np.unique(np.nanquantile(x0, [0.2, 0.4, 0.6, 0.8]))
        binary = len(edges) < 4
        for nm, d in P.items():
            x, y = d[ft].to_numpy(float), d["итог, % базы"].to_numpy(float)
            if binary:
                q = np.where(x > 0, 4, 0)
            else:
                q = bins(x, edges)
            size = (y * MULT[q]).sum()
            skip = y[q > 0].sum()
            row = {"признак": ft, "отрезок": nm, "сделок": len(d), "база": round(float(y.sum()), 1), "размер 0.5–1.5": round(float(size), 1),
                   "без худшей пятой": round(float(skip), 1), "по корзинам": " / ".join(f"{y[q == k].sum():+.1f}({int((q == k).sum())})" for k in range(5))}
            if nm != "открытие 2018–22":
                ns, nk = [], []
                for _ in range(999):
                    pq = RNG.permutation(q)
                    ns.append((y * MULT[pq]).sum())
                    nk.append(y[pq > 0].sum())
                row["ранг размера"] = round(float((np.sum(np.array(ns) >= size) + 1) / 1000), 3)
                row["ранг пропуска"] = round(float((np.sum(np.array(nk) >= skip) + 1) / 1000), 3)
            rows.append(row)
    R = pd.DataFrame(rows)
    pd.set_option("display.width", 260, "display.max_columns", 20, "display.max_colwidth", 60)
    print(R.to_string(index=False), flush=True)
    R.to_csv(ts.OUT / "div_check_1109.csv", index=False)


if __name__ == "__main__":
    main()
