"""Первый взгляд на участок: таблица 4ч и 1ч вокруг 95k, ширина пучка, голубые."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402

pd.set_option("display.width", 260, "display.max_columns", 60, "display.max_rows", 500)
m, h1, h4, d1, fund = cw.load()
print("минут", len(m), "h1", len(h1), "h4", len(h4), "конец", cw.utc(int(m["ts"].iloc[-1])))

a, b = cw.T("2025-02-15"), cw.T("2025-03-15")
s = h4[(h4.index >= a) & (h4.index < b)].copy()
s.insert(0, "t", [cw.utc(int(x)) for x in s.index])
cols = ["t", "close", "G", "Y", "R", "B", "B1", "d_G", "d_Y", "d_R", "d_B", "d_Bo", "a_G", "a_B", "width", "width_rank", "run_G", "run_Y", "run_B",
        "slope_B", "vol_vs30", "vol_trend", "ret24"]
print(s[cols].round(2).to_string(index=False))
