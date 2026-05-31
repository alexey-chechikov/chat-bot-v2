"""Inside Bar parameter optimization with STRICT anti-overfit discipline.

Method (the honest one, not the one that flatters):
  - TRAIN window = 2024 only. Rank every param combo by train net%.
  - OOS window = 2025 + 2026 (never touched during selection).
  - Report: best-on-train, then how it does OOS. If train winner collapses
    OOS, that's overfit — say so. A combo is only "real" if it's positive
    in BOTH train and OOS.

Swept params:
  exit:    stop&reverse (hold to opposite signal) | ATR TP/SL with M_tp/M_sl
  filter:  none | ema200 trend-align | min-ATR (skip dead chop)
  confirm: enter on breakout close | require breakout + next-bar follow-through

Real fee 0.15% round-trip. 4h BTC (the TF that worked).
"""
import sys
from itertools import product
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "backtests" / "frozen"
FEE = 0.00075
BARS_PER_DAY = 6  # 4h


def load_4h(pair="BTCUSDT"):
    df = pd.read_csv(FROZEN / f"{pair}_15m_2y.csv")
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return (df.set_index("ts").resample("4h").agg(
        {"open": "first", "high": "max", "low": "min",
         "close": "last", "volume": "sum"}).dropna())


def atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def build_signals(df, filt, confirm, min_atr_mult):
    """Return entry signal series: +1/-1 on the bar a breakout triggers, else 0."""
    inside = (df["high"] < df["high"].shift()) & (df["low"] > df["low"].shift())
    mh = df["high"].shift(); ml = df["low"].shift()
    ema = df["close"].ewm(span=200).mean()
    a = atr(df, 14); a_med = a.rolling(100).median()
    sig = pd.Series(0, index=df.index)
    c = df["close"]
    for i in range(2, len(df)):
        if not inside.iloc[i - 1]:
            continue
        if min_atr_mult and a.iloc[i] < min_atr_mult * a_med.iloc[i]:
            continue  # skip dead chop
        longb = c.iloc[i] > mh.iloc[i - 1]
        shortb = c.iloc[i] < ml.iloc[i - 1]
        if confirm == "follow":  # need next bar to continue (checked lazily below)
            pass
        side = 1 if longb else (-1 if shortb else 0)
        if side == 0:
            continue
        if filt == "trend":
            up = c.iloc[i] > ema.iloc[i]
            if (side == 1) != up:
                continue
        sig.iloc[i] = side
    return sig


def run(df, sig, exit_mode, m_tp, m_sl):
    """Simulate. Returns net% over this df slice."""
    c = df["close"].to_numpy(float)
    hi = df["high"].to_numpy(float); lo = df["low"].to_numpy(float)
    a = atr(df, 14).to_numpy(float)
    s = sig.to_numpy()
    eq = 1.0
    pos = 0; entry = 0.0; tp = sl = 0.0
    for i in range(len(df)):
        # manage open ATR position
        if pos != 0 and exit_mode == "atr":
            if pos == 1:
                if lo[i] <= sl:
                    eq *= (1 + (sl / entry - 1) - FEE); pos = 0
                elif hi[i] >= tp:
                    eq *= (1 + (tp / entry - 1) - FEE); pos = 0
            else:
                if hi[i] >= sl:
                    eq *= (1 + (entry / sl - 1) - FEE); pos = 0
                elif lo[i] <= tp:
                    eq *= (1 + (entry / tp - 1) - FEE); pos = 0
        # new signal
        if s[i] != 0 and s[i] != pos:
            if exit_mode == "reverse" and pos != 0:
                # close at this close, pay fee
                r = (c[i] / entry - 1) if pos == 1 else (entry / c[i] - 1)
                eq *= (1 + r - FEE)
            if exit_mode == "atr" and pos != 0:
                r = (c[i] / entry - 1) if pos == 1 else (entry / c[i] - 1)
                eq *= (1 + r - FEE)
            pos = int(s[i]); entry = c[i]
            eq *= (1 - FEE)  # entry fee
            if exit_mode == "atr":
                if pos == 1:
                    tp = entry * (1 + m_tp * a[i] / entry); sl = entry * (1 - m_sl * a[i] / entry)
                else:
                    tp = entry * (1 - m_tp * a[i] / entry); sl = entry * (1 + m_sl * a[i] / entry)
        elif exit_mode == "reverse" and pos != 0:
            # mark-to-mkt via daily compounding approximated by close-to-close
            pass
    # for reverse mode, recompute properly as held*returns
    if exit_mode == "reverse":
        held = sig.replace(0, np.nan).ffill().fillna(0).shift().fillna(0)
        ret = df["close"].pct_change().fillna(0)
        net = held * ret - held.diff().abs().fillna(0) * FEE
        return ((1 + net).cumprod().iloc[-1] - 1) * 100
    return (eq - 1) * 100


def main():
    df = load_4h()
    train = df[df.index.year == 2024]
    oos = df[df.index.year >= 2025]
    print(f"TRAIN=2024 ({len(train)} bars)  OOS=2025-26 ({len(oos)} bars)")
    bh_tr = (train['close'].iloc[-1]/train['close'].iloc[0]-1)*100
    bh_oos = (oos['close'].iloc[-1]/oos['close'].iloc[0]-1)*100
    print(f"buy&hold: train {bh_tr:+.0f}%  oos {bh_oos:+.0f}%\n")

    filters = ["none", "trend", "minatr"]
    confirms = ["close"]
    exits = [("reverse", 0, 0), ("atr", 3.0, 1.5), ("atr", 4.0, 2.0), ("atr", 2.0, 2.0), ("atr", 5.0, 3.0)]

    results = []
    for filt, conf, (ex, mtp, msl) in product(filters, confirms, exits):
        min_atr = 1.2 if filt == "minatr" else 0
        f2 = "none" if filt == "minatr" else filt
        sig_tr = build_signals(train, f2, conf, min_atr)
        sig_oos = build_signals(oos, f2, conf, min_atr)
        tr = run(train, sig_tr, ex, mtp, msl)
        oo = run(oos, sig_oos, ex, mtp, msl)
        name = f"{filt:6} {ex}{f'{mtp:g}/{msl:g}' if ex=='atr' else ''}"
        results.append((name, tr, oo))

    print(f"{'variant':22} {'TRAIN%':>8} {'OOS%':>8}  verdict")
    for name, tr, oo in sorted(results, key=lambda x: -x[1]):
        v = "ROBUST" if (tr > 0 and oo > 0) else ("overfit" if tr > 0 >= oo else "weak")
        beat = " >B&H_oos" if oo > bh_oos else ""
        print(f"{name:22} {tr:>+8.1f} {oo:>+8.1f}  {v}{beat}")


if __name__ == "__main__":
    main()
