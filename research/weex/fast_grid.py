"""Быстрый прогон сетки WEEX (логика движка services/weex_grid после 09.10, правило GinArea):
- сторона LONG / SHORT независимо (хедж-режим), ордер фиксированного размера;
- вход — лимитка на шаг от КРАЙНЕГО ОТКРЫТОГО лота (лонг — нижнего, шорт — верхнего);
  без позиции опорная цена тянется за ценой (лонг — за максимумом, шорт — за минимумом);
- тейк каждого лота — лимитка на entry × (1 ± цель); один вход за точку пути (как один
  ордер на входе у движка);
- потолок позиции на сторону (USD) и число ордеров;
- комиссия мейкера на каждую сторону; фандинг не учитывается.
Путь минуты: open → (low/high по цвету) → close, 4 точки.
Итог — полный капитал: закрыто − комиссии + мешок; по месяцам — изменение капитала."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

DATA = Path(__file__).with_name("data")
MAKER = 0.00016


def load(sym: str, a: str | None = None, b: str | None = None):
    rows = list(csv.reader((DATA / f"{sym}_1m.csv").open()))[1:]
    ts = np.array([int(r[0]) // 1000 for r in rows], dtype=np.int64)
    o, h, l, c = (np.array([float(r[i]) for r in rows]) for i in (1, 2, 3, 4))
    m = np.ones(len(ts), bool)
    if a:
        m &= ts >= int(datetime.fromisoformat(a).replace(tzinfo=timezone.utc).timestamp())
    if b:
        m &= ts < int(datetime.fromisoformat(b).replace(tzinfo=timezone.utc).timestamp())
    return ts[m], o[m], h[m], l[m], c[m]


def path4(o, h, l, c):
    up = c >= o
    p = np.empty((len(o), 4))
    p[:, 0] = o
    p[:, 1] = np.where(up, l, h)
    p[:, 2] = np.where(up, h, l)
    p[:, 3] = c
    return p


@dataclass
class Side:
    d: int                                   # +1 лонг, −1 шорт
    lots: list = field(default_factory=list)  # [entry, qty, tp]
    ref: float | None = None
    realized: float = 0.0
    fees: float = 0.0
    turnover: float = 0.0
    tps: int = 0
    entries: int = 0


def run(sym_data, sides=("LONG", "SHORT"), step=0.2, target=0.21, order_usd=100.0, cap_usd=4000.0,
        max_orders=50, fee=MAKER, order_qty: float | None = None, cut_ts: int | None = None):
    """order_qty — фиксированный объём в монете (как у живой сетки); иначе — order_usd / цена уровня.
    cut_ts — момент, с которого считается непрерывный результат второй части окна (без обнуления)."""
    ts, o, h, l, c = sym_data
    pts = path4(o, h, l, c)
    st = {s: Side(1 if s == "LONG" else -1) for s in sides}
    g, t = step / 100, target / 100
    months = []
    cur_m = None
    worst = 0.0
    eq_cut = None
    peak, max_dd = 0.0, 0.0
    for i in range(len(ts)):
        if cut_ts is not None and eq_cut is None and ts[i] >= cut_ts:
            # капитал на ГРАНИЦЕ — до первой сделки второй части, по закрытию последней минуты первой
            # (10.10, разбор GPT: брался после обработки минуты среза и только на часовых точках)
            pc = c[i - 1] if i > 0 else o[i]
            eq_cut = sum(s.realized - s.fees + sum(s.d * x[1] * (pc - x[0]) for x in s.lots) for s in st.values())
        for p in pts[i]:
            for s in st.values():
                d = s.d
                # тейки
                if s.lots:
                    keep = []
                    for lot in s.lots:
                        e, q, tp = lot
                        if (d > 0 and p >= tp) or (d < 0 and p <= tp):
                            s.realized += d * q * (tp - e)
                            s.fees += fee * q * tp
                            s.turnover += q * tp
                            s.tps += 1
                        else:
                            keep.append(lot)
                    s.lots = keep
                # опорная цена
                if s.lots:
                    s.ref = min(x[0] for x in s.lots) if d > 0 else max(x[0] for x in s.lots)
                elif s.ref is None:
                    s.ref = p
                else:
                    s.ref = max(s.ref, p) if d > 0 else min(s.ref, p)
                # вход
                lvl = s.ref * (1 - d * g)
                if len(s.lots) < max_orders and ((d > 0 and p <= lvl) or (d < 0 and p >= lvl)):
                    q = order_qty if order_qty else order_usd / lvl
                    cost = sum(x[1] * x[0] for x in s.lots)
                    value = sum(x[1] for x in s.lots) * p
                    if max(cost, value) + q * lvl <= cap_usd:     # потолок как в движке (с 10.10)
                        e = lvl                # лимитка исполняется по своему уровню
                        s.lots.append([e, q, e * (1 + d * t)])
                        s.fees += fee * q * e
                        s.turnover += q * e
                        s.entries += 1
        # капитал и мешок — по закрытию КАЖДОЙ минуты (10.10, разбор GPT: раз в час занижало просадку)
        px = c[i]
        bag = sum(s.d * x[1] * (px - x[0]) for s in st.values() for x in s.lots)
        eq = sum(s.realized - s.fees for s in st.values()) + bag
        if i % 1440 == 0 or i == len(ts) - 1:
            m = datetime.fromtimestamp(int(ts[i]), timezone.utc).strftime("%Y-%m")
            if m != cur_m:
                if cur_m is not None:
                    months.append((cur_m, last_eq))
                cur_m = m
        last_eq = eq
        worst = min(worst, bag)
        peak = max(peak, eq)
        max_dd = min(max_dd, eq - peak)
    months.append((cur_m, last_eq))
    px = c[-1]
    res = {
        "тейков": sum(s.tps for s in st.values()),
        "оборот": sum(s.turnover for s in st.values()),
        "закрыто": sum(s.realized for s in st.values()),
        "комиссии": sum(s.fees for s in st.values()),
        "мешок": sum(s.d * x[1] * (px - x[0]) for s in st.values() for x in s.lots),
        "худший мешок": worst,
        "по сторонам": {k: round(float(s.realized - s.fees + sum(s.d * x[1] * (px - x[0]) for x in s.lots)), 2)
                        for k, s in st.items()},
    }
    res["итог"] = res["закрыто"] - res["комиссии"] + res["мешок"]
    res["просадка капитала"] = max_dd                        # от пика до дна по закрытиям минут
    if eq_cut is not None:
        res["2-я часть непрерывно"] = res["итог"] - eq_cut
        res["1-я часть непрерывно"] = eq_cut
    prev = 0.0
    res["по месяцам"] = []
    for m, e in months:
        res["по месяцам"].append((m, round(e - prev, 2)))
        prev = e
    return res
