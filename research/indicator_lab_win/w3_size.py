"""W3: постоянный риск против постоянных $1000, попытка опровергнуть. Сделки те же, меняется только вес.
1. По годам. 2. Вес от скользящей медианы (нет сдвига уровня во времени). 3. Контроль: те же веса случайно по сделкам. 4. Корзины волатильности. 5. Пик номинала.
Запуск: python -X utf8 w3_size.py"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import lab_core as lc
import lab_sweep as ls

OUT = Path(__file__).parent / "out"
pd.set_option("display.width", 240, "display.max_columns", 40, "display.max_rows", 200)


def w_expanding(S, n, lo, hi):
    return ls.vol_weights(S, lo, hi, n)


def w_rolling(S, n, lo, hi, days=365):
    A = S.atr4(n)
    p = A / S.h4["c"]
    med = pd.Series(p).rolling(days * 6, min_periods=500).median().shift(1).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        w = np.clip(med / p, lo, hi)
    return np.where(np.isfinite(w), w, 1.0)


def w_static(S, n, lo, hi, target):
    A = S.atr4(n)
    p = A / S.h4["c"] * 100
    with np.errstate(invalid="ignore", divide="ignore"):
        w = np.clip(target / p, lo, hi)
    return np.where(np.isfinite(w), w, 1.0)


def with_w(S, w, **kw):
    legs = lc.run(S, w_fn=w, **kw)
    m = np.mean([x[5] for x in legs])
    return [(*x[:5], x[5] / m, *x[6:]) for x in legs], m


def by_year(S, legs):
    r = lc.nets(S, legs)
    y = pd.to_datetime(S.t[[x[0] for x in legs]], unit="s").year
    return pd.Series(r).groupby(y).sum().round(1)


def peak_notional(S, legs):
    n = np.zeros(len(S.t) + 1)
    for x in legs:
        n[x[0]] += x[5]
        n[x[1]] -= x[5]
    return float(np.cumsum(n).max())


def shuffle_control(S, legs, reps=2000, seed=7):
    base = [x[5] for x in legs]
    rng = np.random.default_rng(seed)
    a = np.array([x[:5] for x in legs], dtype=float)
    i0, i1 = a[:, 0].astype(int), a[:, 1].astype(int)
    p0, p1, s = a[:, 2], a[:, 3], a[:, 4]
    unit = (s * (p1 / p0 - 1) - lc.SIDE_COST - lc.SIDE_COST * p1 / p0 - s * (S.fm[i1] - S.fm[i0]) / p0) * 100
    real = float((unit * np.array(base)).sum())
    w = np.array(base)
    ctl = np.array([float((unit * rng.permutation(w)).sum()) for _ in range(reps)])
    return real, float(np.median(ctl)), float((ctl < real).mean() * 100), float(np.quantile(ctl, .95))


def main():
    for name in ("BTC", "ETH", "XRP", "Bitstamp"):
        S = lc.load(name)
        base = lc.run(S)
        st0 = lc.stats(S, base)
        print(f"\n===== {name} база: итог {st0['итог']} просадка {st0['просадка']} отн {st0['отн']} с2025 {st0['с2025']}")
        A = S.atr4()
        p = A / S.h4["c"] * 100
        target = float(np.nanmedian(p[S.j[S.i0]:]))
        print("медиана ATR% за период", round(target, 2))
        cfg = {"расширяющаяся медиана ATR14, 0.25-3": w_expanding(S, 14, 0.25, 3), "расширяющаяся ATR100, 0.25-3": w_expanding(S, 100, 0.25, 3), "расширяющаяся ATR14, 0.25-2": w_expanding(S, 14, 0.25, 2), "расширяющаяся ATR100, 0.25-2": w_expanding(S, 100, 0.25, 2),
               "скользящая год ATR14, 0.25-3": w_rolling(S, 14, 0.25, 3), "скользящая год ATR100, 0.25-3": w_rolling(S, 100, 0.25, 3), "скользящая год ATR14, 0.5-2": w_rolling(S, 14, 0.5, 2), "скользящая год ATR100, 0.5-2": w_rolling(S, 100, 0.5, 2), "постоянная цель, ATR14, 0.25-3": w_static(S, 14, 0.25, 3, target), "постоянная цель ATR100, 0.25-3": w_static(S, 100, 0.25, 3, target)}
        rows = []
        for lab, w in cfg.items():
            legs, m = with_w(S, w)
            st = lc.stats(S, legs)
            wv = np.array([x[5] for x in legs])
            real, med, better, q95 = shuffle_control(S, legs)
            rows.append({"вес": lab, "итог": st["итог"], "просадка": st["просадка"], "отн": st["отн"], "с2025": st["с2025"], "p1": st["p1"], "p2": st["p2"], "p3": st["p3"], "макс_вес": round(float(wv.max()), 2), "мин": round(float(wv.min()), 2), "пик_номинала": round(peak_notional(S, legs), 2), "случайно_медиана": round(med, 1), "лучше_случ_%": round(better, 1)})
        print(pd.DataFrame(rows).to_string(index=False))
        legs, _ = with_w(S, w_rolling(S, 100, 0.25, 3))
        print("годы, база:", by_year(S, base).to_dict())
        print("годы, вес :", by_year(S, legs).to_dict())
        a = np.array([x[:5] for x in base], dtype=float)
        r = lc.nets(S, base)
        i0 = a[:, 0].astype(int)
        ap = p[S.j[i0]]
        rk = pd.Series(p).rolling(365 * 6, min_periods=500).rank(pct=True).to_numpy()[S.j[i0]]
        side = a[:, 4]
        d = pd.DataFrame({"r": r, "ap": ap, "rk": rk, "s": side})
        d["r_atr"] = d["r"] / d["ap"]
        d["корзина"] = pd.cut(d["rk"], [0, 1 / 3, 2 / 3, 1.01], labels=["низкая", "средняя", "высокая"])
        print(d.groupby(["s", "корзина"], observed=True).agg(n=("r", "size"), итог=("r", "sum"), среднее=("r", "mean"), в_ATR=("r_atr", "mean"), плюс=("r", lambda x: (x > 0).mean() * 100)).round(2).to_string())
        print("корреляция r и ATR% на входе:", round(float(np.corrcoef(d["r"], d["ap"])[0, 1]), 3), " |r| и ATR%:", round(float(np.corrcoef(d["r"].abs(), d["ap"])[0, 1]), 3))


if __name__ == "__main__":
    main()
