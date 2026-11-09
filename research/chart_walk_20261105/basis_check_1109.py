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
from services.btc_signals import features as fx  # noqa: E402

RNG = np.random.default_rng(91109)
MULT = np.array([0.5, 0.75, 1.0, 1.25, 1.5])
FEATS = ["базис 7д среднее, %", "базис фьючерс−спот, %", "фандинг 7д, %"]


def with_funding(D, fm, a):
    """Per-leg funding only after that leg's recorded entry time.

    Unknown add time or incomplete observed payout coverage produces NaN rather
    than an invented cashflow. Exact entries use ledger's (entry, exit] cutoff.
    An engine add marked _add_before_close existed before its recorded hour-end:
    the payout at that hour-end is included. Subhour payouts remain ambiguous.
    """
    t = a["t"]
    out = []
    for _, r in D.iterrows():
        i0, i1 = int(r["_i0"]), int(r["_i1"])
        s, w = int(r["сторона"]), float(r["вес"])
        legs = [(i0, i1, float(r["цена входа"]), float(r["цена выхода"]), s, "x", "x", w * 0.5)]
        if r["добор"] == 1.0 and pd.notna(r["цена добора"]):
            add_t, add_i = r.get("_add_t"), r.get("_add_i")
            if pd.isna(add_t) and pd.notna(r.get("добор UTC")):
                add_t = pd.Timestamp(r["добор UTC"], tz="UTC").timestamp()
            if pd.notna(add_t):
                add_i = int(np.searchsorted(t, add_t))
                if add_i >= len(t) or t[add_i] != add_t:
                    add_i = None
            if pd.isna(add_i) or not i0 <= int(add_i) <= i1:
                out.append(np.nan)
                continue
            funding_i = int(add_i)
            before_close = r.get("_add_before_close", False)
            if pd.notna(before_close) and bool(before_close):
                if funding_i <= i0:
                    out.append(np.nan)
                    continue
                records = a.get("funding_records") or {}
                payout_t = np.asarray(records.get("times", []), float)
                # At hourly resolution only the hour-end payout has a known
                # order relative to a standing stop. Inside-hour payouts do not.
                if np.any((payout_t > t[funding_i - 1]) & (payout_t < t[funding_i])):
                    out.append(np.nan)
                    continue
                funding_i -= 1
            legs.append((funding_i, i1, float(r["цена добора"]), float(r["цена выхода"]), s, "x", "x", w * 0.5))
        _, coverage = fx.funding_window(a.get("funding_records"), np.array([t[x[1]] for x in legs]),
                                        np.array([t[x[1]] - t[x[0]] for x in legs]))
        if not coverage.all():
            out.append(np.nan)
            continue
        rr, ww = pl.unit(fm, legs)
        out.append(float((rr * ww).sum()))
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
                part = part[part[col].notna()]
                if part.empty:
                    continue
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
