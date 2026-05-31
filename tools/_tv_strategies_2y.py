"""Reproduce TradingView built-in strategies on our 2y frozen BTC 4h, WITH real
fees, and compare to buy&hold. Operator ran these in TV (2021-2026) and they
showed +4..+31% but ALL lost to buy&hold by ~$1M and Sharpe ~0. TV default fee
is often ~0. Here we charge a real round-trip taker fee and benchmark honestly.

Strategies (classic TV definitions, long+short, stop-and-reverse where natural):
  supertrend, inside_bar, bollinger, rsi, stochastic, volty_expan_close, pivot_ext

Bars: 4h resampled from frozen 15m. Position sizing = full equity each trade,
compounding, so the % return is comparable to TV's "Общие ПР/УБ %".
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "backtests" / "frozen"
FEE = 0.00075          # taker per side (0.075%); round-trip 0.15%
TF = "4h"


def load_4h(pair="BTCUSDT"):
    df = pd.read_csv(FROZEN / f"{pair}_15m_2y.csv")
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    o = (df.set_index("ts").resample(TF).agg(
        {"open": "first", "high": "max", "low": "min",
         "close": "last", "volume": "sum"}).dropna())
    return o


# ─── indicator helpers ──────────────────────────────────────────────────────
def atr(df, n=10):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).rolling(n).mean()
    dn = (-d.clip(upper=0)).rolling(n).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def stoch(df, k=14, d=3):
    ll = df["low"].rolling(k).min(); hh = df["high"].rolling(k).max()
    kk = 100 * (df["close"] - ll) / (hh - ll).replace(0, np.nan)
    return kk.rolling(d).mean()


# ─── signal generators: return a position series (+1 long / -1 short / 0 flat)
def sig_supertrend(df, period=10, mult=3.0):
    a = atr(df, period); hl2 = (df["high"] + df["low"]) / 2
    up = hl2 - mult * a; dn = hl2 + mult * a
    dir_ = pd.Series(1, index=df.index)
    for i in range(1, len(df)):
        if df["close"].iloc[i] > dn.iloc[i - 1]:
            dir_.iloc[i] = 1
        elif df["close"].iloc[i] < up.iloc[i - 1]:
            dir_.iloc[i] = -1
        else:
            dir_.iloc[i] = dir_.iloc[i - 1]
    return dir_


def sig_inside_bar(df):
    # inside bar = high<prev high and low>prev low; trade breakout of mother bar
    inside = (df["high"] < df["high"].shift()) & (df["low"] > df["low"].shift())
    mh = df["high"].shift(); ml = df["low"].shift()
    pos = pd.Series(np.nan, index=df.index)
    for i in range(2, len(df)):
        if inside.iloc[i - 1]:
            if df["close"].iloc[i] > mh.iloc[i - 1]:
                pos.iloc[i] = 1
            elif df["close"].iloc[i] < ml.iloc[i - 1]:
                pos.iloc[i] = -1
    return pos.ffill().fillna(0)


def sig_bollinger(df, n=20, k=2.0):
    ma = df["close"].rolling(n).mean(); sd = df["close"].rolling(n).std()
    up = ma + k * sd; dn = ma - k * sd
    pos = pd.Series(np.nan, index=df.index)
    pos[df["close"] < dn] = 1     # buy lower band (mean-revert, TV default)
    pos[df["close"] > up] = -1
    return pos.ffill().fillna(0)


def sig_rsi(df, n=14, lo=30, hi=70):
    r = rsi(df["close"], n)
    pos = pd.Series(np.nan, index=df.index)
    pos[r < lo] = 1; pos[r > hi] = -1
    return pos.ffill().fillna(0)


def sig_stochastic(df, k=14, d=3, lo=20, hi=80):
    s = stoch(df, k, d)
    pos = pd.Series(np.nan, index=df.index)
    pos[s < lo] = 1; pos[s > hi] = -1
    return pos.ffill().fillna(0)


def sig_volty(df, length=5, mult=0.75):
    # Volty Expan Close: breakout of close +/- mult*ATR (stop-and-reverse)
    a = atr(df, length)
    long_stop = df["close"].shift() + mult * a.shift()
    short_stop = df["close"].shift() - mult * a.shift()
    pos = pd.Series(np.nan, index=df.index)
    pos[df["close"] > long_stop] = 1
    pos[df["close"] < short_stop] = -1
    return pos.ffill().fillna(0)


def sig_pivot_ext(df, left=4, right=2):
    # Pivot Extension: trade in direction of last confirmed pivot break
    ph = df["high"].rolling(left + right + 1, center=True).apply(
        lambda x: 1.0 if x[left] == max(x) else 0.0, raw=True)
    pl = df["low"].rolling(left + right + 1, center=True).apply(
        lambda x: 1.0 if x[left] == min(x) else 0.0, raw=True)
    last_ph = df["high"].where(ph == 1).ffill()
    last_pl = df["low"].where(pl == 1).ffill()
    pos = pd.Series(np.nan, index=df.index)
    pos[df["close"] > last_ph] = 1
    pos[df["close"] < last_pl] = -1
    return pos.ffill().fillna(0)


STRATS = {
    "supertrend": sig_supertrend, "inside_bar": sig_inside_bar,
    "bollinger": sig_bollinger, "rsi": sig_rsi, "stochastic": sig_stochastic,
    "volty_expan": sig_volty, "pivot_ext": sig_pivot_ext,
}


def backtest(df, pos):
    """Equity curve from next-bar execution; charge FEE on every position change."""
    ret = df["close"].pct_change().fillna(0)
    held = pos.shift().fillna(0)              # act on next bar
    gross = held * ret
    turns = held.diff().abs().fillna(0)       # 0->1 =1 turn, 1->-1 =2 turns
    cost = turns * FEE
    net = gross - cost
    eq = (1 + net).cumprod()
    n_trades = int((held.diff().abs() > 0).sum())
    total = (eq.iloc[-1] - 1) * 100
    # sharpe (per-bar, annualized for 4h: 6 bars/day*365)
    sh = (net.mean() / net.std() * np.sqrt(6 * 365)) if net.std() else 0
    # max drawdown
    dd = ((eq / eq.cummax()) - 1).min() * 100
    return total, sh, dd, n_trades


def main():
    df = load_4h()
    bh = (df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100
    print(f"===== TV strategies on 2y frozen BTC 4h (fee {FEE*2*100:.2f}%/rt) =====")
    print(f"span {df.index[0].date()} -> {df.index[-1].date()}  bars={len(df)}")
    print(f"BUY & HOLD: {bh:+.1f}%\n")
    print(f"{'strategy':14} {'net%':>8} {'vs B&H':>8} {'Sharpe':>7} {'maxDD%':>7} {'trades':>7}")
    rows = []
    for name, fn in STRATS.items():
        pos = fn(df)
        total, sh, dd, nt = backtest(df, pos)
        rows.append((name, total, total - bh, sh, dd, nt))
    for name, total, vs, sh, dd, nt in sorted(rows, key=lambda x: -x[1]):
        beat = " BEATS B&H" if vs > 0 else ""
        print(f"{name:14} {total:>+8.1f} {vs:>+8.1f} {sh:>7.2f} {dd:>7.1f} {nt:>7}{beat}")


if __name__ == "__main__":
    main()
