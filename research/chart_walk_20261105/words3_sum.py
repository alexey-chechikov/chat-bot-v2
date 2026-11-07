"""Свод w3_sweep.csv: по каждому варианту четыре ряда, монеты, с 2025, отношение итог/просадка."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import pos  # noqa: E402

pd.set_option("display.width", 300, "display.max_columns", 40, "display.max_rows", 400, "display.max_colwidth", 60)


def main():
    d = pd.read_csv(pos.OUT / "w3_sweep.csv")
    print("вариантов", d["вариант"].nunique(), "рядов", d["ряд"].nunique(), flush=True)
    d["отн"] = d["итог"] / d["просадка"].abs().clip(lower=1)
    base = d[d["вариант"] == "A+2/6"].set_index("ряд")
    rows = []
    for lab, g in d.groupby("вариант", sort=False):
        g = g.set_index("ряд")
        m = g[g["группа"] == "монеты"]
        mb = base[base["группа"] == "монеты"]
        row = {"вариант": lab}
        for k in ("BTC", "ETH", "Bitstamp", "XRP"):
            row[k] = g.loc[k, "итог"]
            row[k + "_пр"] = g.loc[k, "просадка"]
        row.update({"монеты": round(m["итог"].sum()), "лучше": int((m["итог"] > mb["итог"].reindex(m.index)).sum()), "монеты_пр": round(m["просадка"].median()), "с2025_BTC": g.loc["BTC", "с2025"], "с2025_ETH": g.loc["ETH", "с2025"], "с2025_монеты": round(m["с2025"].sum()), "отн_мон": round(m["отн"].median(), 2), "отн_BTC": round(g.loc["BTC", "отн"], 2), "n_BTC": int(g.loc["BTC", "n"])})
        rows.append(row)
    s = pd.DataFrame(rows)
    s.to_csv(pos.OUT / "w3_sweep_sum.csv", index=False)
    show = ["вариант", "BTC", "BTC_пр", "ETH", "ETH_пр", "Bitstamp", "Bitstamp_пр", "XRP", "XRP_пр", "монеты", "лучше", "монеты_пр", "отн_мон", "с2025_BTC", "с2025_ETH", "с2025_монеты", "n_BTC"]
    print(s[s["вариант"].isin(("A", "A+2/6"))][show].to_string(index=False), flush=True)
    grid = s[s["вариант"].str.startswith("k")]
    print("== сетка ядра, лучшие по монетам", flush=True)
    print(grid.sort_values("монеты", ascending=False).head(14)[show].to_string(index=False), flush=True)
    print("== сетка ядра, лучшие по отношению итог/просадка на монетах", flush=True)
    print(grid.sort_values("отн_мон", ascending=False).head(10)[show].to_string(index=False), flush=True)
    print("== добавки к простому правилу", flush=True)
    print(s[s["вариант"].str.startswith(("G|", "Y|"))][show].to_string(index=False), flush=True)
    print("== условие выстроенности при k2, выход G", flush=True)
    print(grid[grid["вариант"].str.startswith("k2 выход G")][show].to_string(index=False), flush=True)
    print("== линия выхода при k2 без выстроенности", flush=True)
    print(grid[grid["вариант"].str.contains("лонг:False шорт:False")][show].to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
