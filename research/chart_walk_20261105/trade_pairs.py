"""PREREG_trade_ext_1109.md: связки «что усиливает» и «что дублирует что». Читает out/trade_table_btc.pkl.
Связка A·B: произведение центрированных рангов, связь с остатком цели после рангов A и B (сверх каждого по отдельности).
Запуск: python trade_pairs.py"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).parent))
import trade_scan as ts  # noqa: E402

OUT = ts.OUT
TOP = 30
pd.set_option("display.width", 260, "display.max_columns", 30, "display.max_rows", 300, "display.max_colwidth", 44)


def zrank(x):
    x = np.where(np.isfinite(x), x, np.nanmedian(x))
    r = stats.rankdata(x)
    return (r - r.mean()) / (r.std() or 1.0)


def pair_r(zA, zB, Y):
    """Связь произведения с остатком Y (n × k) после [1, zA, zB]."""
    X = np.column_stack([np.ones(len(zA)), zA, zB])
    beta, *_ = np.linalg.lstsq(X, Y, rcond=None)
    res = Y - X @ beta
    p = zA * zB
    p = p - p.mean()
    res = res - res.mean(0)
    den = np.sqrt((p ** 2).sum() * (res ** 2).sum(0))
    return np.where(den > 0, (p @ res) / den, 0.0)


def scan_pairs(D, feats):
    rows, n1, n2 = [], np.zeros(ts.NPERM), np.zeros(ts.NPERM)
    for typ in ts.TYPES:
        P = ts.periods(D, typ)
        names = list(P)
        ok = [f for f in feats if all(P[k][f].notna().sum() >= 25 for k in names)]
        for tg in ts.TARGETS:
            d0 = P[names[0]]
            y0 = d0[tg].to_numpy(float)
            r0 = {f: abs(stats.spearmanr(d0[f], y0, nan_policy="omit")[0]) for f in ok}
            cand = sorted([f for f in ok if np.isfinite(r0[f])], key=lambda f: -r0[f])[:TOP]
            Z, Y = {}, {}
            for k in names:
                d = P[k]
                y = d[tg].to_numpy(float)
                y = np.where(np.isfinite(y), y, np.nanmedian(y))
                yr = zrank(y)
                Y[k] = np.column_stack([yr] + [ts.RNG.permutation(yr) for _ in range(ts.NPERM)])
                Z[k] = {f: zrank(d[f].to_numpy(float)) for f in cand}
            for A, B in itertools.combinations(cand, 2):
                R = [pair_r(Z[k][A], Z[k][B], Y[k]) for k in names]
                N = [len(P[k]) for k in names]
                t1, t2, pd_, p1, p2 = ts.tiers(R[0], N[0], R[1], N[1], R[2], N[2])
                n1 += t1[1:]
                n2 += t2[1:]
                if t2[0]:
                    rows.append({"тип": typ, "цель": tg, "A": A, "B": B, "ярус": 1 if t1[0] else 2, "r открытие": round(float(R[0][0]), 3), "p открытие": float(pd_[0]),
                                 "r 2023–26": round(float(R[1][0]), 3), "p 2023–26": float(p1[0]), "r Bitstamp": round(float(R[2][0]), 3), "p Bitstamp": float(p2[0])})
    return pd.DataFrame(rows), n1, n2


def quadrants(D, typ, A, B, tg="итог, % базы"):
    P = ts.periods(D, typ)
    d0 = P["открытие 2018–22"]
    ma, mb = d0[A].median(), d0[B].median()
    out = []
    for k, d in P.items():
        for qa, qb in ((1, 1), (1, 0), (0, 1), (0, 0)):
            m = ((d[A] > ma) == bool(qa)) & ((d[B] > mb) == bool(qb))
            out.append({"отрезок": k, "A": "выше" if qa else "ниже", "B": "выше" if qb else "ниже", "сделок": int(m.sum()),
                        "итог": round(float(d.loc[m, tg].sum()), 1), "на сделку": round(float(d.loc[m, tg].mean()), 2) if m.any() else None})
    return pd.DataFrame(out)


def duplicates(D, feats, thr=0.8):
    b = D[D["ряд"] == "Binance"]
    use = [f for f in feats if b[f].notna().sum() >= 200 and b[f].nunique() > 2]
    C = b[use].rank().corr(method="pearson", min_periods=150).abs().to_numpy()
    n = len(use)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(n):
        for j in range(i + 1, n):
            if np.isfinite(C[i, j]) and C[i, j] > thr:
                parent[find(i)] = find(j)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(use[i])
    return [g for g in groups.values() if len(g) > 1], len(use)


def main():
    D = ts.add_best(pd.read_pickle(OUT / "trade_table_btc.pkl"))
    feats_all = [c for c in D.columns if c not in ts.OUTCOME and not c.startswith("_") and pd.api.types.is_numeric_dtype(D[c])]
    late = ts.late_feats(D, feats_all)
    full = [f for f in feats_all if f not in late]
    G, n = duplicates(D, feats_all)
    print(f"== что дублирует что: {n} признаков, групп с |ρ|>0.8 — {len(G)} ==", flush=True)
    for g in sorted(G, key=len, reverse=True):
        print(f"  [{len(g)}] " + " | ".join(g), flush=True)
    S, n1, n2 = scan_pairs(D, full)
    S.to_csv(OUT / "trade_pairs.csv", sep=";", decimal=",", index=False, encoding="utf-8-sig")
    tests = len(ts.TYPES) * len(ts.TARGETS) * TOP * (TOP - 1) // 2
    print(f"\n== связки: проверок ≈{tests}; ярус 1 — {int((S['ярус'] == 1).sum()) if len(S) else 0} (шум: {n1.mean():.1f}, 95% {np.quantile(n1, 0.95):.0f}); "
          f"ярус 1–2 — {len(S)} (шум: {n2.mean():.1f}, 95% {np.quantile(n2, 0.95):.0f}) ==", flush=True)
    if len(S):
        for tg in ts.TARGETS:
            s = S[S["цель"] == tg]
            print(f"  {tg}: ярус 1 — {int((s['ярус'] == 1).sum())}, 1–2 — {len(s)}", flush=True)
        print(S.sort_values(["ярус", "p открытие"]).head(40).round(4).to_string(index=False), flush=True)
        top = S[(S["ярус"] == 1) & (S["цель"].isin(["итог, % базы", "в лучших 20%"]))].sort_values("p открытие").head(6)
        for _, z in top.iterrows():
            print(f"\n2×2: {z['тип']} — A «{z['A']}» × B «{z['B']}» (итог, % базы)", flush=True)
            print(quadrants(D, z["тип"], z["A"], z["B"]).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
