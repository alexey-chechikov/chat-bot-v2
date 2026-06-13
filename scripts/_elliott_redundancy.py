"""Добавляет ли EW-импульс что-то ПОВЕРХ фильтра наклона EMA77 (H5)?
Если impulse ≈ slope_ok — избыточно. Если разделяет ВНУТРИ slope_ok — новая инфа.
BTC 4ч."""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT / "scripts"))
import _elliott_on_macross as e

FEE = 0.10
df = e.load("4h")
close, cx = e.cross_signals(df)
piv = e.zigzag(close, 3.5)
hl2 = ((df["high"] + df["low"]) / 2).to_numpy(float)
e77 = e.ema(hl2, 77)
e200 = e.ema(hl2, 200)
diff = e.ema(hl2, 14) - e77

rows = []
for k in range(len(cx) - 1):
    i, nxt = cx[k], cx[k + 1]
    d = 1 if diff[i] > 0 else -1
    retX = d * (close[nxt] / close[i] - 1) * 100 - FEE
    slope_ok = (e77[i] - e77[i - 5] > 0) == (d == 1) if i >= 5 else False
    side_ok = (close[i] > e200[i]) == (d == 1)
    ew = e.ew_features(close, piv, i)
    if ew is None:
        continue
    rows.append((retX, ew[2], slope_ok, side_ok))

t = pd.DataFrame(rows, columns=["rX", "imp", "slope", "side"])
print(f"BTC 4ч, кроссов с EW-контекстом: {len(t)}\n")

# корреляция impulse vs slope_ok
agree = (t["imp"] == t["slope"]).mean() * 100
print(f"EW-импульс совпадает со slope_ok в {agree:.0f}% случаев "
      f"({'избыточно' if agree>75 else 'частично независимы'})\n")

print("Разделяет ли импульс ВНУТРИ каждой группы slope?")
for sv in (True, False):
    g = t[t["slope"] == sv]
    if len(g) < 8:
        continue
    for iv in (True, False):
        s = g[g["imp"] == iv]
        if len(s) >= 5:
            print(f"  slope_ok={sv!s:5} · импульс={iv!s:5}: n={len(s):3} heldX {s.rX.mean():+.2f}% "
                  f"win {100*(s.rX>0).mean():.0f}%")

print("\nЛучшая связка (импульс И slope_ok И side_ok) vs всё остальное:")
best = t[t.imp & t.slope & t.side]
rest = t[~(t.imp & t.slope & t.side)]
for lbl, s in [("импульс+H5", best), ("остальное", rest)]:
    if len(s) >= 5:
        pf = s.rX[s.rX > 0].sum() / abs(s.rX[s.rX <= 0].sum()) if (s.rX <= 0).any() else float("inf")
        print(f"  {lbl:12} n={len(s):3} net {s.rX.sum():+.0f}пп heldX {s.rX.mean():+.2f}% "
              f"win {100*(s.rX>0).mean():.0f}% PF {pf:.2f}")
