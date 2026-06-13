"""Робастность EW-импульс-фильтра к порогу ZigZag (3.5% не должно быть особенным).
Если impulse/correction split держится на 2.5-5% — реально; если только 3.5% — артефакт."""
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
hl2 = ((df["high"] + df["low"]) / 2).to_numpy(float)
diff = e.ema(hl2, 14) - e.ema(hl2, 77)

print("BTC 4ч — EW-импульс split при разных порогах ZigZag:")
print(f"{'zz%':>5}{'n_imp':>7}{'imp_heldX':>11}{'imp_win':>9}{'n_corr':>8}{'corr_heldX':>12}{'corr_win':>10}")
for zz in (2.5, 3.0, 3.5, 4.0, 4.5, 5.0):
    piv = e.zigzag(close, zz)
    imp_r, corr_r = [], []
    for k in range(len(cx) - 1):
        i, nxt = cx[k], cx[k + 1]
        d = 1 if diff[i] > 0 else -1
        retX = d * (close[nxt] / close[i] - 1) * 100 - FEE
        ew = e.ew_features(close, piv, i)
        if ew is None:
            continue
        (imp_r if ew[2] else corr_r).append(retX)
    if imp_r and corr_r:
        iw = 100 * np.mean(np.array(imp_r) > 0)
        cw = 100 * np.mean(np.array(corr_r) > 0)
        print(f"{zz:>5}{len(imp_r):>7}{np.mean(imp_r):>+11.2f}{iw:>8.0f}%"
              f"{len(corr_r):>8}{np.mean(corr_r):>+12.2f}{cw:>9.0f}%")

print("\nЕсли imp_heldX>0 и corr_heldX<0 на ВСЕХ порогах → разделение робастно.")
