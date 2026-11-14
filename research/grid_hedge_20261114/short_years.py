"""Почему шорт системы в страховке в плюсе, если «шорт всегда убыточен»: шорты системы (под синей + под жёлтой) по
годам — (1) равным размером $1000 на ногу (вход 0.5 + добор 0.5, как в индикаторе без веса), (2) с весом системы w,
(3) размером страховки 0.5 × позиция сеток (BTC) на входе/доборе — то же, что в overlay. Издержка 0.068%/сторону."""
from __future__ import annotations

import json
from collections import defaultdict

import numpy as np
import pandas as pd

D = str(__import__("pathlib").Path(__file__).resolve().parent) + "/"   # ev.json (dump_signals.py), grid_hourly.npz (grid_sim.py)
SC = 0.00068
z = np.load(D + "grid_hourly.npz")
T, C, Q = z["t"], z["c"], z["q"]
pos_of_t = {int(x): i for i, x in enumerate(T)}
ev = json.load(open(D + "ev.json", encoding="utf-8"))

trades, cur = [], None
for e in ev:
    if e.get("side") != -1:
        continue
    if e["kind"] == "вход":
        cur = {"tag": e["tag"], "t0": e["t"], "p0": e["px"], "w": e.get("w", 1.0), "ta": None, "pa": None}
    elif e["kind"] == "добор" and cur:
        cur["ta"], cur["pa"] = e["t"], e["px"]
    elif e["kind"] == "выход" and cur:
        cur["t1"], cur["p1"] = e["t"], e["px"]
        trades.append(cur)
        cur = None
print("шортов системы:", len(trades), "открыт сейчас:", cur is not None)

rows = []
for tr in trades:
    legs = [(tr["t0"], tr["p0"])] + ([(tr["ta"], tr["pa"])] if tr["ta"] else [])
    eq_usd, w_usd, g_usd, gq = 0.0, 0.0, 0.0, 0.0
    for t, p in legs:
        r = (p - tr["p1"]) / p - 2 * SC                   # доходность ноги шорта после издержек
        eq_usd += 500 * r                                  # $500 на ногу (полная позиция $1000)
        w_usd += 500 * tr["w"] * r
        i = pos_of_t.get(int(t))
        q = 0.5 * Q[i] if i is not None else 0.0          # страховка k=1: 0.5 × позиция сеток, BTC
        g_usd += q * p * r
        gq += q * p
    rows.append({"year": pd.to_datetime(tr["t0"], unit="s").year, "tag": tr["tag"], "eq": eq_usd, "w": w_usd,
                 "g": g_usd, "g_notional": gq, "px": tr["p0"]})
df = pd.DataFrame(rows)
df = df[df["year"] >= 2018]
print("\nгод | сделок | равный размер $1000 | с весом системы | размер страховки (k=1) | средний номинал страховки")
for y, g in df.groupby("year"):
    print(f"{y} | {len(g):3d} | {g['eq'].sum():+8.0f}$ ({(g['eq'] > 0).mean():.0%} в плюсе) | {g['w'].sum():+8.0f}$ | "
          f"{g['g'].sum():+8.0f}$ | ${g['g_notional'].mean():,.0f}")
for lab, m in (("2018–2026", df["year"] >= 2018), ("2023–2026", df["year"] >= 2023), ("2025–2026", df["year"] >= 2025)):
    g = df[m]
    print(f"{lab}: сделок {len(g)}, равный ${g['eq'].sum():+,.0f}, с весом ${g['w'].sum():+,.0f}, "
          f"страховка ${g['g'].sum():+,.0f}")
for tag, g in df.groupby("tag"):
    print(f"  {tag}: {len(g)} сделок, равный ${g['eq'].sum():+,.0f} (2023+ ${g[g['year'] >= 2023]['eq'].sum():+,.0f}), "
          f"страховка ${g['g'].sum():+,.0f} (2023+ ${g[g['year'] >= 2023]['g'].sum():+,.0f})")
# где размер страховки большой — какие шорты: убыточные равным размером, но малые по страховке
df["win"] = df["eq"] > 0
print("\nсредний номинал страховки: у плюсовых шортов ${:,.0f}, у минусовых ${:,.0f}".format(
    df[df.win]["g_notional"].mean(), df[~df.win]["g_notional"].mean()))
# корреляция номинала страховки с итогом шорта
print("корреляция (номинал страховки, итог шорта на $1000):", round(float(np.corrcoef(df["g_notional"], df["eq"])[0, 1]), 3))
for lab, m in (("2018–26", df["year"] >= 2018), ("2023–26", df["year"] >= 2023), ("2025–26", df["year"] >= 2025)):
    g = df[m]
    w, lo = g[g.win]["eq"], g[~g.win]["eq"]
    print(f"{lab}, на $1000: плюсовых {len(w)} из {len(g)}, средний плюс {w.mean():+.1f}$, средний минус {lo.mean():+.1f}$; "
          f"сумма плюсов {w.sum():+,.0f}$, минусов {lo.sum():+,.0f}$")
