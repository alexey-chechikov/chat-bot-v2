"""Reproduce TV ChannelBreakOutStrategy (Donchian breakout) with REAL fee.

TV screenshot (operator, 2026-05-31): BTCUSDT.P 1h, 1 Jan 2025 - 31 May 2026,
+51001 USDT (+5.10%), 1494 trades, WR 35.21%, Profit Factor 1.092, maxDD 2.93%,
avg win +0.79% / avg loss -0.60%. Commission bar tiny → suspect zero-fee mirage.

TV ChannelBreakOutStrategy = Donchian channel breakout, stop-and-reverse:
  upper = highest(high, L) of PRIOR L bars ; lower = lowest(low, L)
  close > upper -> LONG ; close < lower -> SHORT ; always in market (reverse).
Default length L=5. Test a few L. REAL taker fee 0.15% rt.
"""
import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT))
FEE_RT = 0.15
TF = os.getenv("TF", "1h")


def load(pair):
    df = pd.read_csv(ROOT / "backtests" / "frozen" / f"{pair}_1m_2y.csv")
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    o = (df.set_index("ts").resample(TF).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna())
    # match TV window
    o = o[(o.index >= "2025-01-01") & (o.index <= "2026-05-31")]
    return o


def backtest(o, L, fee_rt=FEE_RT):
    h = o["high"].to_numpy(float); l = o["low"].to_numpy(float)
    c = o["close"].to_numpy(float); idx = o.index
    upper = pd.Series(h).rolling(L).max().shift(1).to_numpy()
    lower = pd.Series(l).rolling(L).min().shift(1).to_numpy()
    pos = 0; entry = 0.0; rets = []
    for i in range(L + 1, len(o)):
        if not (np.isfinite(upper[i]) and np.isfinite(lower[i])):
            continue
        sig = 0
        if c[i] > upper[i]:
            sig = 1
        elif c[i] < lower[i]:
            sig = -1
        if sig != 0 and sig != pos:
            if pos != 0:                      # close current at c[i] (reverse)
                g = (c[i] - entry) / entry if pos == 1 else (entry - c[i]) / entry
                rets.append(g - fee_rt / 100.0)
            pos = sig; entry = c[i]
    return np.array(rets)


def metrics(rets, label):
    if len(rets) < 5:
        print(f"{label}: n={len(rets)}"); return
    eq = np.cumprod(1 + rets); net = (eq[-1] - 1) * 100
    peak = np.maximum.accumulate(eq); dd = ((eq - peak) / peak).min() * 100
    wr = (rets > 0).mean() * 100
    gw = rets[rets > 0].sum(); gl = -rets[rets < 0].sum()
    pf = gw / gl if gl > 0 else 999
    print(f"{label}: n={len(rets)} net={net:+.0f}% maxDD={dd:.0f}% WR={wr:.0f}% PF={pf:.3f}")


def main():
    pair = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    o = load(pair)
    print(f"=== {pair} {TF} ChannelBreakOut  ({o.index.min().date()} -> {o.index.max().date()}, {len(o)} bars) ===")
    print(f"--- with REAL fee {FEE_RT}% rt ---")
    for L in (5, 10, 20, 50):
        metrics(backtest(o, L, FEE_RT), f"  L={L:3d}")
    print("--- ZERO fee (= TV mirage check) ---")
    for L in (5, 10, 20, 50):
        metrics(backtest(o, L, 0.0), f"  L={L:3d}")


if __name__ == "__main__":
    main()
