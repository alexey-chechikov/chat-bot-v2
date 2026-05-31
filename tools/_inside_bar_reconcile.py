"""Reconcile Win +234% vs Mac +130% on Inside Bar 4h BTC 2024-26.

Mac's suspects for the 1.8x gap, tested one at a time in MY engine:
  A. ATR type: simple rolling mean (mine) vs Wilder RMA (TV default)
  B. TP/SL intrabar order: SL-first (mine, conservative) vs TP-first (optimistic)
  C. same-bar fill: can a trade hit TP/SL on its OWN entry bar?
  D. ambiguous bar: when BOTH tp and sl are inside one bar's range — which wins?
  E. reverse accounting: closing at close vs at signal price

Run each variant, see which knob moves +234% toward +130%.
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "backtests" / "frozen"
FEE = 0.00075
TP_MULT, SL_MULT = 5.0, 3.0


def load_4h(pair="BTCUSDT"):
    df = pd.read_csv(FROZEN / f"{pair}_15m_2y.csv")
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return (df.set_index("ts").resample("4h").agg(
        {"open": "first", "high": "max", "low": "min",
         "close": "last", "volume": "sum"}).dropna())


def atr_simple(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def atr_wilder(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()  # Wilder RMA


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


def simulate(df, sig, atr_fn, tp_first, same_bar_fill, ambiguous):
    """ambiguous: 'sl' (pessimistic, SL wins ties) or 'tp' (optimistic)."""
    c = df["close"].to_numpy(float)
    hi = df["high"].to_numpy(float); lo = df["low"].to_numpy(float)
    a = atr_fn(df, 14).to_numpy(float)
    s = sig.to_numpy()
    eq = 1.0; pos = 0; entry = 0.0; tp = sl = 0.0; entry_bar = -1
    rets = []

    def check_exit(i):
        """Return closed-return or None. Honors tp_first/ambiguous."""
        if pos == 1:
            hit_tp = hi[i] >= tp; hit_sl = lo[i] <= sl
        else:
            hit_tp = lo[i] <= tp; hit_sl = hi[i] >= sl
        if hit_tp and hit_sl:
            win = (ambiguous == "tp")
        elif hit_tp:
            win = True
        elif hit_sl:
            win = False
        else:
            return None
        if win:
            return (tp / entry - 1) if pos == 1 else (entry / tp - 1)
        return (sl / entry - 1) if pos == 1 else (entry / sl - 1)

    for i in range(len(df)):
        if pos != 0 and (same_bar_fill or i > entry_bar):
            closed = check_exit(i)
            if closed is not None:
                eq *= (1 + closed - FEE); rets.append(closed - FEE); pos = 0
        if s[i] != 0 and s[i] != pos:
            if pos != 0:
                r = (c[i] / entry - 1) if pos == 1 else (entry / c[i] - 1)
                eq *= (1 + r - FEE); rets.append(r - FEE)
            pos = int(s[i]); entry = c[i]; entry_bar = i; eq *= (1 - FEE)
            if pos == 1:
                tp = entry + TP_MULT * a[i]; sl = entry - SL_MULT * a[i]
            else:
                tp = entry - TP_MULT * a[i]; sl = entry + SL_MULT * a[i]
    total = (eq - 1) * 100
    rr = np.array(rets) if rets else np.array([0.0])
    wr = round((rr > 0).mean() * 100) if len(rr) else 0
    return total, wr, len(rets)


def main():
    df = load_4h()
    sig = inside_signals(df)
    print("===== Inside Bar reconcile (BTC 4h 2024-26, fee 0.15%) =====")
    print(f"{'variant':46} {'net%':>9} {'WR':>4} {'trd':>4}")

    configs = [
        ("MINE original (simple ATR, SL-first, no same-bar, tie=SL)",
         atr_simple, False, False, "sl"),
        ("+ Wilder ATR (TV default)",
         atr_wilder, False, False, "sl"),
        ("+ Wilder + same-bar fill allowed",
         atr_wilder, False, True, "sl"),
        ("+ Wilder + tie=SL + same-bar",
         atr_wilder, False, True, "sl"),
        ("optimistic: simple ATR, tie=TP, same-bar",
         atr_simple, True, True, "tp"),
        ("pessimistic: Wilder, tie=SL, no same-bar (strictest)",
         atr_wilder, False, False, "sl"),
    ]
    for name, afn, tpf, sbf, amb in configs:
        total, wr, nt = simulate(df, sig, afn, tpf, sbf, amb)
        print(f"{name:46} {total:>+9.1f} {wr:>3}% {nt:>4}")


if __name__ == "__main__":
    main()
