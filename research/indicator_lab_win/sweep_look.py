"""Сводка перебора по семействам: лучшие на BTC по отношению итог/просадка и что они дают на ETH и XRP. Смотрит только готовую таблицу."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

pd.set_option("display.width", 250, "display.max_columns", 40, "display.max_rows", 400, "display.max_colwidth", 44)
OUT = Path(__file__).parent / "out"


def main():
    d = pd.read_csv(OUT / "sweep_BTC_ETH_XRP.csv")
    base = d[d["вариант"] == "база R"].iloc[0]
    print("всего вариантов", len(d))
    cols = ["BTC_итог", "BTC_просадка", "BTC_отн", "BTC_с2025", "BTC_p1", "BTC_p2", "BTC_p3", "BTC_n", "ETH_итог", "ETH_просадка", "ETH_с2025", "XRP_итог", "XRP_просадка", "XRP_с2025"]
    print(d[d["семейство"] == "база"][["вариант"] + cols].to_string(index=False))
    for s in ("BTC", "ETH", "XRP"):
        d[f"{s}_отн2"] = d[f"{s}_итог"] / d[f"{s}_просадка"].abs().clip(lower=1)
    d["лучше_по_всем"] = (d["BTC_итог"] >= base["BTC_итог"]) & (d["BTC_просадка"] >= base["BTC_просадка"]) & (d["ETH_итог"] >= base["ETH_итог"]) & (d["ETH_просадка"] >= base["ETH_просадка"])
    d["годен_с2025"] = (d["BTC_с2025"] > 0) & (d["ETH_с2025"] > 0)
    d["годен_пер"] = (d["BTC_p1"] > 0) & (d["BTC_p2"] > 0) & (d["BTC_p3"] > 0)
    print("\nне хуже базы на BTC и ETH:", int(d["лучше_по_всем"].sum()), "; и плюс с 2025 на обоих:", int((d["лучше_по_всем"] & d["годен_с2025"]).sum()), "; и все периоды BTC:", int((d["лучше_по_всем"] & d["годен_с2025"] & d["годен_пер"]).sum()))
    for fam, g in d.groupby("семейство", sort=False):
        if fam == "база":
            continue
        print(f"\n--- {fam}: {len(g)} вариантов; выше базы по BTC итог {int((g['BTC_итог'] > base['BTC_итог']).sum())}, по отн {int((g['BTC_отн2'] > base['BTC_итог'] / abs(base['BTC_просадка'])).sum())}; медиана BTC {g['BTC_итог'].median():.0f}, ETH {g['ETH_итог'].median():.0f}, XRP {g['XRP_итог'].median():.0f}")
        print(g.sort_values("BTC_отн2", ascending=False).head(int(sys.argv[1]) if len(sys.argv) > 1 else 6)[["вариант"] + cols].to_string(index=False))
    q = d[d["лучше_по_всем"]].sort_values("BTC_отн2", ascending=False)
    print("\n=== не хуже базы на BTC и ETH, лучшие\n", q.head(30)[["семейство", "вариант"] + cols].to_string(index=False))
    print("\n=== плюс с 2025 на BTC и ETH, лучшие по BTC\n", d[d["годен_с2025"]].sort_values("BTC_отн2", ascending=False).head(25)[["семейство", "вариант"] + cols].to_string(index=False))


if __name__ == "__main__":
    main()
