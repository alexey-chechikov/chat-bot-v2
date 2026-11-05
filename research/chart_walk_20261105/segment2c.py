"""Оборот: сколько тейков у лонга всё время и у правил участка 1 за 15.02–05.05, время в рынке, сумма лонгов с целью и без."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import rules  # noqa: E402
from segment2 import OUT, T0, T1  # noqa: E402

m, h1, h4, d1, fund = cw.load()
mk = cw.gridk.Market(m["ts"].to_numpy(), m["open"].to_numpy(), m["high"].to_numpy(), m["low"].to_numpy(), m["close"].to_numpy(), fund)
i0, i1 = mk.idx([T0 + 3600])[0], mk.idx([T1])[0]
for nm, s in (("лонг всё время", 1), ("шорт всё время", -1)):
    r = mk.run(np.array([i0]), np.array([i1]), s)[0]
    print(nm, "итог", round(float(r[0]), 2), "тейки $", round(float(r[1]), 2), "тейков", int(r[8]), "комиссии", round(float(r[2]), 2), "фандинг", round(float(r[3]), 2), "выход", round(float(r[4]), 2))
t = pd.read_csv(OUT / "segment2_legs_v1.csv")
print("v1: тейков", int(t["тейки_шт"].sum()), "итог", round(float(t["сетка_$"].sum()), 2), "ног", len(t))
print("время в рынке, % окна", round(float((t["t1"] - t["t0"]).sum() / (T1 - T0) * 100), 1))
L = t[t["сторона"] == "L"]
hit = L["почему_закрыта"].str.startswith("цель")
print("лонгов", len(L), "дошли до цели", int(hit.sum()), "сумма с целью", round(float(L.loc[hit, "сетка_$"].sum()), 2), "без цели", round(float(L.loc[~hit, "сетка_$"].sum()), 2))
S = t[t["сторона"] == "S"]
print("шортов", len(S), "сумма", round(float(S["сетка_$"].sum()), 2), "плюсовых", int((S["сетка_$"] > 0).sum()))
print("по типам шорта", S.groupby("тип")["сетка_$"].agg(["count", "sum"]).round(2).to_dict())
far = S["почему_закрыта"].str.startswith("далеко")
print("шорт закрыт по далеко", int(far.sum()), round(float(S.loc[far, "сетка_$"].sum()), 2), "остальные", round(float(S.loc[~far, "сетка_$"].sum()), 2))
print("цена", round(float(h1[h1["known"] == T0 + 3600]["close"].iloc[0])), round(float(h1[h1["known"] == T1]["close"].iloc[0])))
