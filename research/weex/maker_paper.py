"""Бумажный maker-бот на объём по записанному стакану WEEX (state/weex_book), схемы 1 и 2 из
docs/WEEX_GPT_VOLUME_VARIANTS_2026-10-11.md. Ордеров нет — только оценка цены оборота.

Данные: верх стакана (3 уровня, при изменении, ~2 раза в секунду) и сделки тейкеров (m=1 — агрессивная продажа,
бьёт по бидам). Время — E (момент события на бирже), стакан и сделки сливаются по времени.

Очередь — консервативно: заявка встаёт в ХВОСТ очереди своей цены (впереди весь объём уровня в момент, когда наша
цена стала лучшей); отмены чужих заявок нас не продвигают. Исполнение — когда сделки по нашей цене съели очередь
впереди и наш объём, либо сделка прошла ХУЖЕ нашей цены, либо встречная лучшая цена дошла до нашей.

Схема 1 (последовательный maker): нет позиции → заявка у лучшей цены (лонг — бид, шорт — аск), живёт 5 с, потом
переставляется; после исполнения — выход лимиткой на +0.08% от входа; стоп 0.25% (рыночный, тейкер, по лучшей
встречной), 15 мин — рыночный выход. Фильтр: спред ≤ 0.03%.
Схема 2 (дальние котировки): две заявки на середина ∓0.08%, живут 60 с; первое исполнение снимает обе; выход к
исходной середине; стоп 0.5%; 30 мин — рыночный выход.
Размер — $30 на заявку (результат в $ пропорционален размеру; главное — цена $1 млн оборота).
Комиссии: мейкер 0.016%, тейкер 0.048%; «с возвратом» — комиссии 0 (бонус, пока действует).
Итог: оборот, сделки по причинам, $ до/после комиссий, цена $1 млн оборота, markout входа (куда пошла середина
через 1/5/30/60 с, в б.п., + = в нашу сторону)."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "state" / "weex_book"
MAKER = next((float(a.split("=")[1]) for a in sys.argv if a.startswith("--maker=")), 0.00016)
TAKER = next((float(a.split("=")[1]) for a in sys.argv if a.startswith("--taker=")), 0.00048)
USD = 30.0
HORIZ = (1, 5, 30, 60)


def load(sym: str):
    ev = []
    for f in sorted(DATA.glob(f"{sym}_*_book.csv")):
        for r in csv.DictReader(f.open()):
            ev.append((int(r["E"]), 0, float(r["b1"]), float(r["b1q"]), float(r["a1"]), float(r["a1q"])))
    for f in sorted(DATA.glob(f"{sym}_*_trades.csv")):
        for r in csv.DictReader(f.open()):
            ev.append((int(r["E"]), 1, float(r["p"]), float(r["q"]), int(r["m"]), 0.0))
    ev.sort(key=lambda x: (x[0], x[1]))
    return ev


class Order:
    """Лимитка в хвосте очереди. d=+1 покупка (исполняют агрессивные продажи), −1 продажа."""

    def __init__(self, d, px, q, t):
        self.d, self.px, self.q, self.t = d, px, q, t
        self.ahead = None                       # объём впереди — с момента, когда цена стала лучшей

    def on_book(self, b1, b1q, a1, a1q) -> bool:
        best, best_q, opp = (b1, b1q, a1) if self.d > 0 else (a1, a1q, b1)
        if self.ahead is None and best == self.px:
            self.ahead = best_q
        return (self.d > 0 and opp <= self.px) or (self.d < 0 and opp >= self.px)

    def on_trade(self, p, q, m) -> bool:
        hits_us = (m == 1) if self.d > 0 else (m == 0)  # покупку исполняет агрессивная продажа
        if not hits_us:
            return False
        if (self.d > 0 and p < self.px) or (self.d < 0 and p > self.px):
            return True                         # сделка прошла хуже нашей цены
        if p == self.px and self.ahead is not None:
            self.ahead -= q
            return self.ahead < -self.q + 1e-12
        return False


def simulate(ev, scheme: int, side: int, tick: float):
    """side: +1 лонг-циклы, −1 шорт-циклы (схема 1); для схемы 2 — обе стороны."""
    cfg = {1: dict(life=5_000, tgt=0.0008, stop=0.0025, hold=900_000),
           2: dict(life=60_000, tgt=0.0008, stop=0.005, hold=1_800_000)}[scheme]
    b1 = a1 = b1q = a1q = None
    quotes: list[Order] = []
    pos = None                                  # dict(d, e, q, t, exit: Order|None, anchor)
    res = {"vol": 0.0, "gross": 0.0, "fee": 0.0, "TP": 0, "SL": 0, "TIME": 0, "fills": [], "age": 0}
    mids = []

    def close(px, t, why, maker):
        nonlocal pos
        d, e, q = pos["d"], pos["e"], pos["q"]
        res["gross"] += d * q * (px - e)
        res["fee"] += q * px * (MAKER if maker else TAKER)
        res["vol"] += q * px
        res[why] += 1
        res["age"] = max(res["age"], t - pos["t"])
        pos = None

    for t, kind, x1, x2, x3, x4 in ev:
        if kind == 0:
            b1, b1q, a1, a1q = x1, x2, x3, x4
            mids.append((t, (b1 + a1) / 2))
            for o in list(quotes):
                if o.on_book(b1, b1q, a1, a1q):
                    quotes = [] if scheme == 2 else [z for z in quotes if z is not o]
                    pos = {"d": o.d, "e": o.px, "q": o.q, "t": t, "exit": None, "anchor": (b1 + a1) / 2}
                    res["fee"] += o.q * o.px * MAKER
                    res["vol"] += o.q * o.px
                    res["fills"].append((t, o.d, o.px))
                    break
        elif b1 is not None:
            for o in list(quotes):
                if o.on_trade(x1, x2, x3):
                    quotes = [] if scheme == 2 else [z for z in quotes if z is not o]
                    pos = {"d": o.d, "e": o.px, "q": o.q, "t": t, "exit": None, "anchor": (b1 + a1) / 2}
                    res["fee"] += o.q * o.px * MAKER
                    res["vol"] += o.q * o.px
                    res["fills"].append((t, o.d, o.px))
                    break
        if b1 is None:
            continue
        mid = (b1 + a1) / 2
        if pos:
            d, e = pos["d"], pos["e"]
            if pos["exit"] is None:
                tgt = e * (1 + d * cfg["tgt"])
                pos["exit"] = Order(-d, round(round(tgt / tick) * tick, 10), pos["q"], t)
            ex = pos["exit"]
            done = ex.on_book(b1, b1q, a1, a1q) if kind == 0 else ex.on_trade(x1, x2, x3)
            if done:
                close(ex.px, t, "TP", True)
            elif d * (mid / e - 1) <= -cfg["stop"]:
                close(b1 if d > 0 else a1, t, "SL", False)
            elif t - pos["t"] >= cfg["hold"]:
                close(b1 if d > 0 else a1, t, "TIME", False)
            continue
        if (a1 - b1) / mid > 0.0003:
            quotes = []
            continue
        quotes = [o for o in quotes if t - o.t < cfg["life"]]
        if not quotes:
            if scheme == 1:
                px = b1 if side > 0 else a1
                quotes = [Order(side, px, USD / px, t)]
            else:
                lo = round(round(mid * (1 - cfg["tgt"]) / tick) * tick, 10)
                hi = round(round(mid * (1 + cfg["tgt"]) / tick) * tick, 10)
                quotes = [Order(1, lo, USD / lo, t), Order(-1, hi, USD / hi, t)]
    # незакрытое — по середине на конце (рыночный выход)
    if pos and mids:
        close(mids[-1][1], mids[-1][0], "TIME", False)
    # markout входов
    mt = np.array([m[0] for m in mids])
    mv = np.array([m[1] for m in mids])
    mk = {h: [] for h in HORIZ}
    for t, d, px in res["fills"]:
        for h in HORIZ:
            i = np.searchsorted(mt, t + h * 1000)
            if i < len(mt):
                mk[h].append(d * (mv[i] / px - 1) * 1e4)
    res["markout"] = {h: (np.mean(v) if v else float("nan")) for h, v in mk.items()}
    res["span_h"] = (mids[-1][0] - mids[0][0]) / 3.6e6 if mids else 0
    return res


def main():
    syms = [a for a in sys.argv[1:] if not a.startswith("--")] or ["BTCUSDT", "ETHUSDT"]
    ticks = {"BTCUSDT": 0.1, "ETHUSDT": 0.01}
    for sym in syms:
        ev = load(sym)
        if not ev:
            print(sym, "нет данных")
            continue
        for scheme, side, name in ((1, 1, "схема 1, лонг-циклы"), (1, -1, "схема 1, шорт-циклы"), (2, 0, "схема 2")):
            r = simulate(ev, scheme, side, ticks.get(sym, 0.01))
            n = r["TP"] + r["SL"] + r["TIME"]
            net = r["gross"] - r["fee"]
            per_m = lambda v: -v / r["vol"] * 1e6 if r["vol"] else float("nan")  # noqa: E731
            mk = " ".join(f"{h}с {v:+.2f}" for h, v in r["markout"].items())
            print(f"{sym} {name}: {r['span_h']:.1f} ч, циклов {n} (тейк {r['TP']}, стоп {r['SL']}, время {r['TIME']}), "
                  f"оборот ${r['vol']:,.0f}; итог ${net:+.2f} (с возвратом ${r['gross']:+.2f}); цена $1 млн оборота "
                  f"${per_m(net):,.0f} (с возвратом ${per_m(r['gross']):,.0f}); markout входа б.п.: {mk}; "
                  f"дольше всего в позиции {r['age'] / 60000:.1f} мин")


if __name__ == "__main__":
    main()
