"""Портфельная метрика по живым ботам (замечание внешнего разбора): чистый итог с открытой
позицией / максимальная просадка этого итога — вместо «закрытый доход / худший мешок» (0.496).
current_profit в снимках = закрытое + нереализованное (мешок) с начала жизни бота."""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
parts = []
for ch in pd.read_csv(ROOT / "ginarea_live" / "snapshots.csv",
                      usecols=["ts_utc", "bot_id", "bot_name", "profit", "current_profit", "status"], chunksize=500_000):
    parts.append(ch.dropna(subset=["bot_id", "current_profit"]))
d = pd.concat(parts)
d["ts"] = pd.to_datetime(d.ts_utc, utc=True, errors="coerce")
d = d.dropna(subset=["ts"]).sort_values("ts")
rows = []
for bid, g in d.groupby("bot_id"):
    days = (g.ts.iloc[-1] - g.ts.iloc[0]).days
    if days < 7:
        continue
    x = g.current_profit.to_numpy(float)
    closed = g.profit.to_numpy(float)
    net = x[-1] - x[0]
    dd = float((np.maximum.accumulate(x) - x).max())
    bag = closed - x                          # мешок = закрытое − итог (≥ 0, когда позиция в минусе)
    rows.append({"bot": str(g.bot_name.iloc[-1]).strip()[:28], "дней": days, "итог с мешком": round(net),
                 "закрыто": round(closed[-1] - closed[0]), "макс. просадка итога": round(dd),
                 "итог/просадка": round(net / dd, 2) if dd > 0 else np.nan,
                 "закрыто/худший мешок": round((closed[-1] - closed[0]) / bag.max(), 2) if bag.max() > 0 else np.nan})
t = pd.DataFrame(rows).sort_values("итог/просадка")
pd.set_option("display.width", 220)
print(t.to_string(index=False))
print(f"\nботов {len(t)}; медиана «итог с мешком / макс. просадка» {t['итог/просадка'].median():.2f}; "
      f"медиана «закрыто / худший мешок» {t['закрыто/худший мешок'].median():.2f}; "
      f"сумма итогов с мешком ${t['итог с мешком'].sum():+,.0f}, закрыто ${t['закрыто'].sum():+,.0f}")
