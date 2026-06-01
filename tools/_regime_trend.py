"""Regime-gated TREND-FOLLOWING on BTC 4h (operator's spec 2026-06-01).

Classic trend strategy + market-regime detection: trade trend-continuation
breakouts ONLY when the market is TRENDING (ADX high) and ONLY in the trend
direction (EMA). Exit by ATR trailing stop (Chandelier). Real fee 0.15% rt.

  regime: Wilder ADX(14) on 4h >= ADX_TH  -> trending
  direction: EMA(EMA_N) slope (close>ema & ema rising = up)
  entry: Donchian(L) breakout in trend dir, only when trending
         (up: close > highest(high,L)[1] ; down: close < lowest(low,L)[1])
  exit: chandelier ATR trail (long: exit if close < runmax - M*ATR), or opposite.
Sweeps ADX_TH / L / M, reports per-year (must be + every year, PF>=1.3).
"""
import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
FEE = float(os.getenv("FEE", "0.15"))


def load(pair):
    df = pd.read_csv(ROOT / "backtests" / "frozen" / f"{pair}_1m_2y.csv")
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return (df.set_index("ts").resample("4h").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna())


def wilder(s, n):
    return s.ewm(alpha=1/n, adjust=False).mean()


def adx(o, n=14):
    h, l, c = o["high"], o["low"], o["close"]
    up = h.diff(); dn = -l.diff()
    plus = ((up > dn) & (up > 0)) * up
    minus = ((dn > up) & (dn > 0)) * dn
    pc = c.shift(1)
    tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    atr = wilder(tr, n)
    pdi = 100*wilder(plus, n)/atr
    mdi = 100*wilder(minus, n)/atr
    dx = 100*(pdi-mdi).abs()/(pdi+mdi).replace(0, np.nan)
    return wilder(dx.fillna(0), n), atr


def backtest(o, ADX_TH, L, M, EMA_N=50, fee=FEE, vol_filt=False, atr_filt=False):
    a, atr = adx(o, 14)
    atr_pct = (atr / o["close"]).to_numpy(float)
    atr_med = pd.Series(atr_pct).rolling(100).median().to_numpy()
    ema = o["close"].ewm(span=EMA_N, adjust=False).mean()
    ema_up = ema > ema.shift(3)
    don_hi = o["high"].rolling(L).max().shift(1)
    don_lo = o["low"].rolling(L).min().shift(1)
    vma = o["volume"].rolling(20).mean()
    h, l, c = o["high"].to_numpy(float), o["low"].to_numpy(float), o["close"].to_numpy(float)
    A = a.to_numpy(float); AT = atr.to_numpy(float); EU = ema_up.to_numpy()
    EM = ema.to_numpy(float); DH = don_hi.to_numpy(float); DL = don_lo.to_numpy(float)
    V = o["volume"].to_numpy(float); VM = vma.to_numpy(float); idx = o.index
    pos = 0; entry = 0.0; runext = 0.0; ent_ts = None; trades = []

    def closep(px, ts):
        nonlocal pos
        g = (px-entry)/entry if pos == 1 else (entry-px)/entry
        trades.append((str(ts)[:4], pos, g*100 - fee))
        pos = 0

    for i in range(max(L, EMA_N)+2, len(o)):
        if not np.isfinite(AT[i]) or not np.isfinite(A[i]):
            continue
        # manage open position — chandelier ATR trail
        if pos == 1:
            runext = max(runext, h[i])
            if c[i] < runext - M*AT[i]:
                closep(c[i], idx[i])
        elif pos == -1:
            runext = min(runext, l[i])
            if c[i] > runext + M*AT[i]:
                closep(c[i], idx[i])
        # entries (only when trending + aligned)
        if pos == 0 and A[i] >= ADX_TH:
            up = c[i] > EM[i] and bool(EU[i])
            dn = c[i] < EM[i] and not bool(EU[i])
            long_brk = up and np.isfinite(DH[i]) and c[i] > DH[i]
            short_brk = dn and np.isfinite(DL[i]) and c[i] < DL[i]
            if vol_filt and np.isfinite(VM[i]) and V[i] < VM[i]:
                long_brk = short_brk = False
            if atr_filt and np.isfinite(atr_med[i]) and atr_pct[i] < atr_med[i]:
                long_brk = short_brk = False
            if long_brk:
                pos = 1; entry = c[i]; runext = h[i]; ent_ts = idx[i]
            elif short_brk:
                pos = -1; entry = c[i]; runext = l[i]; ent_ts = idx[i]
    return trades


def metr(trades):
    if len(trades) < 5:
        return None
    r = np.array([t[2] for t in trades])/100
    eq = np.cumprod(1+r); net = (eq[-1]-1)*100
    dd = ((eq-np.maximum.accumulate(eq))/np.maximum.accumulate(eq)).min()*100
    gw = r[r > 0].sum(); gl = -r[r < 0].sum()
    pf = gw/gl if gl else 99
    sh = r.mean()/r.std()*np.sqrt(len(r)/2) if r.std() > 0 else 0
    years = {}
    for t in trades:
        years.setdefault(t[0], []).append(t[2])
    py = {y: round(np.sum(v), 0) for y, v in sorted(years.items())}
    pos_all = all(v > 0 for v in py.values())
    return dict(n=len(r), net=round(net), dd=round(dd), wr=round((r > 0).mean()*100),
                pf=round(pf, 2), sharpe=round(sh, 2), peryear=py, allpos=pos_all)


def main():
    pair = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    o = load(pair)
    print(f"=== {pair} 4h REGIME-TREND ({o.index.min().date()}..{o.index.max().date()}, fee {FEE}%) ===")
    print(f"{'ADX':>4}{'L':>4}{'M':>3}  n   net  DD   WR  PF   Sh  +yr  per-year")
    best = None
    for th in (18, 22, 25, 30):
        for L in (20, 30, 55):
            for M in (2.0, 3.0):
                m = metr(backtest(o, th, L, M))
                if not m:
                    continue
                flag = "✅" if (m["allpos"] and m["pf"] >= 1.3) else ""
                print(f"{th:>4}{L:>4}{M:>3}  {m['n']:>3} {m['net']:>5} {m['dd']:>4} {m['wr']:>4} "
                      f"{m['pf']:>4} {m['sharpe']:>4} {'Y' if m['allpos'] else '-':>3}  {m['peryear']} {flag}")
                if m["pf"] >= 1.3 and m["allpos"] and (best is None or m["net"] > best[1]["net"]):
                    best = ((th, L, M), m)
    if best:
        (th, L, M), m = best
        print(f"\nBEST robust: ADX>={th} Donchian{L} ATRx{M} -> net+{m['net']}% PF{m['pf']} Sharpe{m['sharpe']} n{m['n']}")
        mv = metr(backtest(o, th, L, M, vol_filt=True))
        print(f"  + volume filter: {mv}")


if __name__ == "__main__":
    main()
