"""Недельная сверка «как должны были отработать — как отработали» (оператор 24.10: «прогони свой прогноз, как должны были
отработать и как реально отработали: объём, прибыль, комиссии — всё; выровняй ордера относительно шага»).

ПРАВИЛА:
- Окно: с официального старта недели 18.10 16:15:21 UTC (state/grid_compare_start_20261018T161521Z.json) по последнюю
  минуту копии frozen 1m Binance spot.
- Бэктест: старт с лотов и стоящего входа снимка; правила движка — следующий вход от НИЖНЕГО лота на шаг ниже, округление
  вниз к тику; лимитка исполняется по своей цене при касании (как в калибровке 19–21.10); тейк каждого лота по
  его цели (округление вверх); потолок max(себестоимость, объём×цена) + вход ≤ max_notional и число лотов ≤ max; мейкер
  0.016% на каждое исполнение; путь минуты path4; режим всю неделю — лонг (смены не было).
- Настройки по времени (снимки и применённые команды): B34/B49/B89 — ордер 0.0012 с 18.10 16:15, 0.0006 с 18.10 19:40:17,
  0.0012 с 19.10 09:30:07, 0.0006 с 22.10 12:14:05 (и потолок $4 462 / $4 361 / $3 709, лотов 61/59/56); BTC 0.6/1.4
  0.0012 / $12 000 / 50 и ETH 0.6/1.4 0.020 / $2 500 / 50 — без изменений.
- Биржа: журналы state/weex_grid*_journal.jsonl (живые строки) в том же окне: входы, тейки, объём, закрыто (gross),
  комиссии; лоты на конце — снимок + входы − тейки (сверяются с учётом сетки сейчас, если окно до «сейчас»).
- Мешок на конце — по одной цене (закрытие последней минуты копии) и для бэктеста, и для биржи.
- Выравнивание (оператор): итог на единицу плотности — $1000 на 1% хода; плотность = ордер × цена / шаг, взвешенная по
  времени действия каждого размера.
Запуск: week_reconcile.py --btc=<копия> --eth=<копия>
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

ARG = {a.split("=", 1)[0]: a.split("=", 1)[1] for a in sys.argv[1:] if "=" in a}
SRC = {"BTCUSDT": ARG.get("--btc", "/Users/alexeychechikov/code/bot7/backtests/frozen/BTCUSDT_1m_2y.csv"),
       "ETHUSDT": ARG.get("--eth", "/Users/alexeychechikov/code/bot7/backtests/frozen/ETHUSDT_1m_2y.csv")}
ST = "/Users/alexeychechikov/code/bot7/state/"
SNAP = ST + "grid_compare_start_20261018T161521Z.json"
JOURNAL = {"BTC": "weex_grid_journal.jsonl", "ETH": "weex_grid_eth_journal.jsonl", "B34": "weex_grid_b34_journal.jsonl",
           "B49": "weex_grid_b49_journal.jsonl", "B89": "weex_grid_b89_journal.jsonl"}
STATE = {"BTC": "weex_grid_state.json", "ETH": "weex_grid_eth_state.json", "B34": "weex_grid_b34_state.json",
         "B49": "weex_grid_b49_state.json", "B89": "weex_grid_b89_state.json"}
MAKER = 0.00016


def ts(s: str) -> float:
    return datetime.fromisoformat(s).timestamp()


T0 = ts("2026-10-18T16:15:21+00:00")
SCHEDULE = {
    "B34": [(T0, "0.0012", 3000.0, 30), (ts("2026-10-18T19:40:17+00:00"), "0.0006", 3000.0, 30),
            (ts("2026-10-19T09:30:07+00:00"), "0.0012", 3000.0, 30), (ts("2026-10-22T12:14:05+00:00"), "0.0006", 4462.0, 61)],
    "B49": [(T0, "0.0012", 3000.0, 30), (ts("2026-10-18T19:40:17+00:00"), "0.0006", 3000.0, 30),
            (ts("2026-10-19T09:30:07+00:00"), "0.0012", 3000.0, 30), (ts("2026-10-22T12:14:05+00:00"), "0.0006", 4361.0, 59)],
    "B89": [(T0, "0.0012", 2000.0, 20), (ts("2026-10-18T19:40:17+00:00"), "0.0006", 2000.0, 20),
            (ts("2026-10-19T09:30:07+00:00"), "0.0012", 2000.0, 20), (ts("2026-10-22T12:14:05+00:00"), "0.0006", 3709.0, 56)],
    "BTC": [(T0, "0.0012", 12000.0, 50)],
    "ETH": [(T0, "0.020", 2500.0, 50)]}


def round_tick(x: float, tick: float, up: bool) -> float:
    k = x / tick
    return (math.ceil(k - 1e-9) if up else math.floor(k + 1e-9)) * tick


def load(sym: str, t_end: float | None = None):
    d = pd.read_csv(SRC[sym])
    d = d[d["ts"] // 1000 >= (int(T0) // 60 + 1) * 60]
    o, h, l, c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    up = c >= o
    pts = np.c_[o, np.where(up, l, h), np.where(up, h, l), c].tolist()
    return d["ts"].to_numpy(np.int64) // 1000, pts, c


def sim(name: str, g: dict, cfg: dict, tms, pts, closes, funding: dict) -> dict:
    step, tgt, tick = cfg["step_pct"] / 100, cfg["target_pct"] / 100, float(cfg["price_tick"])
    sched = SCHEDULE[name]
    lots = [[float(x["entry"]), float(x["qty"]), float(x["tp"])] for x in g["sides"]["LONG"]["lots"]]
    e0 = g["sides"]["LONG"].get("entry_order")
    pending = float(e0["price"]) if e0 else None                  # стоящий на старте вход
    ref = None
    ent = tk = 0
    vol = real = fee = fund = 0.0
    si = 0
    for k, (t, row) in enumerate(zip(tms, pts)):
        while si + 1 < len(sched) and t >= sched[si + 1][0]:
            si += 1
        q, cap, mx = float(sched[si][1]), sched[si][2], sched[si][3]
        rate = funding.get(int(t) // 60)
        if rate is not None and lots:
            fund += sum(x[1] for x in lots) * row[0] * rate
        for p in row:
            keep = []
            for lot in lots:
                if p >= lot[2]:
                    real += lot[1] * (lot[2] - lot[0])
                    fee += lot[1] * lot[2] * MAKER
                    vol += lot[1] * lot[2]
                    tk += 1
                else:
                    keep.append(lot)
            lots = keep
            if lots:
                ref = min(x[0] for x in lots)
                lvl = round_tick(ref * (1 - step), tick, up=False)
                pending = None
            else:
                # без лотов вход подтягивается вслед за ростом (trail_min_move_pct движка) от максимума — как regime_grid;
                # 24.10: первая версия считала уровень от текущей цены каждой точки — вход не исполнялся никогда
                ref = p if ref is None else max(ref, p)
                lvl = pending if pending else round_tick(ref * (1 - step), tick, up=False)
            cost, qty = sum(x[0] * x[1] for x in lots), sum(x[1] for x in lots)
            # стоящая лимитка на уровне исполняется по своей цене (так модель сошлась с биржей 19–21.10: ±1–7%)
            if p <= lvl and len(lots) < mx and max(cost, qty * lvl) + q * lvl <= cap:
                lots.append([lvl, q, round_tick(lvl * (1 + tgt), tick, up=True)])
                fee += q * lvl * MAKER
                vol += q * lvl
                ent += 1
                pending = None
    pe = closes[-1]
    return {"ent": ent, "tk": tk, "vol": vol, "real": real, "fee": fee, "fund": fund, "lots": len(lots),
            "qty": sum(x[1] for x in lots), "bag": sum(x[1] * (pe - x[0]) for x in lots)}


def live(name: str, g: dict, t_end: float, pe: float) -> dict:
    lots = [[float(x["entry"]), float(x["qty"])] for x in g["sides"]["LONG"]["lots"]]
    ent = tk = 0
    vol = real = fee = 0.0
    for line in open(ST + JOURNAL[name], encoding="utf-8"):
        r = json.loads(line)
        if r.get("dry") or r.get("side") != "LONG" or not (T0 < ts(r["ts"]) <= t_end):
            continue
        q, px = float(r["qty"]), float(r["price"])
        if r.get("kind") == "вход":
            ent += 1
            lots.append([px, q])
        elif r.get("kind") == "тейк":
            tk += 1
            real += float(r.get("pnl") or 0)
            e = float(r.get("entry") or 0)
            j = min(range(len(lots)), key=lambda i: abs(lots[i][0] - e) + abs(lots[i][1] - q) * 1e6) if lots else None
            if j is not None:
                lots.pop(j)
        else:
            continue
        fee += float(r.get("fee") or 0)
        vol += q * px
    return {"ent": ent, "tk": tk, "vol": vol, "real": real, "fee": fee, "lots": len(lots),
            "qty": sum(x[1] for x in lots), "bag": sum(x[1] * (pe - x[0]) for x in lots), "lot_list": lots}


def density(name: str, cfg: dict, price: float, t_end: float) -> float:
    """$ на 1% хода, взвешенно по времени действия каждого размера ордера."""
    sched = SCHEDULE[name] + [(t_end, None, None, None)]
    tot = sum((b[0] - a[0]) * float(a[1]) for a, b in zip(sched, sched[1:]))
    q = tot / (t_end - T0)
    return q * price / cfg["step_pct"]


def main():
    snap = json.load(open(SNAP))
    rows = []
    for sym, names in (("BTCUSDT", ("BTC", "B34", "B49", "B89")), ("ETHUSDT", ("ETH",))):
        tms, pts, closes = load(sym)
        fr = pd.read_csv(f"/Users/alexeychechikov/code/bot7/backtests/frozen/{sym}_funding_full.csv")
        funding = {int(t) // 60000: float(r) for t, r in zip(fr["fundingTime"], fr["fundingRate"])}
        t_end = float(tms[-1]) + 60
        pe = closes[-1]
        for name in names:
            g = snap["grids"][name]
            cfg = g["config"]
            s = sim(name, g, cfg, tms, pts, closes, funding)
            lv = live(name, g, t_end, pe)
            st = json.load(open(ST + STATE[name]))
            now_lots = len(st["LONG"]["lots"])
            dens = density(name, cfg, pe, t_end)
            rows.append((name, sym, s, lv, dens, now_lots))
        print(f"{sym}: окно {datetime.fromtimestamp(T0, timezone.utc):%d.%m %H:%M} … "
              f"{datetime.fromtimestamp(t_end, timezone.utc):%d.%m %H:%M} UTC ({(t_end - T0) / 86400:.1f} сут), "
              f"цена на конце {pe:,.2f}")
    print(f"\n{'сетка':<5} {'':<8} | {'входов':>6} {'тейков':>6} | {'объём $':>9} | {'закрыто':>8} {'комиссии':>8} "
          f"{'фандинг':>8} | {'лотов':>5} {'мешок':>8} | {'итог':>8} | {'на $1000/1%':>11}")
    for name, sym, s, lv, dens, now_lots in rows:
        for tag, x, fnd in (("бэктест", s, s["fund"]), ("биржа", lv, None)):
            tot = x["real"] - x["fee"] + x["bag"] - (fnd or 0)
            ftxt = f"{-fnd:+8.2f}" if fnd is not None else f"{'—':>8}"
            print(f"{name:<5} {tag:<8} | {x['ent']:6d} {x['tk']:6d} | {x['vol']:9,.0f} | {x['real']:+8.2f} {-x['fee']:+8.2f} "
                  f"{ftxt} | {x['lots']:5d} {x['bag']:+8.2f} | {tot:+8.2f} | {tot / dens * 1000:+11.2f}")
        d_tk = (s["tk"] - lv["tk"]) / lv["tk"] * 100 if lv["tk"] else 0
        d_real = (s["real"] - lv["real"]) / lv["real"] * 100 if lv["real"] else 0
        print(f"{'':<5} {'разница':<8} | тейков {d_tk:+.0f}% · закрыто {d_real:+.0f}% · плотность ${dens:,.0f}/1% · "
              f"лоты по журналу {lv['lots']} против учёта сетки сейчас {now_lots}")


if __name__ == "__main__":
    main()
