"""Вторая партия (25.10, оператор: «где платные, остальное — не верю, что больше ничего нет»). Правила до прогона:
стратегии — с параметрами авторов (TradingView, открытый код прочитан 25.10) или публичными правилами:
- KKB «Kinetic Kalman Breakout» (nd8EpyQ5): Калман (шум позиции 0.05, скорости 0.0001, измерения 250), полосы ±2.6 ×
  SMA200 |close−калман|; пересечение верхней — лонг, нижней — шорт, всегда в рынке (переворот). 15m и 1h.
- CBS «Compression Breakout System» (97gxVA5b): ширина Боллинджера 20/2 в нижних 25% за 126 дней за последние 5 баров,
  close > максимума high 20 прошлых баров, объём > SMA20 объёма, close > SMA200 → лонг; выход по close ниже
  max(вход − 2×ATR22, максимум close − 3×ATR22). 1d.
- Capitulation Stretch Reversion (WWuTjyDx): close > EMA200, close < EMA5 − 0.5×ATR14, ≥ 2 падающих закрытия подряд,
  свеча зелёная → лонг; стоп 3×ATR, выход: close ≥ EMA5 или 10 баров. Только лонг (как у автора). 1h и 4h.
- DeMARK TD Sequential (публичные правила; платный DeMARK 9-13 строится на них): завершён «buy setup» 9 (9 закрытий подряд
  ниже close[4]) → лонг; выход: close выше максимума high 9 баров сетапа (TDST) — цель, close ниже минимума low сетапа —
  стоп, иначе 9 баров. «Sell setup» — шорт зеркально. 4h и 1d.
- Принцип Omega «Session Bias» (платный, код закрыт): направление 00:00–14:00 UTC (Азия+Лондон) продолжается в Нью-Йорке:
  вход по open 14:00 UTC в сторону хода с 00:00, выход по open 21:00 UTC. Каждый день. 1h.
Исполнение — open следующего бара, издержки 0.068%/сторона, фандинг. Контроль: только лонг — случайный вход в баре
выше EMA200 (SMA200 для CBS), те же длительности; лонг+шорт — те же моменты и длительности со случайной стороной.
2000 повторов, ранг (k+1)/(n+1). «Есть эдж» — ранг ≤ 0.01 на BTC и ETH и плюс за последние 2 года на обеих."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import run as R  # noqa: E402
import strategies as S  # noqa: E402

REPS = 2000


def bars_v(path):
    d = pd.read_csv(path, usecols=["ts", "open", "high", "low", "close", "volume"])
    d.index = pd.to_datetime(d["ts"], unit="ms")
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    return {tf: d.resample(tf).agg(agg).dropna() for tf in ("15min", "1h", "4h", "1D")}


def kkb(df):
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    n = len(c)
    xp, xv, p00, p01, p10, p11 = c[0], 0.0, 1.0, 0.0, 0.0, 1.0
    kal = np.empty(n)
    for i in range(n):
        pp, vp = xp + xv, xv
        a00, a01, a10, a11 = p00 + p10, p01 + p11, p10, p11
        q00, q01, q10, q11 = a00 + a01 + 0.05, a01, a10 + a11, a11 + 0.0001
        y = c[i] - pp
        s = q00 + 250
        k0, k1 = q00 / s, q10 / s
        xp, xv = pp + k0 * y, vp + k1 * y
        p00, p01, p10, p11 = (1 - k0) * q00, (1 - k0) * q01, -k1 * q00 + q10, -k1 * q01 + q11
        kal[i] = xp
    mae = S.sma(np.abs(c - kal), 200)
    up, lo = kal + 2.6 * mae, kal - 2.6 * mae
    cu = np.r_[False, (c[1:] > up[1:]) & (c[:-1] <= up[:-1])]
    cd = np.r_[False, (c[1:] < lo[1:]) & (c[:-1] >= lo[:-1])]
    ent = np.where(cu, 1, np.where(cd, -1, 0))
    ent[:300] = 0
    return S.trades_from_signals(o, h, l, c, ent), "both"


def cbs(df):
    o, h, l, c, v = (df[k].to_numpy() for k in ("open", "high", "low", "close", "volume"))
    basis = S.sma(c, 20)
    dev = pd.Series(c).rolling(20).std(ddof=0).to_numpy() * 2
    bw = 2 * dev / basis * 100
    rank = pd.Series(bw).rolling(126).apply(lambda w: (w[:-1] <= w[-1]).mean() * 100, raw=True).to_numpy()
    sq = pd.Series((rank < 25).astype(float)).rolling(5).sum().to_numpy() > 0
    brk = pd.Series(h).shift(1).rolling(20).max().to_numpy()
    vok = v > S.sma(v, 20)
    s200 = S.sma(c, 200)
    a = S.atr(h, l, c, 22)
    sig = sq & (c > brk) & vok & (c > s200)
    out, pos = [], None
    for i in range(300, len(c) - 1):
        if pos is not None:
            j, px, est, hwm = pos
            hwm = max(hwm, c[i])
            if c[i] < max(est, hwm - 3 * a[i]):
                out.append((j, i + 1, 1, px, o[i + 1], "сигнал"))
                pos = None
                continue
            pos = (j, px, est, hwm)
        if pos is None and sig[i]:
            pos = (i + 1, o[i + 1], c[i] - 2 * a[i], c[i])
    if pos:
        out.append((pos[0], len(c) - 1, 1, pos[1], c[-1], "конец"))
    return out, "long_sma"


def capstretch(df):
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    mean, trend, a = S.ema(c, 5), S.ema(c, 200), S.atr(h, l, c, 14)
    down = np.zeros(len(c), int)
    for i in range(1, len(c)):
        down[i] = down[i - 1] + 1 if c[i] < c[i - 1] else 0
    sig = (c > trend) & (c < mean - 0.5 * a) & (down >= 2) & (c > o)
    out, pos = [], None
    for i in range(300, len(c) - 1):
        if pos is not None:
            j, px, sl = pos
            if l[i] <= sl and i >= j:
                out.append((j, i, 1, px, min(o[i], sl), "стоп"))
                pos = None
            elif c[i] >= mean[i] or i - j + 1 >= 10:
                out.append((j, i + 1, 1, px, o[i + 1], "сигнал"))
                pos = None
                continue
        if pos is None and sig[i]:
            pos = (i + 1, o[i + 1], c[i] - 3 * a[i])
    return out, "long_ema"


def td_seq(df):
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    n = len(c)
    bs = np.zeros(n, int)
    ss = np.zeros(n, int)
    for i in range(4, n):
        bs[i] = bs[i - 1] + 1 if c[i] < c[i - 4] else 0
        ss[i] = ss[i - 1] + 1 if c[i] > c[i - 4] else 0
    out, pos = [], None
    for i in range(10, n - 1):
        if pos is not None:
            j, side, px, tgt, stp, t0 = pos
            hit_t = c[i] > tgt if side > 0 else c[i] < tgt
            hit_s = c[i] < stp if side > 0 else c[i] > stp
            if hit_t or hit_s or i - t0 >= 9:
                out.append((j, i + 1, side, px, o[i + 1], "сигнал"))
                pos = None
                continue
        if pos is None and (bs[i] == 9 or ss[i] == 9):
            side = 1 if bs[i] == 9 else -1
            hh, ll = h[i - 8:i + 1].max(), l[i - 8:i + 1].min()
            pos = (i + 1, side, o[i + 1], hh if side > 0 else ll, ll if side > 0 else hh, i)
    return out, "both"


def session_bias(df):
    o, c = df["open"].to_numpy(), df["close"].to_numpy()
    idx = df.index
    hr = idx.hour.to_numpy()
    day = idx.normalize().to_numpy()
    out = []
    pos_of = {t: i for i, t in enumerate(idx)}
    for d in np.unique(day):
        i0 = pos_of.get(pd.Timestamp(d))
        i14 = pos_of.get(pd.Timestamp(d) + pd.Timedelta(hours=14))
        i21 = pos_of.get(pd.Timestamp(d) + pd.Timedelta(hours=21))
        if i0 is None or i14 is None or i21 is None:
            continue
        move = c[i14 - 1] / o[i0] - 1
        if move == 0:
            continue
        side = 1 if move > 0 else -1
        out.append((i14, i21, side, o[i14], o[i21], "время"))
    return out, "both"


def controls(df, tr, fund, kind, seed=5):
    o, c = df["open"].to_numpy(), df["close"].to_numpy()
    t = df.index.to_numpy()
    ft, cs = fund
    rng = np.random.default_rng(seed)
    if kind == "both":
        g = tr["gross"].to_numpy()
        side = tr["side"].to_numpy()
        f = (tr["gross"] - tr["net"] - 2 * S.COST).to_numpy() * side       # side·fsum
        res = np.empty(REPS)
        for r in range(REPS):
            s = rng.choice([-1, 1], size=len(g))
            res[r] = (s * side * g - 2 * S.COST - s * side * f).mean()     # та же цена, случайная сторона
        return res
    trend = S.sma(c, 200) if kind == "long_sma" else S.ema(c, 200)
    ok = np.flatnonzero(c > trend)
    ok = ok[(ok > 300) & (ok < len(o) - 30)]
    durs = tr["bars"].to_numpy()
    res = np.empty(REPS)
    for r in range(REPS):
        j = rng.choice(ok, size=len(durs)) + 1
        k = np.minimum(j + durs, len(o) - 1)
        fs = cs[np.searchsorted(ft, t[k])] - cs[np.searchsorted(ft, t[j])]
        res[r] = (o[k] / o[j] - 1 - 2 * S.COST - fs).mean()
    return res


def main():
    jobs = [("KKB (Калман)", kkb, ["15min", "1h"]), ("CBS (сжатие+пробой)", cbs, ["1D"]),
            ("Capitulation Stretch", capstretch, ["1h", "4h"]), ("DeMARK TD Setup 9", td_seq, ["4h", "1D"]),
            ("Session Bias (принцип Omega)", session_bias, ["1h"])]
    for sym, path in (("BTCUSDT", sys.argv[1]), ("ETHUSDT", sys.argv[2])):
        bb = bars_v(path)
        fund = R.funding(sym)
        print(f"== {sym}", flush=True)
        for name, fn, tfs in jobs:
            for tf in tfs:
                df = bb[tf]
                raw, kind = fn(df)
                tr = R.evaluate(df, raw, fund)
                if len(tr) < 5:
                    print(f"   {name:<28} {tf:>5}: сделок {len(tr)}")
                    continue
                m, lo, hi = R.ci(tr["net"].to_numpy())
                ctl = controls(df, tr, fund, kind)
                fr = tr[tr["t"] >= R.FRESH]["net"]
                h1, h2 = tr[tr["t"] < R.SPLIT]["net"].sum(), tr[tr["t"] >= R.SPLIT]["net"].sum()
                print(f"   {name:<28} {tf:>5}: n {len(tr):>5} net {100 * m:+.3f}% [{100 * lo:+.3f}…{100 * hi:+.3f}] "
                      f"до изд. {100 * tr['gross'].mean():+.3f}% | половины {100 * h1:+.0f}/{100 * h2:+.0f}% 2г "
                      f"{100 * fr.sum():+.0f}% (n {len(fr)}) | контроль ({'случ. сторона' if kind == 'both' else 'случ. выше тренда'}) "
                      f"медиана {100 * np.median(ctl):+.3f}% ранг {(1 + int((ctl >= m).sum())) / (REPS + 1):.4f}", flush=True)


if __name__ == "__main__":
    main()
