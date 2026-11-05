"""1ч-бары вокруг событий участка 1 и ширина трёх TEMA."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402

pd.set_option("display.width", 260, "display.max_columns", 60, "display.max_rows", 900)
m, h1, h4, d1, fund = cw.load()

for tag, b in (("4ч", h4), ("1ч", h1)):
    b["width3"] = (b[["G", "Y", "R"]].max(axis=1) - b[["G", "Y", "R"]].min(axis=1)) / b["close"] * 100

COLS = ["t", "open", "high", "low", "close", "G", "Y", "R", "B", "B4", "d_G", "d_R", "d_B", "d_Bo", "width3", "run_G", "run_Y", "run_R", "run_B", "run_Bo", "vol_vs30"]
for a, z in (("2025-02-28 00:00", "2025-03-03 12:00"), ("2025-03-04 10:00", "2025-03-06 12:00"), ("2025-03-06 12:00", "2025-03-08 06:00")):
    s = h1[(h1.index >= cw.T(a)) & (h1.index < cw.T(z))].copy()
    s.insert(0, "t", [cw.utc(int(x)) for x in s.index])
    print(s[COLS].round(2).to_string(index=False))
    print()

s = h4[(h4.index >= cw.T("2025-02-15")) & (h4.index < cw.T("2025-03-27"))].copy()
s.insert(0, "t", [cw.utc(int(x)) for x in s.index])
print(s[["t", "high", "low", "close", "width", "width3", "d_B", "d_Bo", "run_G"]].round(2).iloc[::3].to_string(index=False))
