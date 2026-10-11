"""Сим ETH Auto (GinArea Dynamic Auto, выход по средней) — вторая попытка (10.10), с вариантами механики набора.

⚠️ ИТОГ 10.10: НЕ СОШЁЛСЯ. Шаг 0.1 — входов ×1.5–2.5, позиция ×2–3 против GinArea. Шаг 0.16 («шаг + ioo»)
подогнан на этом же клоне (оборот 8/12 месяцев в ±15%, сумма месяцев $1 520 против $1 471), но вне выборки
(клон 6227907209, шаг 0.2, eth_auto_oos.py) −33% медиана, 0/12 целей в ±25%; живой бот 4470088018 шагает ровно
на gs (0.2 → 0.21%, 0.4 → 0.41%), не на gs + ioo. Годовой итог прыгает −$5.8k…+$4.4k от мелких правил.
Копию ETH Auto на WEEX по этой модели не строить.

Эталон — движок GinArea, клон 5678633257 (so 0.4, ioo 0.06, шаг 0.1, цель 2.0, ордер 0.01, выход по средней):
год 25.09.2025–17.09.2026 и 12 помесячных тестов (state/ginarea_sweep_eth_border_0.jsonl, есть позиция, макс.
позиция, худший мешок). Первая попытка (tools/eth_auto_sim.py, вариант «док») дала закрыто/оборот как у GinArea
(0.92% против 0.95%), но входов ~×2 — значит, неверна частота набора. Варианты:
  per_bar  — не больше одного входа на сторону за минутную свечу;
  trail    — граница стороны тянется за ценой на so, пока у стороны нет позиции ('flat') / всегда ('all') / нет;
  reset    — после выхода стороны: заново от цены только её граница ('side') или обе ('both').
Граница шорта s_trig: цена ≥ → вход шорта по s_trig; дальше s_trig = max(s_trig·(1+ioo), вход·(1+шаг)),
граница лонга сдвигается вверх на ioo (документация: вход шорта двигает обе границы вверх). Зеркально для лонга.
Комиссия 0.05% на сторону (как OKX у GinArea); оборот — вход + выход."""
from __future__ import annotations

import json
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "backtests" / "frozen" / "ETHUSDT_1m_2y.csv"
FEE = 0.0005
MODE = "close" if "--close" in sys.argv else "ohlc"
STEP = next((float(a.split("=")[1]) for a in sys.argv if a.startswith("--step=")), 0.1)
YEAR = {"from": "2025-09-25", "to": "2026-09-17 09:20", "profit": 3483.51, "current_profit": 2946.46,
        "volume": 366232.6, "position": -1.75}


def load(a, b):
    d = pd.read_csv(SRC)
    d["ts"] = pd.to_datetime(d["ts"], unit="ms", utc=True)
    d = d.set_index("ts")[["open", "high", "low", "close"]].astype(float)
    return d[(d.index >= pd.Timestamp(a, tz="UTC")) & (d.index < pd.Timestamp(b, tz="UTC"))]


def bars(d, mode=None):
    o, h, l, c = (d[k].to_numpy() for k in ("open", "high", "low", "close"))
    up = c >= o
    p = np.empty((len(d), 4))
    p[:, 0], p[:, 1], p[:, 2], p[:, 3] = o, np.where(up, l, h), np.where(up, h, l), c
    if (mode or MODE) == "close":
        p[:, :] = c[:, None]
    return p


def run(P, target=2.0, step=None, so=0.4, ioo=0.06, qty=0.01, max_orders=800, per_bar=False, trail="none",
        reset="side", fee=FEE):
    T, g, s, sh = target / 100, (step or STEP) / 100, so / 100, ioo / 100
    sq = sqe = lq = lqe = 0.0
    ns = nl = 0
    p0 = P[0, 0]
    s_trig, l_trig = p0 * (1 + s), p0 * (1 - s)
    realized = turnover = 0.0
    max_pos = 0.0
    worst_bag = worst_tot = 0.0
    closes = 0
    for row in P:
        s_done = l_done = False
        for p in row:
            while p >= s_trig and ns + nl < max_orders and not (per_bar and s_done):
                e = s_trig
                sq += qty; sqe += qty * e; ns += 1
                turnover += qty * e; realized -= qty * e * fee
                s_trig = max(s_trig * (1 + sh), e * (1 + g))
                l_trig *= (1 + sh)
                s_done = True
            while p <= l_trig and ns + nl < max_orders and not (per_bar and l_done):
                e = l_trig
                lq += qty; lqe += qty * e; nl += 1
                turnover += qty * e; realized -= qty * e * fee
                l_trig = min(l_trig * (1 - sh), e * (1 - g))
                s_trig *= (1 - sh)
                l_done = True
            if trail == "all" or (trail == "flat" and sq == 0):
                s_trig = min(s_trig, p * (1 + s))
            if trail == "all" or (trail == "flat" and lq == 0):
                l_trig = max(l_trig, p * (1 - s))
            if sq > 0:
                ex = sqe / sq * (1 - T)
                if p <= ex:
                    realized += sqe - sq * ex - sq * ex * fee
                    turnover += sq * ex
                    sq = sqe = 0.0; ns = 0; closes += 1
                    s_trig = p * (1 + s)
                    if reset == "both":
                        l_trig = p * (1 - s)
            if lq > 0:
                ex = lqe / lq * (1 + T)
                if p >= ex:
                    realized += lq * ex - lqe - lq * ex * fee
                    turnover += lq * ex
                    lq = lqe = 0.0; nl = 0; closes += 1
                    l_trig = p * (1 - s)
                    if reset == "both":
                        s_trig = p * (1 + s)
        c = row[3]
        bag = (sqe - sq * c) + (lq * c - lqe)
        worst_bag = min(worst_bag, bag)
        worst_tot = min(worst_tot, realized + bag)
        max_pos = max(max_pos, abs(lq - sq))
    c = P[-1, 3]
    bag = (sqe - sq * c) + (lq * c - lqe)
    return {"net": realized + bag, "closed": realized, "turnover": turnover, "pos": lq - sq, "max_pos": max_pos,
            "worst_bag": worst_bag, "worst_tot": worst_tot, "closes": closes, "gross": max(sq, lq)}


VARIANTS = {f"bar={pb} trail={tr} reset={rs}": dict(per_bar=pb, trail=tr, reset=rs)
            for pb, tr, rs in product([False, True], ["none", "flat"], ["side", "both"])}


def err(a, b):
    return a / b - 1 if b else float("nan")


def main():
    months = [json.loads(x) for x in (ROOT / "state" / "ginarea_sweep_eth_border_0.jsonl").read_text().splitlines()
              if x.strip()]
    months.sort(key=lambda m: m["from"])
    data = {m["from"]: bars(load(m["from"], m["to"])) for m in months}
    year = bars(load(YEAR["from"], YEAR["to"]))
    only = [a for a in sys.argv[1:] if not a.startswith("--")] or list(VARIANTS)
    for name in only:
        kw = VARIANTS[name]
        y = run(year, **kw)
        print(f"\n=== {name}\nГОД: итог {y['net']:+,.0f} (GA {YEAR['current_profit']:+,.0f}) закрыто {y['closed']:,.0f} "
              f"(GA {YEAR['profit']:,.0f}) оборот {y['turnover']:,.0f} (GA {YEAR['volume']:,.0f}, {err(y['turnover'], YEAR['volume']):+.0%}) "
              f"позиция {y['pos']:+.2f} (GA {YEAR['position']:+.2f}) закрытий {y['closes']}")
        rows = []
        for m in months:
            r = run(data[m["from"]], **kw)
            rows.append({"мес": m["from"][:7], "итог": r["net"], "GA итог": m["current_profit"],
                         "закр": r["closed"], "GA закр": m["profit"],
                         "об×": r["turnover"] / m["volume"], "поз": r["pos"], "GA поз": m["position"],
                         "макс поз": r["max_pos"], "GA макс": m["max_pos"],
                         "мешок": r["worst_bag"], "GA мешок": m["worst_bag"]})
        t = pd.DataFrame(rows)
        print(t.round(2).to_string(index=False))
        ok_v = ((t["об×"] - 1).abs() <= 0.15).sum()
        ok_n = ((t["итог"] / t["GA итог"] - 1).abs() <= 0.15).sum()
        print(f"оборот ±15%: {ok_v}/12; итог ±15%: {ok_n}/12; медиана об× {t['об×'].median():.2f}; "
              f"корр. итога {np.corrcoef(t['итог'], t['GA итог'])[0, 1]:.2f}; сумма итога {t['итог'].sum():+,.0f} "
              f"(GA {t['GA итог'].sum():+,.0f})")


if __name__ == "__main__":
    main()
