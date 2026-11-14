"""Имитатор биржи: хедж-режим, рыночные / post-only / стоп-ордера, частичные исполнения, сбои ответов.

Для тестов исполнителя и для бумажного прогона на живых ценах (runner --paper). Цена двигается через move(price) или
bar(o, h, l, c) (путь o → ближний экстремум → дальний → c). Лимитка исполняется, только если цена прошла СКВОЗЬ уровень
(как в замере research/sigexec_20261112). Сбои: fail_next(op, mode) — "reject", "unknown_placed" (ордер встал, ответ
потерян), "unknown_lost" (ответ потерян, ордера нет), "incomplete" (поиск не дал ответа); partial_next(frac) — следующее
исполнение только на долю объёма."""
from __future__ import annotations

import json
from pathlib import Path

from .base import (BUY, FINAL, LONG, SHORT, Exchange, Incomplete, Instrument, OrderInfo, OrderReq, Rejected,
                   Unknown)


class SimExchange(Exchange):
    name = "sim"

    def __init__(self, symbol: str = "BTCUSDT", price: float = 70000.0, tick: float = 0.1, lot: float = 0.0001,
                 min_qty: float = 0.0001, maker: float = 0.00016, taker: float = 0.00048, slip: float = 0.0001,
                 clock=None, hedge: bool = True):
        self.inst = Instrument(symbol, tick, lot, min_qty)
        self.px = float(price)
        self.maker, self.taker, self.slip = maker, taker, slip
        self.orders: dict[str, dict] = {}
        self.pos = {LONG: 0.0, SHORT: 0.0}
        self.avg = {LONG: 0.0, SHORT: 0.0}
        self.realized = 0.0
        self.fees = 0.0
        self._t = 1.0e9
        self._clock = clock
        self.hedge = hedge
        self.faults: list[tuple[str, str]] = []
        self._partial: list[float] = []
        self.calls: list[tuple[str, str]] = []

    # ---------- служебное
    def now(self) -> float:
        return self._clock() if self._clock else self._t

    def tick_clock(self, sec: float) -> None:
        self._t += sec

    def fail_next(self, op: str, mode: str) -> None:
        self.faults.append((op, mode))

    def partial_next(self, frac: float) -> None:
        self._partial.append(frac)

    def _fault(self, op: str) -> str | None:
        for i, (o, m) in enumerate(self.faults):
            if o == op:
                self.faults.pop(i)
                return m
        return None

    # ---------- интерфейс
    def instrument(self, symbol: str) -> Instrument:
        return self.inst

    def book(self, symbol: str) -> tuple[float, float]:
        return self.inst.round_px(self.px - self.inst.tick / 2, "down"), self.inst.round_px(self.px + self.inst.tick / 2, "up")

    def position(self, symbol: str) -> dict[str, float]:
        return dict(self.pos)

    def place(self, req: OrderReq) -> OrderInfo:
        self.calls.append(("place", req.cid))
        f = self._fault("place")
        if f == "reject":
            raise Rejected(f"sim: отказ {req.cid}")
        if f == "unknown_lost":
            raise Unknown(f"sim: ответ потерян, ордера нет {req.cid}")
        if req.cid in self.orders:
            raise Rejected(f"sim: дубль cid {req.cid}")
        if req.qty < self.inst.min_qty - 1e-12:
            raise Rejected("sim: объём меньше минимального")
        o = {"req": req.to_dict(), "status": "NEW", "filled": 0.0, "cost": 0.0, "fee": 0.0, "t": self.now()}
        if req.kind == "STOP":
            o["status"] = "UNTRIGGERED"
        self.orders[req.cid] = o
        bid, ask = self.book(req.symbol)
        if req.kind == "MARKET":
            self._fill(o, req.qty, ask * (1 + self.slip) if req.side == BUY else bid * (1 - self.slip), self.taker, ioc=True)
        elif req.kind == "LIMIT":
            crosses = (req.side == BUY and req.price >= ask) or (req.side != BUY and req.price <= bid)
            if crosses and req.post_only:
                o["status"] = "REJECTED"
            elif crosses:
                self._fill(o, req.qty, ask if req.side == BUY else bid, self.taker, ioc=False)
        if f == "unknown_placed":
            raise Unknown(f"sim: ответ потерян, ордер стоит {req.cid}")
        return self._info(req.cid)

    def cancel(self, symbol: str, cid: str, kind: str, oid: str = "", placed_at: float = 0.0) -> None:
        self.calls.append(("cancel", cid))
        f = self._fault("cancel")
        o = self.orders.get(cid)
        if f == "unknown_lost":
            raise Unknown("sim: ответ на отмену потерян, не снят")
        if o and o["status"] not in FINAL:
            o["status"] = "CANCELED"
        if f == "unknown_placed":
            raise Unknown("sim: ответ на отмену потерян, снят")

    def order(self, symbol: str, cid: str, kind: str, oid: str = "", placed_at: float = 0.0) -> OrderInfo | None:
        f = self._fault("order")
        if f == "incomplete":
            raise Incomplete("sim: поиск неполный")
        if f == "unknown_lost":
            raise Unknown("sim: нет ответа")
        if cid not in self.orders:
            return None
        return self._info(cid)

    # ---------- цена
    def move(self, price: float) -> None:
        """Цена прошла от текущей до price: срабатывают стопы и лимитки на пути."""
        p0, p1 = self.px, float(price)
        lo, hi = min(p0, p1), max(p0, p1)
        for cid in list(self.orders):
            o = self.orders[cid]
            r = o["req"]
            if o["status"] not in ("NEW", "PARTIAL", "UNTRIGGERED"):
                continue
            if r["kind"] == "STOP" and lo <= r["trigger"] <= hi and ((r["side"] == BUY and p1 >= r["trigger"]) or (r["side"] != BUY and p1 <= r["trigger"])):
                o["status"] = "NEW"
                fill_px = r["trigger"] * (1 + self.slip) if r["side"] == BUY else r["trigger"] * (1 - self.slip)
                self._fill(o, r["qty"] - o["filled"], fill_px, self.taker, ioc=True)
            elif r["kind"] == "LIMIT":
                through = (r["side"] == BUY and lo < r["price"] - self.inst.tick / 2) or (r["side"] != BUY and hi > r["price"] + self.inst.tick / 2)
                if through:
                    self._fill(o, r["qty"] - o["filled"], r["price"], self.maker, ioc=False)
        self.px = p1

    def bar(self, o: float, h: float, l: float, c: float) -> None:
        self.move(o)
        if abs(h - o) <= abs(o - l):
            self.move(h), self.move(l)
        else:
            self.move(l), self.move(h)
        self.move(c)

    def external_trade(self, pos_side: str, qty: float, price: float | None = None) -> None:
        """Чужая сделка на той же стороне (ручная, другой бот): qty > 0 добавляет, < 0 закрывает."""
        self._apply(pos_side, qty, price or self.px)

    # ---------- исполнение
    def _fill(self, o: dict, qty: float, price: float, rate: float, ioc: bool) -> None:
        r = o["req"]
        if self._partial:
            qty = self.inst.floor_qty(qty * self._partial.pop(0))
        if r["reduce_only"]:
            qty = min(qty, self.pos[r["pos_side"]] if self.hedge else qty)
        qty = max(0.0, qty)
        if qty > 0:
            sign = 1 if (r["side"] == BUY) == (r["pos_side"] == LONG) else -1  # открытие или закрытие стороны
            self._apply(r["pos_side"], sign * qty, price)
            fee = qty * price * rate
            o["filled"] += qty
            o["cost"] += qty * price
            o["fee"] += fee
            self.fees += fee
        done = o["filled"] >= r["qty"] - 1e-12
        o["status"] = "FILLED" if done else ("CANCELED" if ioc else ("PARTIAL" if o["filled"] > 0 else o["status"]))

    def _apply(self, side: str, dq: float, price: float) -> None:
        d = 1 if side == LONG else -1
        q0 = self.pos[side]
        if dq > 0:
            self.avg[side] = (self.avg[side] * q0 + price * dq) / (q0 + dq)
            self.pos[side] = q0 + dq
        else:
            q = min(-dq, q0)
            self.realized += d * q * (price - self.avg[side])
            self.pos[side] = round(q0 - q, 12)
            if self.pos[side] <= 1e-12:
                self.pos[side], self.avg[side] = 0.0, 0.0

    def _info(self, cid: str) -> OrderInfo:
        o = self.orders[cid]
        avg = o["cost"] / o["filled"] if o["filled"] else 0.0
        return OrderInfo(cid=cid, status=o["status"], filled=round(o["filled"], 12), avg=avg, fee=o["fee"], oid=f"sim-{cid}")

    # ---------- сохранение (бумажный прогон переживает перезапуск)
    def dump(self, path: Path) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"px": self.px, "orders": self.orders, "pos": self.pos, "avg": self.avg, "realized": self.realized, "fees": self.fees}))
        tmp.replace(path)

    def load(self, path: Path) -> None:
        if not path.exists():
            return
        d = json.loads(path.read_text())
        self.px, self.orders, self.pos, self.avg = d["px"], d["orders"], d["pos"], d["avg"]
        self.realized, self.fees = d["realized"], d["fees"]
