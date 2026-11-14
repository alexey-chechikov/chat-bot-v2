"""WEEX v3 USDT-перпы через проверенный клиент services/weex_api/client.py (сетки торгуют им с 09.10).

Хедж-режим счёта (positionSide LONG/SHORT). Свой номер — newClientOrderId / clientAlgoId (= cid).
Статусы и поля — как разбирают services/weex_grid и weex_trend: executedQty / avgPrice, комиссия — сумма commission
сделок ордера (userTrades). Поиск по cid: открытые → история окна вокруг времени отправки (WEEX игнорирует page —
окно делится пополам, пока ответ < 100). Условный стоп: /capi/v3/algoOrder (clientAlgoId), сработавший — по
algoStatus / actualOrderId / actualPrice из allAlgoOrders.
ВНИМАНИЕ: на WEEX стороны BTCUSDT общие с живыми сетками и ручными сделками оператора — исполнитель ведёт только
свои cid (префикс конфига), сверка позиции видит лишь «меньше своего» (executor._audit)."""
from __future__ import annotations

import time

from services.weex_api.client import FUTURES, WeexClient, WeexError, WeexIncomplete

from .base import Exchange, ExchangeError, Incomplete, Instrument, OrderInfo, OrderReq, Rejected, Unknown

LIVE = {"NEW": "NEW", "PENDING": "NEW", "CANCELING": "NEW", "PARTIALLY_FILLED": "PARTIAL", "UNTRIGGERED": "UNTRIGGERED", "UNACTIVATED": "UNTRIGGERED"}
DONE = {"FILLED": "FILLED", "CANCELED": "CANCELED", "CANCELLED": "CANCELED", "EXPIRED": "CANCELED", "REJECTED": "REJECTED"}
SPEC = {"BTCUSDT": (0.1, 0.0001, 0.0001), "ETHUSDT": (0.01, 0.001, 0.001)}  # тик, шаг, минимум — как state/weex_grid*_config.json
WINDOW_MS = 600_000
BUDGET = 12


class WeexExchange(Exchange):
    name = "weex"
    hedge = True

    def __init__(self, client: WeexClient):
        self.c = client

    @classmethod
    def from_env(cls):
        c = WeexClient()
        c.sync_time()
        return cls(c)

    def now(self) -> float:
        return time.time()

    def instrument(self, symbol: str) -> Instrument:
        if symbol not in SPEC:
            raise ExchangeError(f"weex: нет параметров контракта {symbol}")
        return Instrument(symbol, *SPEC[symbol])

    def book(self, symbol: str) -> tuple[float, float]:
        try:
            return self.c.book(symbol)
        except (WeexError, OSError) as e:
            raise Unknown(f"weex book: {e}") from None

    def position(self, symbol: str) -> dict[str, float]:
        rows = self.c.futures_positions()
        if not isinstance(rows, list):
            raise ExchangeError(f"weex позиции: не список ({str(rows)[:120]})")
        out = {"LONG": 0.0, "SHORT": 0.0}
        for p in rows:
            if p.get("symbol") == symbol and p.get("side") in out:
                out[p["side"]] += float(p.get("size") or 0)
        return out

    def position_ids(self, symbol: str) -> dict[str, str | None]:
        """Номер позиции стороны (поле id; чтение 14.11: новый после закрытия стороны до нуля — у ETH с 05.11). Две строки
        на сторону или строка без id — ExchangeError (неясно)."""
        rows = self.c.futures_positions()
        if not isinstance(rows, list):
            raise ExchangeError(f"weex позиции: не список ({str(rows)[:120]})")
        out: dict[str, str | None] = {"LONG": None, "SHORT": None}
        for p in rows:
            if not isinstance(p, dict) or p.get("symbol") != symbol or p.get("side") not in out:
                continue
            if out[p["side"]] is not None or not p.get("id"):
                raise ExchangeError(f"weex позиции {symbol} {p.get('side')}: две строки или нет id")
            if float(p.get("size") or 0) > 0:
                out[p["side"]] = str(p["id"])
        return out

    def place(self, req: OrderReq) -> OrderInfo:
        inst = self.instrument(req.symbol)
        q = inst.fmt_qty(req.qty)
        try:
            if req.kind == "MARKET":
                r = self.c.place_market(req.symbol, req.side, req.pos_side, q, req.cid, reduce_only=req.reduce_only)
            elif req.kind == "LIMIT":
                r = self.c.place_limit(req.symbol, req.side, req.pos_side, q, inst.fmt_px(req.price, req.side), req.cid, reduce_only=req.reduce_only,
                                       post_only=req.post_only)
            elif req.kind == "STOP":
                body = {"symbol": req.symbol, "side": req.side, "positionSide": req.pos_side, "type": "STOP_MARKET", "quantity": q,
                        "triggerPrice": inst.fmt_px(req.trigger), "clientAlgoId": req.cid, "reduceOnly": bool(req.reduce_only), "workingType": "CONTRACT_PRICE"}
                r = self.c.post(FUTURES, "/capi/v3/algoOrder", body)
            else:
                raise Rejected(f"weex: тип {req.kind}")
        except WeexError as e:
            msg = str(e)
            if msg.startswith("HTTP 4") and not msg.startswith(("HTTP 408", "HTTP 429")):
                raise Rejected(f"weex: {msg[:200]}") from None
            raise Unknown(f"weex: {msg[:200]}") from None
        except OSError as e:
            raise Unknown(f"weex: {e!r}") from None
        oid = str((r or {}).get("algoId") or (r or {}).get("orderId") or "") if isinstance(r, dict) else ""
        if not oid:
            raise Unknown(f"weex: ответ без номера ({str(r)[:120]})")   # {} / None — исход неизвестен (аудит GPT E3)
        if r.get("success") is False:
            # разбор ead2ca4: номер есть, но success=false — не «встала»; исход решает поиск по cid
            raise Unknown(f"weex: success=false при номере {oid} ({str(r)[:120]})")
        return OrderInfo(cid=req.cid, status="UNTRIGGERED" if req.kind == "STOP" else "NEW", oid=oid)

    def cancel(self, symbol: str, cid: str, kind: str, oid: str = "", placed_at: float = 0.0) -> None:
        if kind == "STOP":
            # разбор ead2ca4: сработавший условный ордер живёт дочерним обычным (actualOrderId) — снимать надо его, а
            # не родителя (DELETE родителя после срабатывания ничего не снимает, выход стоял). Состояние — свежим поиском.
            info = self.order(symbol, cid, kind, oid, placed_at)
            if info is None or info.final:
                return
            child = (info.raw or {}).get("actualOrderId")
            try:
                if child and info.status != "UNTRIGGERED":
                    self.c.cancel(child)
                else:
                    self.c.cancel_algo(info.oid or oid)
            except (WeexError, OSError) as e:
                raise Unknown(f"weex cancel: {e}") from None
            return
        if not oid:
            info = self.order(symbol, cid, kind)
            if info is None or info.final:
                return
            oid = info.oid
        try:
            self.c.cancel(oid)
        except (WeexError, OSError) as e:
            raise Unknown(f"weex cancel: {e}") from None

    def order(self, symbol: str, cid: str, kind: str, oid: str = "", placed_at: float = 0.0) -> OrderInfo | None:
        try:
            if kind == "STOP":
                return self._algo(symbol, cid, placed_at)
            row = None
            if oid:
                row = self.c.order_info(oid)
                row = row if isinstance(row, dict) and row.get("status") else None
            if row is None:
                row = next((x for x in _rows(self.c.open_orders(symbol), "orderId", "openOrders") if x.get("clientOrderId") == cid), None)
            if row is None:
                t = placed_at or time.time()
                row, complete = self._history(symbol, cid, int((t - WINDOW_MS / 1000) * 1000), int((t + WINDOW_MS / 1000) * 1000), [BUDGET])
                if row is None:
                    if not complete:
                        raise Incomplete("weex: история неполная")
                    return None
            return self._parse(row)
        except WeexIncomplete as e:
            raise Incomplete(str(e)) from None
        except (WeexError, OSError) as e:
            raise Incomplete(f"weex поиск: {e}") from None

    def _parse(self, x: dict) -> OrderInfo:
        if not isinstance(x, dict):                     # разбор b056816: null / список из order_info ронял проход
            raise Incomplete(f"weex: ордер не словарь ({str(x)[:80]})")
        st = x.get("status", "")
        status = LIVE.get(st) or DONE.get(st)
        if status is None:
            raise Incomplete(f"weex: неизвестный статус {st!r}")
        if status in ("FILLED", "CANCELED") and x.get("executedQty") is None:
            raise Incomplete("weex: конечный статус без executedQty")
        if not isinstance(x, dict):
            raise Incomplete(f"weex: ордер не словарь ({str(x)[:80]})")
        try:
            filled = float(x.get("executedQty") or 0)
            avg = float(x.get("avgPrice") or 0) if filled else 0.0
        except (TypeError, ValueError):
            raise Incomplete(f"weex: executedQty/avgPrice не числа ({str(x)[:120]})") from None
        fee, known = 0.0, True
        if filled:
            try:
                trades = self.c.user_trades(x.get("symbol") or "BTCUSDT", x.get("orderId"))
                fee = sum(float(t.get("commission") or 0) for t in trades or [])
                known = len(trades or []) < 100 and bool(trades)
            except (WeexError, OSError):
                known = False
        return OrderInfo(cid=x.get("clientOrderId", ""), status=status, filled=filled, avg=avg, fee=abs(fee), oid=str(x.get("orderId", "")), raw=x, fee_known=known)

    def _algo(self, symbol: str, cid: str, placed_at: float) -> OrderInfo | None:
        rows = _rows(self.c.open_algo_orders(symbol), "algoId", "openAlgoOrders")   # «[{}]» — Incomplete (разбор b056816)
        a = next((x for x in rows if x.get("clientAlgoId") == cid), None)
        if a is not None:
            return OrderInfo(cid=cid, status="UNTRIGGERED", oid=str(a.get("algoId", "")), raw=a)
        t = placed_at or time.time()
        # разбор aadc2a4: client.algo_history теряет hasMore — читаем ответ сами; список неполный и cid нет → Incomplete.
        # Разбор ead2ca4: «{}» превращался в пустую полную историю → стоп ABSENT → второй стоп на общей стороне. Ответ WEEX
        # (чтение 14.11): {"hasMore": bool, "orders": [...]} — иначе Incomplete, отсутствие не доказано
        r = self.c.get(FUTURES, "/capi/v3/allAlgoOrders", {"symbol": symbol, "limit": 500, "startTime": int((t - 600) * 1000)})
        if not (isinstance(r, dict) and isinstance(r.get("orders"), list) and isinstance(r.get("hasMore"), bool)
                and all(isinstance(x, dict) and x.get("algoId") for x in r["orders"])):
            raise Incomplete(f"weex allAlgoOrders: ответ не {{hasMore: bool, orders: [..]}} ({str(r)[:120]})")
        hist, more = r["orders"], r["hasMore"]
        a = next((x for x in hist if x.get("clientAlgoId") == cid), None)
        if a is None:
            if more:
                raise Incomplete("weex allAlgoOrders: hasMore — список неполный, отсутствие не доказано")
            return None
        st = a.get("algoStatus", "")
        if st in ("UNTRIGGERED", "UNACTIVATED"):
            return OrderInfo(cid=cid, status="UNTRIGGERED", oid=str(a.get("algoId", "")), raw=a)
        if st == "CANCELED" and not a.get("actualOrderId"):
            return OrderInfo(cid=cid, status="CANCELED", oid=str(a.get("algoId", "")), raw=a)
        child = a.get("actualOrderId")
        if not child:
            raise Incomplete(f"weex: алгоритм {st} без actualOrderId")
        o = self._parse(self.c.order_info(child))       # не словарь / не числа — Incomplete (разбор b056816)
        return OrderInfo(cid=cid, status=o.status, filled=o.filled, avg=o.avg or float(a.get("actualPrice") or 0), fee=o.fee, oid=str(a.get("algoId", "")),
                         raw={**a, "child": o.raw}, fee_known=o.fee_known)

    def _history(self, sym: str, cid: str, a: int, b: int, budget: list[int]) -> tuple[dict | None, bool]:
        if budget[0] <= 0:
            return None, False
        budget[0] -= 1
        rows = self.c.order_history(sym, limit=100, page=0, start_ms=a, end_ms=b)
        o = next((x for x in _rows(rows, "orderId", "order/history") if x.get("clientOrderId") == cid), None)
        if o is not None:
            return o, True
        if len(rows) < 100:
            return None, True
        if b - a <= 1000:
            return None, False
        m = (a + b) // 2
        complete = True
        for lo, hi in ((a, m), (m, b)):
            o, ok = self._history(sym, cid, lo, hi, budget)
            if o is not None:
                return o, True
            complete = complete and ok
        return None, complete


def _rows(rows, id_key: str, what: str) -> list[dict]:
    """Список строк ордеров: каждая — словарь с номером биржи (разбор GPT b056816: «[{}]» проходил проверку типа, а строку
    без номера нельзя отнести ни к одному ордеру — отсутствие своего не доказано). Иначе Incomplete."""
    if not isinstance(rows, list) or not all(isinstance(x, dict) and x.get(id_key) for x in rows):
        raise Incomplete(f"weex {what}: строка без {id_key} или не список ({str(rows)[:120]})")
    return rows
