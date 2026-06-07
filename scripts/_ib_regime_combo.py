"""Inside Bar 4h × НАШ РЕЖИМ (TEMA-стек + band + vol-off) — фильтр-свип.

Вопрос оператора: совместить валидированный Inside Bar (+264%/Sharpe 2.23, ATR-фильтр)
с нашими регим-линиями. В каноне свипнут только EMA50 ('trend') — победил ATR, не trend.
Здесь: полный режим (TEMA50>100>200 стек, vol-off z>=2.5, band от красной) как фильтр входа IB.
Сравниваем с baseline и atr_lo (текущий победитель). Reuse каноничного движка.
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT))
from tools._inside_bar_canonical import load, atr_wilder, metrics, FEE_RT, TPM, SLM, ATR_N


def tema(s, n):
    e1 = s.ewm(span=n, adjust=False).mean()
    e2 = e1.ewm(span=n, adjust=False).mean()
    e3 = e2.ewm(span=n, adjust=False).mean()
    return 3 * e1 - 3 * e2 + e3


def backtest_mask(o, allow_long, allow_short, fee=FEE_RT):
    h, l, c = o["high"].to_numpy(float), o["low"].to_numpy(float), o["close"].to_numpy(float)
    idx = o.index
    atr = atr_wilder(o, ATR_N).to_numpy(float)
    pos = 0; entry = tp = sl = 0.0; ent_ts = None; trades = []

    def close_t(px, ts, reason):
        nonlocal pos
        g = (px - entry) / entry if pos == 1 else (entry - px) / entry
        ret = g - fee / 100.0
        trades.append((str(ent_ts), str(ts), "L" if pos == 1 else "S",
                       round(entry, 1), round(px, 1), reason, round(ret * 100, 3)))
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
        if sig == 1 and not allow_long[i]: sig = 0
        if sig == -1 and not allow_short[i]: sig = 0
        if sig != 0 and np.isfinite(atr[i]):
            if pos == -sig: close_t(c[i], idx[i], "REV")
            if pos == 0:
                pos = sig; entry = c[i]; ent_ts = idx[i]
                tp = entry + TPM * atr[i] * sig; sl = entry - SLM * atr[i] * sig
    return trades


def per_year(trades):
    return {y: metrics([t for t in trades if t[0][:4] == str(y)]) for y in (2024, 2025, 2026)}


def main():
    pair = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    o = load(pair)
    n = len(o); c = o["close"]; cc = c.to_numpy(float)
    t50 = tema(c, 50).to_numpy(float); t100 = tema(c, 100).to_numpy(float); t200 = tema(c, 200).to_numpy(float)
    bull = (t50 > t100) & (t100 > t200)
    bear = (t50 < t100) & (t100 < t200)
    aboveRed = (cc - t200) / t200 * 100.0
    atr = atr_wilder(o, ATR_N).to_numpy(float); atr_pct = atr / cc
    atr_med = pd.Series(atr_pct).rolling(100).median().to_numpy()
    sma = pd.Series(atr_pct).rolling(100).mean().to_numpy()
    sd = pd.Series(atr_pct).rolling(100).std().to_numpy()
    z = (atr_pct - sma) / sd
    voloff = np.zeros(n, bool); stt = False
    for i in range(n):
        if np.isfinite(z[i]):
            if z[i] >= 2.5: stt = True
            elif z[i] < 1.0: stt = False
        voloff[i] = stt
    allow = np.ones(n, bool)
    hiVol = np.isfinite(atr_med) & (atr_pct >= atr_med)
    band = 2.5

    tests = {
        "baseline": (allow, allow),
        "atr_lo (winner)": (hiVol, hiVol),
        "stack": (bull, bear),
        "notvoloff": (~voloff, ~voloff),
        "stack+notvoloff": (bull & ~voloff, bear & ~voloff),
        "stack+atr": (bull & hiVol, bear & hiVol),
        "stack+atr+notvoloff": (bull & hiVol & ~voloff, bear & hiVol & ~voloff),
        "beyond-band": (aboveRed > band, aboveRed < -band),
    }
    print(f"=== {pair} 4h  Inside Bar × НАШ РЕЖИМ (TEMA)  fee {FEE_RT}%  bars={n} ===")
    res = {}
    for name, (al, ash) in tests.items():
        tr = backtest_mask(o, al, ash); res[name] = tr
        print(f"  {name:22s} {metrics(tr)}")
    print("\n--- per-year (робастность) ---")
    for name in ["atr_lo (winner)", "stack+atr", "stack+atr+notvoloff"]:
        print(f"  {name:22s} {per_year(res[name])}")


if __name__ == "__main__":
    main()
