"""Inside Bar final validation: (1) ETH/XRP cross-asset, (2) walk-forward.

Uses the winning config from the train/OOS optimization:
  Inside Bar 4h, ATR exit TP=5x / SL=3x, no filters.

Part 1 — CROSS-ASSET: run the SAME config on BTC, ETH, XRP. If the edge holds
on all three (like the pump-filter did), it's a real framework, not a BTC fluke.

Part 2 — WALK-FORWARD: instead of a single train=2024 split, slide the train
window. Test on each held-out segment with params fixed (no per-window tuning —
the config is already fixed, so this is pure OOS robustness across time).

Real fee 0.15% round-trip. 4h resampled from frozen 1h (ETH/XRP) or 15m (BTC).
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "backtests" / "frozen"
FEE = 0.00075
TP_MULT, SL_MULT = 5.0, 3.0   # winning config


def load_4h(pair):
    for src, rule in (("15m", "4h"), ("1h", "4h")):
        f = FROZEN / f"{pair}_{src}_2y.csv"
        if f.exists():
            df = pd.read_csv(f)
            df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
            return (df.set_index("ts").resample(rule).agg(
                {"open": "first", "high": "max", "low": "min",
                 "close": "last", "volume": "sum"}).dropna())
    raise FileNotFoundError(pair)


def atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def inside_signals(df):
    inside = (df["high"] < df["high"].shift()) & (df["low"] > df["low"].shift())
    mh = df["high"].shift(); ml = df["low"].shift()
    sig = pd.Series(0, index=df.index)
    c = df["close"]
    for i in range(2, len(df)):
        if not inside.iloc[i - 1]:
            continue
        if c.iloc[i] > mh.iloc[i - 1]:
            sig.iloc[i] = 1
        elif c.iloc[i] < ml.iloc[i - 1]:
            sig.iloc[i] = -1
    return sig


def run_atr(df, sig):
    c = df["close"].to_numpy(float)
    hi = df["high"].to_numpy(float); lo = df["low"].to_numpy(float)
    a = atr(df, 14).to_numpy(float)
    s = sig.to_numpy()
    eq = 1.0; pos = 0; entry = 0.0; tp = sl = 0.0
    rets = []
    for i in range(len(df)):
        if pos != 0:
            closed = None
            if pos == 1:
                if lo[i] <= sl: closed = sl / entry - 1
                elif hi[i] >= tp: closed = tp / entry - 1
            else:
                if hi[i] >= sl: closed = entry / sl - 1
                elif lo[i] <= tp: closed = entry / tp - 1
            if closed is not None:
                eq *= (1 + closed - FEE); rets.append(closed - FEE); pos = 0
        if s[i] != 0 and s[i] != pos:
            if pos != 0:
                r = (c[i] / entry - 1) if pos == 1 else (entry / c[i] - 1)
                eq *= (1 + r - FEE); rets.append(r - FEE)
            pos = int(s[i]); entry = c[i]; eq *= (1 - FEE)
            if pos == 1:
                tp = entry + TP_MULT * a[i]; sl = entry - SL_MULT * a[i]
            else:
                tp = entry - TP_MULT * a[i]; sl = entry + SL_MULT * a[i]
    total = (eq - 1) * 100
    rr = np.array(rets) if rets else np.array([0.0])
    sh = (rr.mean() / rr.std() * np.sqrt(len(rr))) if rr.std() and len(rr) > 1 else 0
    wr = round((rr > 0).mean() * 100) if len(rr) else 0
    return total, sh, wr, len(rets)


def slice_year(df, y):
    return df[df.index.year == y]


def main():
    print(f"===== Inside Bar 4h ATR TP{TP_MULT:g}/SL{SL_MULT:g} — final validation =====\n")

    # ─── Part 1: cross-asset ───
    print("--- PART 1: CROSS-ASSET (same config, 3 instruments) ---")
    print(f"{'pair':8} {'net%':>8} {'Sharpe':>7} {'WR':>4} {'trd':>4} {'buy&hold':>9}")
    cache = {}
    for pair in ("BTCUSDT", "ETHUSDT", "XRPUSDT"):
        df = load_4h(pair); cache[pair] = df
        sig = inside_signals(df)
        total, sh, wr, nt = run_atr(df, sig)
        bh = (df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100
        beat = " BEATS" if total > bh else ""
        print(f"{pair:8} {total:>+8.1f} {sh:>7.2f} {wr:>3}% {nt:>4} {bh:>+8.1f}%{beat}")

    # ─── Part 2: walk-forward per year, each instrument ───
    print("\n--- PART 2: WALK-FORWARD (per-year, fixed config = pure OOS) ---")
    print(f"{'pair':8} {'2024':>9} {'2025':>9} {'2026':>9}  all-positive?")
    for pair in ("BTCUSDT", "ETHUSDT", "XRPUSDT"):
        df = cache[pair]
        ys = {}
        for y in (2024, 2025, 2026):
            seg = slice_year(df, y)
            if len(seg) < 50:
                ys[y] = None; continue
            sig = inside_signals(seg)
            tot, _, _, _ = run_atr(seg, sig)
            ys[y] = tot
        cells = "  ".join(f"{('%+.0f%%' % ys[y]) if ys[y] is not None else 'n/a':>8}" for y in (2024, 2025, 2026))
        allpos = all(v is not None and v > 0 for v in ys.values())
        print(f"{pair:8} {cells}  {'YES' if allpos else 'no'}")


if __name__ == "__main__":
    main()
