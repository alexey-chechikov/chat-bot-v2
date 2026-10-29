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
- 25.10 (аудит GPT R2): PnL недели = закрыто − комиссии − фандинг + мешок на конце − мешок стартовых лотов по
  цене старта (открытие первой минуты окна); «с мешком от входа» — прежний итог, включает убыток до недели.
- Выравнивание (оператор): итог на единицу плотности — $1000 на 1% хода; плотность = ордер × цена / шаг, взвешенная по
  времени действия каждого размера.
- 28.10 (разбор GPT a7d799b, §3): тейк вычитает из лотов ИСПОЛНЕННЫЙ объём, а не снимает лот целиком (частичный —
  остаток живёт); повторный отчёт той же заявки — по курсору cum_qty (прирост один раз), «тейков» = заявок, не строк;
  стоящий на старте вход исполняется своим объёмом; окно биржи начинается с той же минуты, что и бэктест (строки
  между T0 и первой полной минутой — отдельным счётчиком); фандинг строки «биржа» — оценка: объём лотов бота по
  журналу × цена × ставка Binance в моменты расчёта (фактический фандинг WEEX — по символу целиком, всех сеток и
  ручных, отдельной строкой); лоты на конце сверяются с учётом сетки по (цена входа, объём), а не по числу.
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


W0 = (int(T0) // 60 + 1) * 60                                 # первая полная минута окна — общая для бэктеста и биржи
EPS = 1e-12


def load(sym: str, t_end: float | None = None):
    d = pd.read_csv(SRC[sym])
    d = d[d["ts"] // 1000 >= W0]
    if t_end is not None:
        d = d[d["ts"] // 1000 < t_end]
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
    pending_q = float(e0["qty"]) if e0 and e0.get("qty") is not None else None   # и его собственный объём
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
            qf = pending_q if pending is not None and lvl == pending and pending_q else q
            if p <= lvl and len(lots) < mx and max(cost, qty * lvl) + qf * lvl <= cap:
                lots.append([lvl, qf, round_tick(lvl * (1 + tgt), tick, up=True)])
                fee += qf * lvl * MAKER
                vol += qf * lvl
                ent += 1
                pending = pending_q = None
    pe = closes[-1]
    return {"ent": ent, "tk": tk, "vol": vol, "real": real, "fee": fee, "fund": fund, "lots": len(lots),
            "qty": sum(x[1] for x in lots), "bag": sum(x[1] * (pe - x[0]) for x in lots)}


def _reduce(lots: list, entry: float, q: float) -> float:
    """Вычесть исполненный объём тейка из лотов: сначала лот с ближайшей ценой входа, остаток — со следующих.
    → объём, который не нашёл лота (0 — всё сошлось)."""
    left = q
    while left > EPS and lots:
        j = min(range(len(lots)), key=lambda i: abs(lots[i][0] - entry))
        take = min(left, lots[j][1])
        lots[j][1] -= take
        left -= take
        if lots[j][1] <= EPS:
            lots.pop(j)
    return left


def live(name: str, g: dict, t_end: float, pe: float, funding: dict | None = None,
         px_at: dict | None = None) -> dict:
    """Биржа по журналу сетки: прирост исполнения каждой заявки — один раз (курсор cum_qty по order_id);
    фандинг — оценка по лотам бота в моменты расчёта (funding: минута → ставка, px_at: минута → цена)."""
    lots = [[float(x["entry"]), float(x["qty"])] for x in g["sides"]["LONG"]["lots"]]
    cur: dict[tuple, float] = {}
    orders = {"вход": set(), "тейк": set()}
    ent = tk = 0
    vol = real = fee = fund = 0.0
    unmatched = 0.0
    gap_rows = 0
    rows = []
    for line in open(ST + JOURNAL[name], encoding="utf-8"):
        r = json.loads(line)
        if r.get("dry") or r.get("side") != "LONG":
            continue
        t = ts(r["ts"])
        if T0 < t < W0:
            gap_rows += 1                                         # между стартом и первой полной минутой окна
        if W0 <= t <= t_end:
            rows.append((t, r))
    rows.sort(key=lambda x: x[0])
    fts = sorted(m * 60 for m in (funding or {}) if W0 <= m * 60 <= t_end)
    fi = 0

    def settle(upto: float) -> None:
        nonlocal fi, fund
        while fi < len(fts) and fts[fi] <= upto:
            m = fts[fi] // 60
            p = (px_at or {}).get(m)
            if p is not None:
                fund += sum(x[1] for x in lots) * p * funding[m]
            fi += 1

    for t, r in rows:
        settle(t)
        kind = r.get("kind") or ""
        if kind not in ("вход", "тейк"):
            if "комисси" in kind:                          # 25.10 R3: поздняя комиссия — без qty/price
                fee += float(r.get("fee") or 0)
            continue
        q, px = float(r["qty"]), float(r["price"])
        oid = r.get("order_id")
        if oid is not None and r.get("cum_qty") is not None:
            key = (kind, oid)
            q = float(r["cum_qty"]) - cur.get(key, 0.0)
            if q <= EPS:
                continue                                   # повтор отчёта той же заявки
            cur[key] = float(r["cum_qty"])
            new_order = oid not in orders[kind]
            orders[kind].add(oid)
        else:
            new_order = True
        if kind == "вход":
            ent += new_order
            lots.append([px, q])
        else:
            tk += new_order
            real += float(r.get("pnl") or 0)
            unmatched += _reduce(lots, float(r.get("entry") or 0), q)
        fee += float(r.get("fee") or 0)
        vol += q * px
    settle(t_end)
    return {"ent": ent, "tk": tk, "vol": vol, "real": real, "fee": fee, "fund": fund, "lots": len(lots),
            "qty": sum(x[1] for x in lots), "bag": sum(x[1] * (pe - x[0]) for x in lots), "lot_list": lots,
            "unmatched_qty": unmatched, "gap_rows": gap_rows}


def lots_match(journal_lots: list, state_lots: list, tick: float) -> tuple[int, int]:
    """Лоты по журналу против учёта сетки по (цена входа с точностью до тика, объём): → (совпало, всего различий)."""
    a = sorted((round(x[0] / tick), round(x[1], 8)) for x in journal_lots)
    b = sorted((round(float(x["entry"]) / tick), round(float(x["qty"]), 8)) for x in state_lots)
    from collections import Counter
    ca, cb = Counter(a), Counter(b)
    same = sum((ca & cb).values())
    return same, sum((ca - cb).values()) + sum((cb - ca).values())


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
        p0 = pts[0][0]                                       # цена старта окна (открытие первой минуты)
        px_at = {int(t) // 60: float(c) for t, c in zip(tms, closes)}
        for name in names:
            g = snap["grids"][name]
            cfg = g["config"]
            s = sim(name, g, cfg, tms, pts, closes, funding)
            lv = live(name, g, t_end, pe, funding, px_at)
            st = json.load(open(ST + STATE[name]))
            now_lots = len(st["LONG"]["lots"])
            lv["match"] = lots_match(lv["lot_list"], st["LONG"]["lots"], float(cfg["price_tick"]))
            dens = density(name, cfg, pe, t_end)
            bag0 = sum(float(x["qty"]) * (p0 - float(x["entry"])) for x in g["sides"]["LONG"]["lots"])
            rows.append((name, sym, s, lv, dens, now_lots, bag0))
        print(f"{sym}: окно {datetime.fromtimestamp(T0, timezone.utc):%d.%m %H:%M} … "
              f"{datetime.fromtimestamp(t_end, timezone.utc):%d.%m %H:%M} UTC ({(t_end - T0) / 86400:.1f} сут), "
              f"цена на конце {pe:,.2f}")
    print(f"\n{'сетка':<5} {'':<8} | {'входов':>6} {'тейков':>6} | {'объём $':>9} | {'закрыто':>8} {'комиссии':>8} "
          f"{'фандинг':>8} | {'лотов':>5} {'мешок':>8} | {'с мешком от входа':>17} | {'PnL недели':>10} | "
          f"{'PnL на $1000/1%':>15}")
    for name, sym, s, lv, dens, now_lots, bag0 in rows:
        for tag, x, fnd in (("бэктест", s, s["fund"]), ("биржа", lv, lv["fund"])):
            tot = x["real"] - x["fee"] + x["bag"] - (fnd or 0)
            ftxt = f"{-fnd:+8.2f}" if fnd is not None else f"{'—':>8}"
            print(f"{name:<5} {tag:<8} | {x['ent']:6d} {x['tk']:6d} | {x['vol']:9,.0f} | {x['real']:+8.2f} {-x['fee']:+8.2f} "
                  f"{ftxt} | {x['lots']:5d} {x['bag']:+8.2f} | {tot:+17.2f} | {tot - bag0:+10.2f} | "
                  f"{(tot - bag0) / dens * 1000:+15.2f}")
        d_tk = (s["tk"] - lv["tk"]) / lv["tk"] * 100 if lv["tk"] else 0
        d_real = (s["real"] - lv["real"]) / lv["real"] * 100 if lv["real"] else 0
        same, diff = lv["match"]
        print(f"{'':<5} {'разница':<8} | тейков {d_tk:+.0f}% · закрыто {d_real:+.0f}% · плотность ${dens:,.0f}/1% · "
              f"лоты по журналу {lv['lots']} против учёта сетки сейчас {now_lots} (по цене и объёму совпало {same}, "
              f"различий {diff}) · тейк без лота {lv['unmatched_qty']:.6f} · строк между стартом и первой минутой "
              f"{lv['gap_rows']} · мешок стартовых лотов по цене старта {bag0:+.2f}")
    print("\nФандинг строки «биржа» — оценка по лотам бота и ставке Binance; фактический фандинг WEEX — по символу "
          "целиком (все сетки символа и ручные позиции) — в /weex.")


if __name__ == "__main__":
    main()
