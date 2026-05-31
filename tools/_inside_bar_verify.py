"""INDEPENDENT reproduction of Win's Inside Bar 4h breakout (2026-05-31 handoff).

Spec (verbatim): BTCUSDT 4h, fee 0.15% RT (0.075%/side taker).
  inside_bar[i-1] = high[i-1]<high[i-2] AND low[i-1]>low[i-2]
  on bar i: close[i]>high[i-1] -> LONG ; close[i]<low[i-1] -> SHORT  (entry at close[i])
  exit: ATR(14) on 4h, TP=5*ATR / SL=3*ATR, stop-and-reverse (hold until opposite
        signal OR ATR exit).
Win's reference (must match within reason, else FLAG): BTC +234% net 2y (slip 0),
Sharpe 2.57, maxDD -28%, WR 46%, ~170 trades; WF 2024 +88% / 2025 +25% / 2026 +37%.

Written from the spec only — no Win code used (independent engine).
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT))
FEE_RT = 0.15        # %
SLIP = float(__import__("os").getenv("SLIP", "0.0"))  # % per side
TP_MULT, SL_MULT, ATR_N = 5.0, 3.0, 14


def load_4h(pair, src="1m"):
    f = ROOT / "backtests" / "frozen" / f"{pair}_{src}_2y.csv"
    df = pd.read_csv(f)
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    o = (df.set_index("ts").resample("4h").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna())
    return o


def wilder_atr(h, l, c, n=14):
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def backtest(o, fee_rt=FEE_RT, slip=SLIP):
    h = o["high"].to_numpy(float); l = o["low"].to_numpy(float)
    c = o["close"].to_numpy(float); idx = o.index
    atr = wilder_atr(o["high"], o["low"], o["close"], ATR_N).to_numpy(float)
    n = len(o)
    pos = 0          # +1 long, -1 short, 0 flat
    entry = tp = sl = 0.0
    trades = []      # (entry_ts, exit_ts, side, entry, exit, ret_frac)
    ent_ts = None

    def close_trade(exit_px, exit_ts):
        nonlocal pos, entry
        gross = (exit_px - entry) / entry if pos == 1 else (entry - exit_px) / entry
        ret = gross - (fee_rt + 2 * slip) / 100.0
        trades.append((ent_ts, exit_ts, "L" if pos == 1 else "S", entry, exit_px, ret))
        pos = 0

    for i in range(2, n):
        # 1) ATR exit check on bar i (position opened on an earlier bar)
        if pos != 0:
            if pos == 1:
                if l[i] <= sl:
                    close_trade(sl, idx[i])
                elif h[i] >= tp:
                    close_trade(tp, idx[i])
            else:
                if h[i] >= sl:
                    close_trade(sl, idx[i])
                elif l[i] <= tp:
                    close_trade(tp, idx[i])
        # 2) signal on bar i: inside bar at i-1 vs i-2, breakout by close[i]
        inside = h[i - 1] < h[i - 2] and l[i - 1] > l[i - 2]
        sig = 0
        # breakout reference: inside bar (i-1, per spec) or mother bar (i-2, classic)
        ref = i - 2 if __import__("os").getenv("MOTHER") == "1" else i - 1
        if inside:
            if c[i] > h[ref]:
                sig = 1
            elif c[i] < l[ref]:
                sig = -1
        if sig != 0 and np.isfinite(atr[i]):
            if pos == -sig:          # opposite -> reverse (close at close[i])
                close_trade(c[i], idx[i])
            if pos == 0:
                pos = sig; entry = c[i]; ent_ts = idx[i]
                if sig == 1:
                    tp = entry + TP_MULT * atr[i]; sl = entry - SL_MULT * atr[i]
                else:
                    tp = entry - TP_MULT * atr[i]; sl = entry + SL_MULT * atr[i]
    return trades


def metrics(trades, label=""):
    if not trades:
        print(f"{label}: no trades"); return
    rets = np.array([t[5] for t in trades])
    eq = np.cumprod(1 + rets)
    net = (eq[-1] - 1) * 100
    peak = np.maximum.accumulate(eq)
    dd = ((eq - peak) / peak).min() * 100
    wr = (rets > 0).mean() * 100
    wins = rets[rets > 0]; losses = rets[rets < 0]
    sharpe = rets.mean() / rets.std() * np.sqrt(len(rets) / 2) if rets.std() > 0 else 0  # ~per-year
    print(f"{label}: n={len(trades)} net={net:+.0f}% maxDD={dd:.0f}% WR={wr:.0f}% "
          f"Sharpe~{sharpe:.2f} avgW={wins.mean()*100:+.2f}% avgL={losses.mean()*100:+.2f}% "
          f"worst={rets.min()*100:.2f}%")


def main():
    pair = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    o = load_4h(pair)
    print(f"=== {pair} 4h Inside Bar  ({o.index.min().date()} -> {o.index.max().date()}, "
          f"{len(o)} bars, fee {FEE_RT}% rt, slip {SLIP}%/side) ===")
    tr = backtest(o)
    metrics(tr, "FULL 2y")
    # walk-forward per year (config fixed = clean OOS)
    for y in (2024, 2025, 2026):
        yt = [t for t in tr if t[0].year == y]
        metrics(yt, f"  {y}")
    # forward: fetch fresh 4h beyond frozen via API
    try:
        from core.data_loader import load_klines
        live = load_klines(symbol=pair, timeframe="4h", limit=400)
        tcol = next((x for x in ("open_time", "ts") if x in live.columns), None)
        live["ts"] = pd.to_datetime(live[tcol], unit="ms" if tcol == "ts" else None, utc=True)
        lo = live.set_index("ts")[["open", "high", "low", "close"]].sort_index()
        fresh = lo[lo.index > o.index.max()]
        if len(fresh) > 20:
            full = pd.concat([o.tail(60), fresh])
            tr_f = [t for t in backtest(full) if t[0] > o.index.max()]
            metrics(tr_f, f"  FORWARD (post {o.index.max().date()}, {len(fresh)} bars)")
        else:
            print(f"  FORWARD: only {len(fresh)} fresh 4h bars beyond frozen — too few")
    except Exception as e:
        print(f"  FORWARD fetch failed: {e}")


if __name__ == "__main__":
    main()
