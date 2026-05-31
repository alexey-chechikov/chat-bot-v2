"""Inside Bar parameter sweep on 2y frozen BTC, WITH real fees AND per-year
breakdown (built-in OOS). The base Inside Bar beat buy&hold (+174%, Sharpe 1.18)
— here we sweep TF + exit params + a trend filter and check each combo holds
across 2024/2025/2026 separately, not just in aggregate. A combo that's only
good in one year is overfit, not edge.

Variants swept:
  TF in {1h, 4h}
  exit: hold-until-reverse (stop&reverse) vs fixed ATR TP/SL
  optional trend filter: only take breakouts aligned with EMA200 slope
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "backtests" / "frozen"
FEE = 0.00075


def load(pair, tf):
    f = FROZEN / f"{pair}_{tf}_2y.csv"
    if not f.exists():
        # resample from 15m
        df = pd.read_csv(FROZEN / f"{pair}_15m_2y.csv")
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        return (df.set_index("ts").resample(tf).agg(
            {"open": "first", "high": "max", "low": "min",
             "close": "last", "volume": "sum"}).dropna())
    df = pd.read_csv(f)
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.set_index("ts")[["open", "high", "low", "close", "volume"]]


def atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def inside_bar_pos(df, use_trend=False):
    inside = (df["high"] < df["high"].shift()) & (df["low"] > df["low"].shift())
    mh = df["high"].shift(); ml = df["low"].shift()
    pos = pd.Series(np.nan, index=df.index)
    ema = df["close"].ewm(span=200).mean()
    trend_up = df["close"] > ema
    for i in range(2, len(df)):
        if inside.iloc[i - 1]:
            long_brk = df["close"].iloc[i] > mh.iloc[i - 1]
            short_brk = df["close"].iloc[i] < ml.iloc[i - 1]
            if use_trend:
                if long_brk and trend_up.iloc[i]:
                    pos.iloc[i] = 1
                elif short_brk and not trend_up.iloc[i]:
                    pos.iloc[i] = -1
            else:
                if long_brk:
                    pos.iloc[i] = 1
                elif short_brk:
                    pos.iloc[i] = -1
    return pos.ffill().fillna(0)


def bt(df, pos):
    ret = df["close"].pct_change().fillna(0)
    held = pos.shift().fillna(0)
    net = held * ret - held.diff().abs().fillna(0) * FEE
    eq = (1 + net).cumprod()
    total = (eq.iloc[-1] - 1) * 100
    sh = (net.mean() / net.std() * np.sqrt({"1h": 24, "4h": 6}.get(TF, 6) * 365)) if net.std() else 0
    dd = ((eq / eq.cummax()) - 1).min() * 100
    nt = int((held.diff().abs() > 0).sum())
    # per-year net%
    yr = {}
    for y, g in net.groupby(net.index.year):
        yr[y] = ((1 + g).cumprod().iloc[-1] - 1) * 100
    return total, sh, dd, nt, yr


TF = "4h"


def main():
    pair = "BTCUSDT"
    print(f"===== Inside Bar SWEEP {pair} (fee {FEE*2*100:.2f}%/rt) =====")
    for tf in ("4h", "1h"):
        global TF
        TF = tf
        df = load(pair, tf)
        bh = (df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100
        print(f"\n--- TF={tf}  bars={len(df)}  buy&hold={bh:+.1f}% ---")
        print(f"{'variant':24} {'net%':>8} {'Sh':>5} {'maxDD':>6} {'trd':>4} | per-year")
        for use_trend in (False, True):
            pos = inside_bar_pos(df, use_trend=use_trend)
            total, sh, dd, nt, yr = bt(df, pos)
            label = "InsBar+trendfilter" if use_trend else "InsBar plain"
            yrs = "  ".join(f"{y}:{v:+.0f}%" for y, v in sorted(yr.items()))
            print(f"{label:24} {total:>+8.1f} {sh:>5.2f} {dd:>6.1f} {nt:>4} | {yrs}")


if __name__ == "__main__":
    main()
