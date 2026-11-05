"""Участок 2: обзор 4ч и список событий (пересечения линий, порядок линий, голубые). Плюс увеличенные куски скриншота."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402

SCR = cw.SCR
img = Image.open("/private/tmp/claude-501/-Users-alexeychechikov/279942d8-034f-4a29-bc43-ed7d07642e98/images/2.jpg")
img.crop((30, 50, 585, 460)).resize((1665, 1230), Image.LANCZOS).save(SCR / "s2_left.png")
img.crop((585, 50, 1035, 460)).resize((1350, 1230), Image.LANCZOS).save(SCR / "s2_right.png")

pd.set_option("display.width", 260, "display.max_columns", 60, "display.max_rows", 900)
m, h1, h4, d1, fund = cw.load()
for b in (h1, h4):
    lines = b[["G", "Y", "R"]]
    b["width3"] = (lines.max(axis=1) - lines.min(axis=1)) / b["close"] * 100
    b["stack"] = np.where((b["G"] > b["Y"]) & (b["Y"] > b["R"]), 1, np.where((b["G"] < b["Y"]) & (b["Y"] < b["R"]), -1, 0))

A, Z = cw.T("2025-03-05"), cw.T("2025-05-12")
s = h4[(h4.index >= A) & (h4.index < Z)].copy()
s.insert(0, "закр", [cw.utc(int(x)) for x in s["known"]])
print(s[["закр", "high", "low", "close", "G", "Y", "R", "B", "B1", "d_G", "d_Y", "d_B", "d_Bo", "width", "width3", "width_rank", "stack", "run_G", "run_Y", "run_B", "vol_vs30"]].round(2).iloc[::3].to_string(index=False))

print("\nсобытия 4ч: смена стороны линии и порядка")
ev = []
for i in range(1, len(s)):
    p, r = s.iloc[i - 1], s.iloc[i]
    for ln in ("run_G", "run_Y", "run_R", "run_B", "run_Bo"):
        if np.sign(p[ln]) != np.sign(r[ln]):
            ev.append((r["закр"], round(float(r["close"])), {"run_G": "G", "run_Y": "Y", "run_R": "R", "run_B": "B4", "run_Bo": "B1"}[ln], "над" if r[ln] > 0 else "под", f"было {int(p[ln])}"))
    if p["stack"] != r["stack"]:
        ev.append((r["закр"], round(float(r["close"])), "порядок", int(r["stack"]), f"было {int(p['stack'])}"))
e = pd.DataFrame(ev, columns=["закр", "цена", "линия", "что", "было"])
e = e[e["линия"].isin(["Y", "B4", "B1", "порядок"]) | (e["было"].str.replace("было ", "").astype(int).abs() >= 6)]
print(e.to_string(index=False))
