"""Проверка единственного выжившего кандидата — TRADLEWARE Gaussian Channel + StochRSI, 4h, только лонг (25.10).
Правила проверки до прогона:
1. контроль, СОВПАДАЮЩИЙ ПО РЕЖИМУ: случайные входы только в барах, где close > SMA200 (как у стратегии), те же
   длительности, 2000 повторов, ранг (k+1)/(n+1) — иначе «эдж» может быть просто ростом рынка выше SMA200;
2. соседи 27 ячеек: период 60/89/120 × множитель 1.2/1.5/2.0 × полюса 3/4/5 — плоская поверхность или пик;
3. разбор условий: без StochRSI, без SMA200, без зелёной свечи, только «канал растёт и close > полосы»;
4. издержки ×2; по годам; XRP (2 года frozen) — монета, на которой автор не подбирал;
вердикт «есть эдж» — только если 1) ранг ≤ 0.01 на BTC и ETH, 2) ≥ 2/3 соседей в плюсе на обеих монетах, 3) плюс при
издержках ×2, 4) последние 2 года в плюсе. Иначе — «нет» с цифрой."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import run as R  # noqa: E402
import strategies as S  # noqa: E402


def gc(b, N=4, per=89, mult=1.5, use_stoch=True, use_sma=True, use_green=True):
    """Как strategies.gaussian_channel, с выключателями условий (для разбора)."""
    import math
    o, h, l, c = b
    src = (h + l + c) / 3
    beta = (1 - math.cos(4 * math.asin(1) / per)) / (math.pow(1.414, 2 / N) - 1)
    alpha = -beta + math.sqrt(beta * beta + 2 * beta)
    x = 1 - alpha
    coef = [math.comb(N, k) for k in range(N + 1)]

    def filt(s):
        f = np.zeros(len(s))
        for i in range(len(s)):
            v = alpha ** N * (0 if np.isnan(s[i]) else s[i])
            for k in range(1, N + 1):
                if i - k >= 0:
                    v += (-1) ** (k + 1) * coef[k] * x ** k * f[i - k]
            f[i] = v
        return f
    fl, ftr = filt(src), filt(np.nan_to_num(S.tr(h, l, c)))
    hb, lb = fl + ftr * mult, fl - ftr * mult
    r = S.rsi(c, 14)
    lo, hi = pd.Series(r).rolling(14).min().to_numpy(), pd.Series(r).rolling(14).max().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        k = S.sma(100 * (r - lo) / (hi - lo), 3)
    s200 = S.sma(c, 200)
    green = np.r_[False, fl[1:] > fl[:-1]]
    cond = green & (c > hb)
    if use_stoch:
        cond &= (k > 80) | (k < 25)
    if use_sma:
        cond &= c > s200
    if use_green:
        cond &= c > o
    ent = np.where(cond, 1, 0)
    ent[:300] = 0
    ex = (c < hb) | ~green
    return S.trades_from_signals(o, h, l, c, ent, exits=ex, stops=lambda i, s, px: (lb, None))


def matched_control(df, tr, fund, reps=2000, seed=7):
    o, c = df["open"].to_numpy(), df["close"].to_numpy()
    s200 = S.sma(c, 200)
    t = df.index.to_numpy()
    ft, cs = fund
    ok = np.flatnonzero(c > s200)                          # бары-сигналы «выше SMA200»
    ok = ok[(ok > 300) & (ok < len(o) - 2)]
    rng = np.random.default_rng(seed)
    durs = tr["bars"].to_numpy()
    out = np.empty(reps)
    for r in range(reps):
        tot = 0.0
        for d in durs:
            j = int(rng.choice(ok)) + 1                    # вход по open следующего бара, как у стратегии
            k = min(j + d, len(o) - 1)
            f = cs[np.searchsorted(ft, t[k])] - cs[np.searchsorted(ft, t[j])]
            tot += o[k] / o[j] - 1 - 2 * S.COST - f
        out[r] = tot / len(durs)
    return out


def summary(df, tr):
    m = tr["net"].mean()
    fr = tr[tr["t"] >= R.FRESH]["net"]
    h1, h2 = tr[tr["t"] < R.SPLIT]["net"].sum(), tr[tr["t"] >= R.SPLIT]["net"].sum()
    return m, len(tr), h1, h2, fr.sum(), len(fr)


def main():
    files = {"BTCUSDT": sys.argv[1], "ETHUSDT": sys.argv[2]}
    if len(sys.argv) > 3:
        files["XRPUSDT"] = sys.argv[3]
    for sym, path in files.items():
        df = R.bars(path)["4h"]
        fund = R.funding(sym)
        b = tuple(df[k].to_numpy() for k in ("open", "high", "low", "close"))
        tr = R.evaluate(df, gc(b), fund)
        m, n, h1, h2, f2, nf = summary(df, tr)
        print(f"== {sym} 4h: {df.index[0].date()} … {df.index[-1].date()}; сделок {n}, net {100 * m:+.3f}%/сделку, "
              f"половины {100 * h1:+.0f}% / {100 * h2:+.0f}%, 2 года {100 * f2:+.0f}% (n {nf})", flush=True)
        if sym != "XRPUSDT":
            ctl = matched_control(df, tr, fund)
            print(f"   контроль по режиму (случайный вход выше SMA200, те же длительности, 2000): медиана "
                  f"{100 * np.median(ctl):+.3f}%, 95% {100 * np.quantile(ctl, .95):+.3f}%, ранг "
                  f"{(1 + int((ctl >= m).sum())) / 2001:.4f}", flush=True)
            c2 = tr["gross"] - 4 * S.COST - (tr["gross"] - tr["net"] - 2 * S.COST)
            print(f"   издержки ×2: net {100 * c2.mean():+.3f}%/сделку, сумма {100 * c2.sum():+.0f}%", flush=True)
            yr = tr.groupby(pd.to_datetime(tr["t"]).dt.year)["net"].agg(["count", "sum"])
            print("   по годам: " + ", ".join(f"{y} {100 * s:+.0f}% (n {int(k)})" for y, (k, s) in yr.iterrows()), flush=True)
            for name, kw in (("без StochRSI", {"use_stoch": False}), ("без SMA200", {"use_sma": False}),
                             ("без зелёной свечи", {"use_green": False}),
                             ("только канал + пробой", {"use_stoch": False, "use_sma": False, "use_green": False})):
                t2 = R.evaluate(df, gc(b, **kw), fund)
                mm, nn, a1, a2, ff, nff = summary(df, t2)
                print(f"   разбор {name}: n {nn}, net {100 * mm:+.3f}%, половины {100 * a1:+.0f}/{100 * a2:+.0f}%, "
                      f"2г {100 * ff:+.0f}%", flush=True)
            cells = []
            for per in (60, 89, 120):
                for mult in (1.2, 1.5, 2.0):
                    for N in (3, 4, 5):
                        t3 = R.evaluate(df, gc(b, N=N, per=per, mult=mult), fund)
                        mm, nn, a1, a2, ff, nff = summary(df, t3)
                        cells.append((per, mult, N, mm, nn, a1, a2, ff))
            pos = sum(1 for x in cells if x[3] > 0)
            both = sum(1 for x in cells if x[5] > 0 and x[6] > 0)
            print(f"   соседи 27: в плюсе {pos}, обе половины в плюсе {both}, 2г в плюсе {sum(1 for x in cells if x[7] > 0)}; "
                  f"net/сделку от {100 * min(x[3] for x in cells):+.3f}% до {100 * max(x[3] for x in cells):+.3f}%", flush=True)
            for x in cells:
                print(f"      период {x[0]:>3} × {x[1]:.1f} × {x[2]} полюса: n {x[4]:>3} net {100 * x[3]:+.3f}% "
                      f"половины {100 * x[5]:+.0f}/{100 * x[6]:+.0f} 2г {100 * x[7]:+.0f}")


if __name__ == "__main__":
    main()
