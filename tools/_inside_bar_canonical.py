"""CANONICAL Inside Bar 4h — pinned rules + trade export + filter sweep.

Goal: ONE deterministic implementation so both engines produce identical trades.
Every rule is fixed and documented. Exports the full trade list to CSV so Win can
diff trade-by-trade. Then sweeps filters to IMPROVE net/PF/Sharpe.

PINNED RULES (canonical):
  TF=4h (resample 1m, UTC boundaries). fee=0.15% round-trip (0.075%/side taker).
  ATR = Wilder RMA of True Range, period 14, on 4h.
  Inside bar: bar i-1 inside i-2  (high[i-1]<high[i-2] AND low[i-1]>low[i-2]).
  Breakout (MOTHER bar i-2): close[i]>high[i-2] -> LONG ; close[i]<low[i-2] -> SHORT.
  Entry = close[i]. Exit: TP=entry+5*ATR[i] / SL=entry-3*ATR[i] (long; inverse short).
  Intrabar order: SL checked BEFORE TP (conservative). Stop-and-reverse: opposite
  signal closes at close[i] and opens the new side. ATR fixed at entry bar.
  Single entry (NO pyramiding).
"""
import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT))
FEE_RT = float(os.getenv("FEE_RT", "0.15"))
TPM, SLM, ATR_N = 5.0, 3.0, 14
OUT_CSV = ROOT / "docs" / "STRATEGIES" / "inside_bar_trades.csv"


def load(pair):
    df = pd.read_csv(ROOT / "backtests" / "frozen" / f"{pair}_1m_2y.csv")
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return (df.set_index("ts").resample("4h").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last",
         "volume": "sum"}).dropna())


def atr_wilder(o, n=14):
    pc = o["close"].shift(1)
    tr = pd.concat([o["high"]-o["low"], (o["high"]-pc).abs(), (o["low"]-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()


def backtest(o, fee=FEE_RT, filt=None):
    h, l, c = o["high"].to_numpy(float), o["low"].to_numpy(float), o["close"].to_numpy(float)
    v = o["volume"].to_numpy(float); idx = o.index
    atr = atr_wilder(o, ATR_N).to_numpy(float)
    atr_pct = atr / c
    ema = o["close"].ewm(span=50, adjust=False).mean().to_numpy(float)
    vma = pd.Series(v).rolling(20).mean().to_numpy()
    atr_med = pd.Series(atr_pct).rolling(100).median().to_numpy()
    pos = 0; entry = tp = sl = 0.0; ent_ts = None; trades = []

    def close_t(px, ts, reason):
        nonlocal pos
        g = (px-entry)/entry if pos == 1 else (entry-px)/entry
        ret = g - fee/100.0
        trades.append((str(ent_ts), str(ts), "L" if pos == 1 else "S",
                       round(entry, 1), round(px, 1), reason, round(ret*100, 3)))
        pos = 0

    for i in range(2, len(o)):
        if pos != 0:
            if pos == 1:
                if l[i] <= sl: close_t(sl, idx[i], "SL")
                elif h[i] >= tp: close_t(tp, idx[i], "TP")
            else:
                if h[i] >= sl: close_t(sl, idx[i], "SL")
                elif l[i] <= tp: close_t(tp, idx[i], "TP")
        inside = h[i-1] < h[i-2] and l[i-1] > l[i-2]
        sig = 0
        if inside:
            if c[i] > h[i-2]: sig = 1
            elif c[i] < l[i-2]: sig = -1
        # ── FILTERS ──
        if sig != 0 and filt:
            if "trend" in filt:   # only with 4h trend (EMA50)
                if (sig == 1 and c[i] < ema[i]) or (sig == -1 and c[i] > ema[i]):
                    sig = 0
            if sig != 0 and "vol" in filt and np.isfinite(vma[i]) and v[i] < vma[i]:
                sig = 0
            if sig != 0 and "atr_lo" in filt and np.isfinite(atr_med[i]) and atr_pct[i] < atr_med[i]:
                sig = 0  # only trade when ATR above its median (avoid dead chop)
            if sig != 0 and "strong" in filt:  # break mother by >=0.3 ATR
                ref = h[i-2] if sig == 1 else l[i-2]
                if abs(c[i]-ref) < 0.3*atr[i]: sig = 0
        if sig != 0 and np.isfinite(atr[i]):
            if pos == -sig: close_t(c[i], idx[i], "REV")
            if pos == 0:
                pos = sig; entry = c[i]; ent_ts = idx[i]
                tp = entry + TPM*atr[i]*sig; sl = entry - SLM*atr[i]*sig
    return trades


def metrics(trades):
    if len(trades) < 5: return None
    r = np.array([t[6] for t in trades])/100
    eq = np.cumprod(1+r); net = (eq[-1]-1)*100
    dd = ((eq-np.maximum.accumulate(eq))/np.maximum.accumulate(eq)).min()*100
    gw = r[r > 0].sum(); gl = -r[r < 0].sum()
    sh = r.mean()/r.std()*np.sqrt(len(r)/2) if r.std() > 0 else 0
    return dict(n=len(r), net=round(net), dd=round(dd), wr=round((r > 0).mean()*100),
                pf=round(gw/gl if gl else 99, 2), sharpe=round(sh, 2))


def main():
    pair = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    o = load(pair)
    print(f"=== {pair} 4h CANONICAL Inside Bar ({o.index.min().date()}..{o.index.max().date()}, fee {FEE_RT}%) ===")
    base = backtest(o)
    print(f"BASELINE (no filter): {metrics(base)}")
    # export canonical trade list for Win to diff
    pd.DataFrame(base, columns=["entry_ts", "exit_ts", "side", "entry", "exit", "reason", "pnl%"]).to_csv(OUT_CSV, index=False)
    print(f"  trade list -> {OUT_CSV}")
    print("\n--- FILTER SWEEP (improve metrics) ---")
    for name, filt in [("trend", ["trend"]), ("strong", ["strong"]), ("atr_lo", ["atr_lo"]),
                       ("vol", ["vol"]), ("trend+strong", ["trend", "strong"]),
                       ("trend+atr", ["trend", "atr_lo"]), ("trend+strong+atr", ["trend", "strong", "atr_lo"])]:
        print(f"  {name:18s} {metrics(backtest(o, filt=filt))}")

    # walk-forward per year for the winner (atr_lo)
    print("\n--- atr_lo filter, PER YEAR (robustness) ---")
    best = backtest(o, filt=["atr_lo"])
    for y in (2024, 2025, 2026):
        yt = [t for t in best if t[0][:4] == str(y)]
        print(f"  {y}: {metrics(yt)}")
    bt = backtest(o)
    print("--- baseline, PER YEAR (compare) ---")
    for y in (2024, 2025, 2026):
        yt = [t for t in bt if t[0][:4] == str(y)]
        print(f"  {y}: {metrics(yt)}")


if __name__ == "__main__":
    main()
