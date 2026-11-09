"""Что могло быть зарезано на биткоине из-за монет, ETH или XRP: все уже посчитанные варианты, только столбцы BTC. Счёт: итог выше опорного и просадка не глубже. Числа не пересчитываются, берутся из таблиц прогонов."""
from __future__ import annotations

import io
import subprocess
from pathlib import Path

import pandas as pd

pd.set_option("display.width", 220, "display.max_columns", 30, "display.max_rows", 100, "display.max_colwidth", 62)
R = "/Users/alexeychechikov/code/bot7"
OUT = Path(__file__).parent / "out"


def win(p):
    return pd.read_csv(io.BytesIO(subprocess.run(["git", "-C", R, "show", f"2449d0b:research/indicator_lab_win/out/{p}"], capture_output=True).stdout))


def main():
    f = pd.read_csv(OUT / "gpt_r3_flow.csv")
    print("== вариант A и его выходы, BTC", flush=True)
    print(f[f["ряд"] == "BTC"][["вариант", "n", "итог", "лонг", "шорт", "с2025", "просадка"]].to_string(index=False), flush=True)
    print("== монеты для тех же вариантов", flush=True)
    m = f[f["группа"] == "монеты"].groupby("вариант", sort=False)["итог"].sum().round()
    print(m.to_string(), flush=True)

    s = pd.read_csv(OUT / "w3_sweep_sum.csv")
    ref = s[s["вариант"].str.startswith("k2 выход R лонг:False шорт:False")].iloc[0]
    q = s[(s["BTC"] >= ref["BTC"]) & (s["BTC_пр"] >= ref["BTC_пр"]) & (s["вариант"] != ref["вариант"])]
    print(f"== мой просчёт 131 вариант, опорный +{ref['BTC']} / {ref['BTC_пр']}: лучше на BTC по итогу и просадке: {len(q)}", flush=True)
    print(q[["вариант", "BTC", "BTC_пр", "с2025_BTC", "ETH", "монеты", "лучше"]].to_string(index=False), flush=True)

    w = win("sweep_BTC_ETH_XRP.csv")
    b = w[w["вариант"] == "база R"].iloc[0]
    q = w[(w["BTC_итог"] > b["BTC_итог"]) & (w["BTC_просадка"] >= b["BTC_просадка"]) & (w["BTC_p1"] > 0) & (w["BTC_p2"] > 0) & (w["BTC_p3"] > 0)]
    print(f"== перебор Вина 2547: лучше базы R на BTC по итогу и просадке, все периоды плюс: {len(q)}; семейства", q["семейство"].value_counts().to_dict(), flush=True)
    print(q.sort_values("BTC_отн", ascending=False).head(10)[["семейство", "вариант", "BTC_итог", "BTC_просадка", "BTC_с2025", "BTC_p1", "BTC_p2", "BTC_p3", "ETH_итог"]].to_string(index=False), flush=True)

    z = win("fam_z.csv")
    pz = z[(z["размер"] == "риск 0.5-2")]
    print("== сборка Вина 384, столбцы BTC, лучшие по итог/просадка", flush=True)
    print(z.sort_values("BTC_отн", ascending=False).head(10)[["шорт", "лонг", "пауза", "размер", "BTC_итог", "BTC_просадка", "BTC_с2025", "BTC_p1", "BTC_p2", "BTC_p3", "ETH_итог"]].to_string(index=False), flush=True)

    i = win("fam_i.csv")
    q = i[i["слой"] == "плюс"]
    ref = q[q["вариант"] == "база"].iloc[0]
    r = q[(q["BTC_итог"] > ref["BTC_итог"]) & (q["BTC_просадка"] >= ref["BTC_просадка"] - 2)]
    print(f"== записки, слой Простое+, опорный +{ref['BTC_итог']} / {ref['BTC_просадка']}: лучше на BTC: {len(r)} из {len(q)}", flush=True)
    print(r.sort_values("BTC_итог", ascending=False).head(14)[["вариант", "BTC_итог", "BTC_просадка", "BTC_с2025", "BTC_p1", "BTC_p2", "BTC_p3", "Bitstamp_итог", "ETH_итог"]].to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
