"""Признаки на барах 4ч: только закрытые данные, значение на баре j известно в момент его закрытия.
Дневные и внешние ряды сдвигаются на момент публикации в asof_daily."""
from __future__ import annotations

import numpy as np
import pandas as pd

import lab_core as lc


def _roll_max(x, n):
    return pd.Series(x).rolling(n, min_periods=n).max().to_numpy()


def _roll_min(x, n):
    return pd.Series(x).rolling(n, min_periods=n).min().to_numpy()


def adx(S, n=14):
    """ADX и +DI/−DI как ta.dmi: RMA."""
    key = ("adx", n)
    if key in S.cache:
        return S.cache[key]
    h, l, c = S.h4["h"], S.h4["l"], S.h4["c"]
    up = np.r_[0.0, h[1:] - h[:-1]]
    dn = np.r_[0.0, l[:-1] - l[1:]]
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr = lc.rma(tr, n)
    with np.errstate(invalid="ignore", divide="ignore"):
        pdi = 100 * lc.rma(pdm, n) / atr
        mdi = 100 * lc.rma(mdm, n) / atr
        dx = 100 * np.abs(pdi - mdi) / (pdi + mdi)
    out = (lc.rma(np.where(np.isfinite(dx), dx, np.nan), n), pdi, mdi)
    S.cache[key] = out
    return out


def er(c, n):
    d = np.abs(np.diff(c, prepend=c[0]))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.abs(c - np.r_[np.full(n, np.nan), c[:-n]]) / pd.Series(d).rolling(n).sum().to_numpy()


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    up, dn = lc.rma(np.maximum(d, 0.0), n), lc.rma(np.maximum(-d, 0.0), n)
    with np.errstate(invalid="ignore", divide="ignore"):
        return 100 - 100 / (1 + up / dn)


def crosses(c, ln, n):
    s = np.sign(c - ln)
    ch = np.r_[0, (s[1:] != s[:-1]).astype(int)]
    return pd.Series(ch).rolling(n, min_periods=n).sum().to_numpy()


def rank(x, n):
    """Доля прошлых n значений ниже текущего."""
    x = np.asarray(x, float)
    return pd.Series(x).rolling(n + 1, min_periods=n // 2).apply(lambda w: np.mean(w[:-1] < w[-1]) if np.isfinite(w[-1]) else np.nan, raw=True).to_numpy()


def daily_close_series(S):
    """Дневные закрытия UTC: день известен с его конца. Индекс — момент известности, сек."""
    t = S.t
    day = (t - 1) // 86400
    c = pd.Series(S.c).groupby(day).last()
    known = (c.index.to_numpy() + 1) * 86400
    return pd.Series(c.to_numpy(), index=known)


def asof_h4(S, known, vals):
    """Значение внешнего ряда с моментом публикации known на каждом закрытом баре 4ч: known ≤ закрытие бара."""
    k4 = S.h4["known"]
    idx = np.searchsorted(known, k4, side="right") - 1
    out = np.full(len(k4), np.nan)
    ok = idx >= 0
    out[ok] = np.asarray(vals, float)[idx[ok]]
    return out


def feats(S):
    """Словарь признаков на барах 4ч, без знака стороны. Знак добавляет signed()."""
    if "feats" in S.cache:
        return S.cache["feats"]
    c, h, l, o, v = S.h4["c"], S.h4["h"], S.h4["l"], S.h4["o"], S.h4["v"]
    G, Y, R, B = S.line4(lc.G), S.line4(lc.Y), S.line4(lc.R), S.line4(lc.B)
    A = S.atr4()
    F = {}
    for nm, ln in (("G", G), ("Y", Y), ("R", R), ("B", B)):
        F[f"d_{nm}"] = (c - ln) / A
        for k in (1, 6, 30):
            F[f"sl{k}_{nm}"] = (ln - np.r_[np.full(k, np.nan), ln[:-k]]) / A
    F["w_GYR"] = (np.maximum(np.maximum(G, Y), R) - np.minimum(np.minimum(G, Y), R)) / A
    F["w_GB"] = np.abs(G - B) / A
    F["stack"] = np.where((G > Y) & (Y > R), 1.0, np.where((G < Y) & (Y < R), -1.0, 0.0))
    a14, p14, m14 = adx(S, 14)
    a3, p3, m3 = adx(S, 3)
    F["adx14"], F["adx3"], F["di14"], F["di3"] = a14, a3, p14 - m14, p3 - m3
    for n in (6, 30, 90):
        F[f"er{n}"] = er(c, n)
    for n in (1, 6, 30, 90, 180):
        F[f"ret{n}"] = (c / np.r_[np.full(n, np.nan), c[:-n]] - 1) / (A / c)
    for n in (30, 90, 180, 540):
        hh, ll = _roll_max(h, n), _roll_min(l, n)
        F[f"pos{n}"] = (c - ll) / (hh - ll)
        F[f"newhi{n}"] = (c >= np.r_[np.nan, _roll_max(c, n)[:-1]]).astype(float)
        F[f"newlo{n}"] = (c <= np.r_[np.nan, _roll_min(c, n)[:-1]]).astype(float)
    F["rsi14"] = rsi(c, 14)
    F["atrp"] = A / c * 100
    F["atr_rank"] = rank(A / c, 1080)
    F["atr_ratio"] = A / lc.rma(np.where(np.isfinite(A), A, np.nan), 100)
    rng = np.maximum(h - l, 1e-12)
    F["body"] = (c - o) / rng
    F["clv"] = (c - l) / rng
    F["rng_atr"] = (h - l) / A
    F["vol30"] = v / pd.Series(v).rolling(180, min_periods=60).median().to_numpy()
    for n in (30, 60, 120):
        F[f"xG{n}"] = crosses(c, G, n)
    F["xB60"] = crosses(c, B, 60)
    dc = daily_close_series(S)
    known = dc.index.to_numpy()
    dv = dc.to_numpy()
    for n in (20, 50, 100, 200):
        F[f"d_sma{n}"] = asof_h4(S, known, dv / lc.sma(dv, n) - 1)
        F[f"d_ema{n}"] = asof_h4(S, known, dv / lc.ema(dv, n) - 1)
    k4 = S.h4["known"]
    F["hour"] = (k4 % 86400 / 3600).astype(float)
    F["wday"] = ((k4 // 86400 + 4) % 7).astype(float)
    if "tb" in S.h4:
        with np.errstate(invalid="ignore", divide="ignore"):
            r = S.h4["tb"] / v
        F["taker"] = r
        F["taker6"] = pd.Series(r).rolling(6).mean().to_numpy()
    fr = S.fund_rate
    if len(fr) > 2:
        kk = fr.index.to_numpy(np.int64)
        rate = fr.to_numpy(float)
        F["fund"] = asof_h4(S, kk, rate) * 100
        F["fund9"] = asof_h4(S, kk, pd.Series(rate).rolling(9).mean().to_numpy()) * 100
    S.cache["feats"] = F
    return F


SIGNED = {"d_G", "d_Y", "d_R", "d_B", "sl1_G", "sl6_G", "sl30_G", "sl1_Y", "sl6_Y", "sl30_Y", "sl1_R", "sl6_R", "sl30_R", "sl1_B", "sl6_B", "sl30_B", "stack", "di14", "di3", "ret1", "ret6", "ret30", "ret90", "ret180",
          "body", "d_sma20", "d_sma50", "d_sma100", "d_sma200", "d_ema20", "d_ema50", "d_ema100", "d_ema200", "fund", "fund9"}


def signed_row(F, j, s):
    """Признаки в момент бара j со знаком стороны: + значит «в пользу сделки»."""
    out = {}
    for k, v in F.items():
        x = v[j]
        if k in SIGNED:
            x = s * x
        elif k in ("rsi14", "clv", "pos30", "pos90", "pos180", "pos540", "taker", "taker6"):
            x = (x - (50 if k == "rsi14" else 0.5)) * s
        elif k.startswith("newhi"):
            n = k[5:]
            x = F[("newhi" if s == 1 else "newlo") + n][j]
        elif k.startswith("newlo"):
            continue
        out[k] = x
    return out
