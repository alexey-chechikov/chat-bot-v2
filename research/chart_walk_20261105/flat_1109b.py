"""PREREG_flat_1109.md, M2: модель на итоге сделки (Ridge), а не на знаке. Признаки и обучение — как flat_1109.M."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).parent))
import btc_lab as bl  # noqa: E402
import flat_1109 as fl  # noqa: E402
import state_map as sm  # noqa: E402

pd.set_option("display.width", 250, "display.max_columns", 30)


def fit(X, y):
    lo, hi = np.quantile(y, [0.05, 0.95])
    sc = StandardScaler().fit(X)
    md = Ridge(alpha=10.0).fit(sc.transform(X), np.clip(y, lo, hi))
    return lambda Z: md.predict(sc.transform(Z)), md


def rank_in(train_pred, x):
    s = np.sort(train_pred)
    return np.searchsorted(s, x, side="right") / len(s)


def main():
    (a, f, lay), (b, fb, layb) = bl.load()
    P, Pb = fl.positions(a, lay), fl.positions(b, layb)
    X, Xb = np.vstack(P["x"]), np.vstack(Pb["x"])
    res, resb = P["res"].to_numpy(), Pb["res"].to_numpy()
    yr = pd.to_datetime(P["t"], unit="s").dt.year.to_numpy()
    yrb = pd.to_datetime(Pb["t"], unit="s").dt.year.to_numpy()
    pred, rk = np.full(len(P), np.nan), np.full(len(P), np.nan)
    for Y in sorted(set(yr)):
        tr = P["t1"].to_numpy() < sm.T(f"{Y}-01-01")
        Xtr, ytr = np.vstack([Xb, X[tr]]), np.r_[resb, res[tr]]
        f_, _ = fit(Xtr, ytr)
        k = yr == Y
        pred[k] = f_(X[k])
        rk[k] = rank_in(f_(Xtr), pred[k])
    f_, md = fit(X, res)
    pb = f_(Xb)
    rkb = rank_in(f_(X), pb)
    t = P["t"].to_numpy()
    c1 = np.corrcoef(pred[t < fl.CUT], res[t < fl.CUT])[0, 1]
    c2 = np.corrcoef(pred[t >= fl.CUT], res[t >= fl.CUT])[0, 1]
    cb = np.corrcoef(pb, resb)[0, 1]
    print(f"связь прогноза с итогом вне выборки: 2018–22 {c1:+.3f}, 2023–26 {c2:+.3f}, Bitstamp {cb:+.3f}", flush=True)
    rows = []
    b1, b2, b25 = fl.halves(P, res)
    rows.append({"что": "база (позиции, без фандинга)", "2018–22": b1, "2023–26": b2, "с 2025": b25, "Bitstamp": round(float(resb.sum()), 1), "ранг Binance": "", "ранг Bitstamp": ""})
    keep, keepb = rk >= 0.3, rkb >= 0.3
    r1, r2, r25 = fl.halves(P, np.where(keep, res, 0.0))
    rows.append({"что": f"M2 U1 пропуск худших (пропущено {int((~keep).sum())} / {int((~keepb).sum())})", "2018–22": r1, "2023–26": r2, "с 2025": r25,
                 "Bitstamp": round(float(resb[keepb].sum()), 1), "ранг Binance": round(fl.placebo_skip(res, keep, yr), 3), "ранг Bitstamp": round(fl.placebo_skip(resb, keepb, yrb), 3)})
    mult, multb = 0.5 + rk, 0.5 + rkb
    r1, r2, r25 = fl.halves(P, res * mult)
    rows.append({"что": "M2 U2 размер 0.5 + ранг", "2018–22": r1, "2023–26": r2, "с 2025": r25, "Bitstamp": round(float((resb * multb).sum()), 1),
                 "ранг Binance": round(fl.placebo_size(res, mult, yr), 3), "ранг Bitstamp": round(fl.placebo_size(resb, multb, yrb), 3)})
    print(pd.DataFrame(rows).to_string(index=False), flush=True)
    print("\nвеса M2 на всём Binance (стандартизованы, + за больший итог):", flush=True)
    print(pd.Series(md.coef_, index=fl.FEATS).sort_values().round(3).to_string(), flush=True)
    q = pd.qcut(pred, 5, labels=False)
    print("\nBinance вне выборки по пятёркам прогноза:", flush=True)
    print(pd.DataFrame({"пятёрка": q, "res": res}).groupby("пятёрка")["res"].agg(["size", "sum", "mean", lambda x: (x > 0).mean() * 100]).round(2).to_string(), flush=True)
    qb = pd.qcut(pb, 5, labels=False)
    print("Bitstamp по пятёркам прогноза:", flush=True)
    print(pd.DataFrame({"пятёрка": qb, "res": resb}).groupby("пятёрка")["res"].agg(["size", "sum", "mean", lambda x: (x > 0).mean() * 100]).round(2).to_string(), flush=True)


if __name__ == "__main__":
    main()
