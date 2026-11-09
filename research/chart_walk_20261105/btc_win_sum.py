"""Свод btc_win_review.csv: только биткоин, правила в шапке btc_win_review.py."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

pd.set_option("display.width", 240, "display.max_columns", 30, "display.max_rows", 120, "display.max_colwidth", 58)
OUT = Path(__file__).parent / "out"
SHOW = ["семейство", "вариант", "слой", "n", "итог", "просадка", "отн", "с2025", "отн1", "отн2", "Bs", "Bs_отн"]


def main():
    d = pd.read_csv(OUT / "btc_win_review.csv")
    err = d[d.get("ошибка").notna()] if "ошибка" in d else d.iloc[0:0]
    print("прогонов", len(d), "ошибок", len(err), err["семейство"].value_counts().to_dict() if len(err) else "", flush=True)
    d = d[d["итог"].notna()].copy()
    k1 = d[(d["вариант"] == "база") & (d["слой"] == "плюс")].iloc[0]
    k2 = d[(d["вариант"] == "противовес under_y w1.0 отмена Y") & (d["слой"] == "плюс")].iloc[0]
    base = d[(d["вариант"] == "база") & (d["слой"] == "постоянный")].iloc[0]
    print(pd.DataFrame([base, k1, k2])[SHOW + ["итог1", "пр1", "итог2", "пр2"]].to_string(index=False), flush=True)

    d["мин"] = np.minimum(d["отн1"] / k1["отн1"], d["отн2"] / k1["отн2"])
    c = d[(d["отн1"] > k1["отн1"]) & (d["отн2"] > k1["отн2"]) & (d["Bs_отн"] > k1["Bs_отн"]) & (d["итог"] >= k1["итог"])]
    print(f"== лучше Простое+ в обеих частях, на Bitstamp и по итогу: {len(c)} из {len(d)}; семейства", c["семейство"].value_counts().to_dict(), flush=True)
    print(c.sort_values("мин", ascending=False).head(22)[SHOW].to_string(index=False), flush=True)
    c2 = d[(d["отн1"] > k2["отн1"]) & (d["отн2"] > k2["отн2"]) & (d["Bs_отн"] > k2["Bs_отн"]) & (d["итог"] >= k2["итог"])]
    print(f"== лучше и Простое+, и шорта под жёлтой: {len(c2)}", flush=True)
    print(c2.sort_values("мин", ascending=False).head(14)[SHOW].to_string(index=False), flush=True)

    print("== в каждом семействе лучший только по 2018–22, слои Простое+ и сборка; что он дал потом", flush=True)
    q = d[d["слой"].isin(["Простое+", "плюс", "сборка"])]
    rows = []
    for fam, g in q.groupby("семейство"):
        b = g.sort_values("отн1", ascending=False).iloc[0]
        rows.append({"семейство": fam, "вариантов": len(g), "вариант": b["вариант"], "отн1": b["отн1"], "отн2": b["отн2"], "Bs_отн": b["Bs_отн"], "итог": b["итог"], "просадка": b["просадка"], "лучше части 2 Простое+": bool(b["отн2"] > k1["отн2"]), "связь_частей": round(float(g["отн1"].rank().corr(g["отн2"].rank())), 2)})
    print(pd.DataFrame(rows).to_string(index=False), flush=True)

    hi1 = q["отн1"] > k1["отн1"]
    hi2 = q["отн2"] > k1["отн2"]
    print(f"контроль: лучше в части 2 среди всех {hi2.mean() * 100:.0f}%, среди лучших в части 1 {hi2[hi1].mean() * 100:.0f}%; лучше в обеих {(hi1 & hi2).sum()} из {len(q)}; связь рангов частей {q['отн1'].rank().corr(q['отн2'].rank()):.2f}", flush=True)
    c.sort_values("мин", ascending=False).to_csv(OUT / "btc_win_candidates.csv", index=False)


if __name__ == "__main__":
    main()
