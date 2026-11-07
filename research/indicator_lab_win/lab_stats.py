"""Поправка на перебор: CSCV/PBO, Deflated Sharpe, White Reality Check, скользящий выбор по годам. Матрицы дневных изменений из lab_sweep.py.
Запуск: python -X utf8 lab_stats.py"""
from __future__ import annotations

import itertools
import math
from pathlib import Path

import numpy as np
import pandas as pd

import lab_core as lc

OUT = Path(__file__).parent / "out"
pd.set_option("display.width", 250, "display.max_columns", 40, "display.max_rows", 400, "display.max_colwidth", 50)


def sharpe(M):
    s = M.std(axis=-1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(s > 0, M.mean(axis=-1) / s, np.nan)


def cscv(M, blocks=16, reps=3000, seed=11):
    """PBO: IS выбирает лучший, смотрим его ранг на OOS. M: варианты × дни."""
    n = M.shape[1]
    edges = np.linspace(0, n, blocks + 1).astype(int)
    means = np.stack([M[:, edges[k]:edges[k + 1]].mean(axis=1) for k in range(blocks)], axis=1)
    var = np.stack([M[:, edges[k]:edges[k + 1]].var(axis=1) for k in range(blocks)], axis=1)
    rng = np.random.default_rng(seed)
    combos = list(itertools.combinations(range(blocks), blocks // 2))
    pick = rng.choice(len(combos), size=min(reps, len(combos)), replace=False)
    lam, deg = [], []
    for q in pick:
        a = np.array(combos[q])
        b = np.setdiff1d(np.arange(blocks), a)
        sr_is = means[:, a].mean(axis=1) / np.sqrt(var[:, a].mean(axis=1) + 1e-12)
        sr_oos = means[:, b].mean(axis=1) / np.sqrt(var[:, b].mean(axis=1) + 1e-12)
        k = int(np.nanargmax(sr_is))
        w = (sr_oos < sr_oos[k]).mean()
        w = min(max(w, 1 / (len(sr_oos) + 1)), len(sr_oos) / (len(sr_oos) + 1))
        lam.append(math.log(w / (1 - w)))
        deg.append((sr_is[k], sr_oos[k]))
    lam, deg = np.array(lam), np.array(deg)
    return {"PBO": float((lam <= 0).mean()), "медиана логита": float(np.median(lam)), "IS Sharpe, год": float(deg[:, 0].mean() * np.sqrt(365)), "OOS Sharpe, год": float(deg[:, 1].mean() * np.sqrt(365)), "OOS плюс, доля": float((deg[:, 1] > 0).mean())}


def dsr(r, sr_trials):
    """Deflated Sharpe: вероятность, что Sharpe выше ожидаемого максимума из N попыток."""
    from scipy.stats import norm, kurtosis, skew
    r = np.asarray(r, float)
    T_ = len(r)
    sr = r.mean() / r.std()
    N = len(sr_trials)
    v = np.nanvar(sr_trials)
    em = np.euler_gamma
    sr0 = np.sqrt(v) * ((1 - em) * norm.ppf(1 - 1 / N) + em * norm.ppf(1 - 1 / (N * np.e)))
    g3, g4 = skew(r), kurtosis(r, fisher=False)
    z = (sr - sr0) * np.sqrt(T_ - 1) / np.sqrt(1 - g3 * sr + (g4 - 1) / 4 * sr ** 2)
    return {"Sharpe дневной": float(sr), "Sharpe год": float(sr * np.sqrt(365)), "порог перебора, год": float(sr0 * np.sqrt(365)), "DSR": float(norm.cdf(z))}


def stationary_idx(n, block, rng):
    p = 1 / block
    idx = np.zeros(n, dtype=np.int64)
    idx[0] = rng.integers(n)
    jumps = rng.random(n) < p
    starts = rng.integers(n, size=n)
    for i in range(1, n):
        idx[i] = starts[i] if jumps[i] else (idx[i - 1] + 1) % n
    return idx


def reality_check(M, b0, reps=1500, block=30, seed=5):
    """White Reality Check: лучший из вариантов против базы с поправкой на перебор."""
    D = M - M[b0]
    keep = np.flatnonzero(D.std(axis=1) > 0)
    D = D[keep]
    n = D.shape[1]
    mu = D.mean(axis=1)
    stat = np.sqrt(n) * mu.max()
    rng = np.random.default_rng(seed)
    cs = np.cumsum(np.c_[np.zeros(D.shape[0]), D], axis=1)
    cnt = 0
    for _ in range(reps):
        idx = stationary_idx(n, block, rng)
        m = D[:, idx].mean(axis=1)
        if np.sqrt(n) * (m - mu).max() >= stat:
            cnt += 1
    return {"лучший против базы, за год %": float(mu.max() * 365), "p Reality Check": (cnt + 1) / (reps + 1), "вариантов": len(keep), "лучший": int(keep[int(np.argmax(mu))])}


def walk(M, days, d, b0, start_year=2021, min_days=730):
    """Каждый год выбирается лучший Sharpe по всему прошлому, торгует следующий год. Сравнение с базой в тех же годах."""
    yrs = pd.DatetimeIndex(days).year.to_numpy()
    rows = []
    tot, totb = np.zeros(0), np.zeros(0)
    for y in sorted(set(yrs)):
        if y < start_year:
            continue
        tr, te = yrs < y, yrs == y
        if tr.sum() < min_days:
            continue
        s = sharpe(M[:, tr])
        k = int(np.nanargmax(s))
        rows.append({"год": y, "выбран": d["вариант"].iloc[k], "семейство": d["семейство"].iloc[k], "прошлый Sharpe": round(float(s[k] * np.sqrt(365)), 2), "итог": round(float(M[k, te].sum()), 1), "база": round(float(M[b0, te].sum()), 1)})
        tot = np.r_[tot, M[k, te]]
        totb = np.r_[totb, M[b0, te]]
    t = pd.DataFrame(rows)
    return t, float(tot.sum()), float(totb.sum()), lc.max_dd(np.cumsum(tot)), lc.max_dd(np.cumsum(totb))


def days_of(name):
    S = lc.load(name)
    d = pd.Series(1.0, index=pd.to_datetime(S.t, unit="s"))
    d = d[d.index >= pd.Timestamp(int(S.t[S.i0]), unit="s")]
    return d.resample("1D").last().index[1:]


def main():
    d = pd.read_csv(OUT / "sweep_BTC_ETH_XRP.csv")
    b0 = int(d.index[d["вариант"] == "база R"][0])
    for nm in ("BTC", "ETH", "XRP"):
        M = np.load(OUT / f"sweep_daily_{nm}.npy").astype(np.float64)
        days = days_of(nm)
        print(f"\n===== {nm}: матрица {M.shape}, дней по датам {len(days)}")
        ok = M.std(axis=1) > 0
        print("CSCV все варианты:", cscv(M[ok]))
        for fam in ("А", "Б", "Д", "Ж-размер"):
            m = (d["семейство"] == fam).to_numpy() & ok
            if m.sum() >= 6:
                print("  CSCV", fam, m.sum(), cscv(M[m]))
        rc = reality_check(M, b0)
        print("Reality Check:", rc, d["вариант"].iloc[rc["лучший"]])
        tt = sharpe(M[ok])
        print("Deflated Sharpe, база:", dsr(M[b0], tt))
        for lab in ("риск 0.25-3 ATR100", "риск 0.25-2 ATR100", "риск 0.25-2 ATR14", "atr_rank<=0.6 шорт", "пауза 12", "d_G>=2 шорт", "только лонг"):
            k = int(d.index[d["вариант"] == lab][0])
            print("  ", lab, dsr(M[k], tt), "разница с базой за год", round(float((M[k] - M[b0]).mean() * 365), 1))
        days = days[-M.shape[1]:]
        t, a, b, da, db = walk(M, days, d, b0)
        print("Скользящий выбор, все семейства:\n", t.to_string(index=False))
        print(f"итог выбора {a:.1f} просадка {da:.1f}; база {b:.1f} просадка {db:.1f}")
        for fam in ("Д", "Ж-размер", "Г", "В-время", "В-плавающий", "А", "Б"):
            m = (d["семейство"] == fam).to_numpy() | (d["вариант"] == "база R").to_numpy()
            idx = np.flatnonzero(m)
            t2, a2, b2, da2, db2 = walk(M[idx], days, d.iloc[idx].reset_index(drop=True), int(np.flatnonzero(idx == b0)[0]))
            print(f"  только {fam} + база: итог {a2:.1f} просадка {da2:.1f}; база {b2:.1f} просадка {db2:.1f}; выбраны {t2['выбран'].tolist()}")


if __name__ == "__main__":
    main()
