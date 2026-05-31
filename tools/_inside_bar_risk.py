"""Inside Bar BTC — risk & sizing analysis for the proven config (4h ATR TP5/SL3).

Answers the questions that decide whether/how to trade it live:
  - Real max drawdown of the equity curve (peak-to-trough %)
  - Per-trade loss distribution: worst trade, avg loss, longest losing streak
  - Slippage stress: re-run with +0.05% / +0.10% entry slippage (market fill is
    worse than the close the harness uses) — does the edge survive?
  - Sizing: given a target "max account drawdown I can stomach", what fraction
    of equity per trade keeps worst historical DD under that?

Real fee 0.15% rt. Prints an equity curve summary by quarter too.
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


def simulate(df, sig, slip=0.0, frac=1.0):
    """Return (equity_series, list_of_trade_returns). slip = entry slippage frac.
    frac = fraction of equity risked per trade (1.0 = full compounding)."""
    c = df["close"].to_numpy(float)
    hi = df["high"].to_numpy(float); lo = df["low"].to_numpy(float)
    a = atr(df, 14).to_numpy(float)
    s = sig.to_numpy()
    idx = df.index
    eq = 1.0; pos = 0; entry = 0.0; tp = sl = 0.0
    eq_curve = []; trades = []

    def apply(trade_ret):
        nonlocal eq
        eq *= (1 + frac * trade_ret)

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
                tr = closed - FEE; apply(tr); trades.append(tr); pos = 0
        if s[i] != 0 and s[i] != pos:
            if pos != 0:
                r = (c[i] / entry - 1) if pos == 1 else (entry / c[i] - 1)
                tr = r - FEE; apply(tr); trades.append(tr)
            # entry with slippage: pay slip on entry price (worse fill)
            entry = c[i] * (1 + slip) if s[i] == 1 else c[i] * (1 - slip)
            pos = int(s[i]); eq *= (1 - frac * FEE)
            if pos == 1:
                tp = entry + TP_MULT * a[i]; sl = entry - SL_MULT * a[i]
            else:
                tp = entry - TP_MULT * a[i]; sl = entry + SL_MULT * a[i]
        eq_curve.append(eq)
    return pd.Series(eq_curve, index=idx), trades


def max_dd(eq):
    return ((eq / eq.cummax()) - 1).min() * 100


def losing_streak(trades):
    mx = cur = 0
    for t in trades:
        cur = cur + 1 if t < 0 else 0
        mx = max(mx, cur)
    return mx


def main():
    df = load_4h()
    sig = inside_signals(df)

    print("===== Inside Bar BTC 4h TP5/SL3 — RISK & SIZING =====\n")

    # ─── slippage stress ───
    print("--- SLIPPAGE STRESS (market fill worse than close) ---")
    print(f"{'entry slip':>11} {'net%':>9} {'maxDD%':>8} {'worst trd':>10}")
    for slip in (0.0, 0.0005, 0.0010, 0.0020):
        eq, tr = simulate(df, sig, slip=slip, frac=1.0)
        total = (eq.iloc[-1] - 1) * 100
        wt = min(tr) * 100 if tr else 0
        print(f"{slip*100:>10.2f}% {total:>+9.1f} {max_dd(eq):>8.1f} {wt:>+9.2f}%")

    # ─── trade distribution at realistic slip 0.05% ───
    eq, tr = simulate(df, sig, slip=0.0005, frac=1.0)
    tr = np.array(tr)
    print("\n--- PER-TRADE (at 0.05% slippage, full size) ---")
    print(f"  trades: {len(tr)}   WR: {round((tr>0).mean()*100)}%")
    print(f"  avg win:  {tr[tr>0].mean()*100:+.2f}%   avg loss: {tr[tr<0].mean()*100:+.2f}%")
    print(f"  worst trade: {tr.min()*100:+.2f}%   best: {tr.max()*100:+.2f}%")
    print(f"  longest losing streak: {losing_streak(tr)} trades")
    print(f"  max drawdown (full size): {max_dd(eq):.1f}%")

    # ─── sizing: what frac keeps DD under a target ───
    print("\n--- SIZING (target = max account DD you can stomach) ---")
    print(f"{'per-trade frac':>14} {'final net%':>11} {'maxDD%':>8}")
    for frac in (1.0, 0.5, 0.33, 0.25, 0.15):
        eqf, _ = simulate(df, sig, slip=0.0005, frac=frac)
        print(f"{frac*100:>12.0f}% {(eqf.iloc[-1]-1)*100:>+10.1f} {max_dd(eqf):>8.1f}")

    # ─── by quarter (consistency) ───
    print("\n--- EQUITY BY QUARTER (full size, 0.05% slip) ---")
    q = eq.resample("QE").last()
    prev = 1.0
    for ts, v in q.items():
        chg = (v / prev - 1) * 100
        prev = v
        bar = "#" * min(int(abs(chg) / 3), 20)
        print(f"  {ts.date()}  {chg:>+7.1f}%  {bar}")


if __name__ == "__main__":
    main()
