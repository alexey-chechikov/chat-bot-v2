"""PREREG_trade_ext_1109.md: шорт под синей — размер по базису фьючерс−спот (и соседи). Границы пятых — первая половина
сделок с данными, проверка — вторая. Итог без фандинга (как в таблице) и с фандингом по выплатам. Запуск: python basis_check_1109.py"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import plus as pl  # noqa: E402
import state_card as sc  # noqa: E402
import trade_scan as ts  # noqa: E402

RNG = np.random.default_rng(91109)
MULT = np.array([0.5, 0.75, 1.0, 1.25, 1.5])
FEATS = ["базис 7д среднее, %", "базис фьючерс−спот, %", "фандинг 7д, %"]


def with_funding(D, fm, a):
    """Итог позиции с фандингом: те же ноги, что в службе (первый лот + добор), через ledger-учёт plus.unit."""
    t = a["t"]
    out = []
    for _, r in D.iterrows():
        i0, i1 = int(r["_i0"]), int(r["_i1"])
        s, w = int(r["сторона"]), float(r["вес"])
        legs = [(i0, i1, float(r["цена входа"]), float(r["цена выхода"]), s, "x", "x", w * 0.5)]
        if r["добор"] == 1.0 and pd.notna(r["цена добора"]):
            legs.append((i0, i1, float(r["цена добора"]), float(r["цена выхода"]), s, "x", "x", w * 0.5))
        rr, ww = pl.unit(fm, legs)
        out.append(float((rr * ww).sum()))
    _ = t
    return np.array(out)


def main():
    D = pd.read_pickle(ts.OUT / "trade_table_btc.pkl")
    a, fm, _ = sc.load_coin("BTC")
    d = D[(D["тип"] == "шорт под синей") & (D["ряд"] == "Binance")].sort_values("_t0").copy()
    d["итог с фандингом"] = with_funding(d, fm, a)
    rows = []
    for ft in FEATS:
        x = d[d[ft].notna()]
        h = len(x) // 2
        first, second = x.iloc[:h], x.iloc[h:]
        edges = np.quantile(first[ft], [0.2, 0.4, 0.6, 0.8])
        for col in ("итог, % базы", "итог с фандингом"):
            for nm, part in (("1-я половина", first), ("2-я половина", second)):
                q = np.searchsorted(edges, part[ft].to_numpy(float))
                y = part[col].to_numpy(float)
                base, size, skip = y.sum(), (y * MULT[q]).sum(), y[q > 0].sum()
                row = {"признак": ft, "итог": col, "часть": nm, "сделок": len(part), "с": pd.Timestamp(int(part["_t0"].iloc[0]), unit="s").strftime("%Y-%m"),
                       "база": round(float(base), 1), "размер 0.5–1.5": round(float(size), 1), "без худшей пятой": round(float(skip), 1),
                       "по пятым (итог)": " / ".join(f"{y[q == k].sum():+.1f}" for k in range(5))}
                if nm == "2-я половина":
                    xs = part[ft].to_numpy(float)
                    null_size = [(y * MULT[np.searchsorted(edges, RNG.permutation(xs))]).sum() for _ in range(999)]
                    null_skip = [y[np.searchsorted(edges, RNG.permutation(xs)) > 0].sum() for _ in range(999)]
                    row["ранг размера"] = round(float((np.sum(np.array(null_size) >= size) + 1) / 1000), 3)
                    row["ранг пропуска"] = round(float((np.sum(np.array(null_skip) >= skip) + 1) / 1000), 3)
                rows.append(row)
    R = pd.DataFrame(rows)
    pd.set_option("display.width", 260, "display.max_columns", 20)
    print(R.to_string(index=False), flush=True)
    R.to_csv(ts.OUT / "basis_check_1109.csv", index=False)


if __name__ == "__main__":
    main()
