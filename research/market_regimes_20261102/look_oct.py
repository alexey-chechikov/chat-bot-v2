"""Сентябрь–ноябрь 2026: где были 85k и касание «синей» у 82k (спор оператора с прежним Claude). Только описание."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import mr_data as md  # noqa: E402

m, h1, h4, d1, fund = md.build()
t0 = pd.Timestamp("2026-09-01", tz="UTC").timestamp()
d = d1[d1.index >= t0].copy()
h4s = h4[["close", "low", "high", "Y", "R", "B", "zone", "known"]]
rows = []
for t, r in d.iterrows():
    k = h4s[(h4s.index >= t) & (h4s.index < t + 86400)]
    rows.append((pd.to_datetime(t, unit="s").date(), r["open"], r["high"], r["low"], r["close"], r["sma100"],
                 r["reg0"], r["reg2"], k["B"].iloc[-1], k["Y"].iloc[-1], k["R"].iloc[-1], k["zone"].iloc[-1],
                 (k["low"] <= k["B"]).any()))
print("день | open high low close | SMA100 реж0 реж2 | 4H на конец дня: EMA200 TEMA100 TEMA200 зона | касание EMA200 4H")
for r in rows:
    print(f"{r[0]} | {r[1]:.0f} {r[2]:.0f} {r[3]:.0f} {r[4]:.0f} | {r[5]:.0f} {r[6]} {r[7]} | {r[8]:.0f} {r[9]:.0f} "
          f"{r[10]:.0f} {r[11]:+d} | {r[12]}")
