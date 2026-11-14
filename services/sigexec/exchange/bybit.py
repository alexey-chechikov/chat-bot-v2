"""Bybit v5, линейные USDT-перпы (category=linear). Хедж-режим: positionIdx 1 — лонг, 2 — шорт; односторонний — 0.

Подпись: HMAC_SHA256(secret, timestamp + api_key + recv_window + (query для GET | тело JSON для POST)), заголовки
X-BAPI-API-KEY / X-BAPI-TIMESTAMP / X-BAPI-RECV-WINDOW / X-BAPI-SIGN. Свой номер — orderLinkId (= cid).
Условный (STOP) — тот же /v5/order/create с triggerPrice и triggerDirection (1 — цена растёт до уровня, 2 — падает).
Поиск: /v5/order/realtime по orderLinkId (живые и недавние), затем /v5/order/history.
Ключи: BYBIT_API_KEY / BYBIT_API_SECRET в .env.local (вписывает оператор). Тестнет: api-testnet.bybit.com.
ПРОВЕРЕНО ВЖИВУЮ: только публичные методы (instrument, book). Торговые — по документации, до тестнета не включать."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from .base import BUY, LONG, Exchange, ExchangeError, Incomplete, Instrument, OrderInfo, OrderReq, Rejected, Unknown

MAIN, TEST = "https://api.bybit.com", "https://api-testnet.bybit.com"
STATUS = {"New": "NEW", "PartiallyFilled": "PARTIAL", "Untriggered": "UNTRIGGERED", "Triggered": "NEW", "Active": "NEW",
          "Filled": "FILLED", "Cancelled": "CANCELED", "PartiallyFilledCanceled": "CANCELED", "Deactivated": "CANCELED", "Rejected": "REJECTED"}
RETRYABLE = {10000, 10002, 10006, 10016, 10019, 170007, 170146}   # сервер, время, частота, таймаут — исход неизвестен
CANCEL_DONE = {110001, 170213}                                  # нет такой / уже конечная


def _load_env(path=None) -> dict:
    from pathlib import Path
    p = Path(path) if path else Path(__file__).resolve().parents[3] / ".env.local"
    out = {}
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


class BybitExchange(Exchange):
    name = "bybit"

    def __init__(self, key: str = "", secret: str = "", testnet: bool = False, hedge: bool = True, timeout: float = 10.0, http=None):
        self.key, self.secret, self.base, self.hedge, self.timeout = key, secret, TEST if testnet else MAIN, hedge, timeout
        self._http = http or self._urlopen
        self._inst: dict[str, Instrument] = {}
        self.recv = "5000"

    @classmethod
    def from_env(cls, testnet: bool = False, hedge: bool = True):
        env = {**_load_env(), **os.environ}
        k, s = env.get("BYBIT_TESTNET_API_KEY" if testnet else "BYBIT_API_KEY"), env.get("BYBIT_TESTNET_API_SECRET" if testnet else "BYBIT_API_SECRET")
        if not (k and s):
            raise ExchangeError("нет ключей Bybit в .env.local")
        return cls(k, s, testnet=testnet, hedge=hedge)

    # ---------- транспорт
    def _urlopen(self, method: str, url: str, headers: dict, data: bytes | None):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode())

    def _call(self, method: str, path: str, params: dict | None = None, signed: bool = True) -> dict:
        params = params or {}
        if method == "GET":
            q = urllib.parse.urlencode(params)
            url, payload, data = f"{self.base}{path}{'?' + q if q else ''}", q, None
        else:
            payload = json.dumps(params, separators=(",", ":"))
            url, data = f"{self.base}{path}", payload.encode()
        h = {"Content-Type": "application/json", "User-Agent": "bot7-sigexec/1.0"}
        if signed:
            ts = str(int(time.time() * 1000))
            h.update({"X-BAPI-API-KEY": self.key, "X-BAPI-TIMESTAMP": ts, "X-BAPI-RECV-WINDOW": self.recv,
                      "X-BAPI-SIGN": sign(self.secret, ts + self.key + self.recv + payload)})
        try:
            r = self._http(method, url, h, data)
        except urllib.error.HTTPError as e:
            # код — из тела; тело без retCode — исход неизвестен, не отказ (разбор aadc2a4, P1-2 — то же правило, что для OKX)
            try:
                r = json.loads(e.read().decode())
            except Exception:  # noqa: BLE001
                raise Unknown(f"bybit HTTP {e.code} без разбираемого тела") from None
            if not isinstance(r, dict) or "retCode" not in r:
                raise Unknown(f"bybit HTTP {e.code}: {str(r)[:120]}") from None
        except Exception as e:  # noqa: BLE001 — таймаут, сеть: исход неизвестен
            raise Unknown(f"bybit {path}: {e!r}") from None
        if not isinstance(r, dict) or "retCode" not in r:
            raise Unknown(f"bybit {path}: ответ без retCode ({str(r)[:120]})")
        return r

    # ---------- интерфейс
    def now(self) -> float:
        return time.time()

    def instrument(self, symbol: str) -> Instrument:
        if symbol not in self._inst:
            r = self._call("GET", "/v5/market/instruments-info", {"category": "linear", "symbol": symbol}, signed=False)
            x = r["result"]["list"][0]
            self._inst[symbol] = Instrument(symbol, float(x["priceFilter"]["tickSize"]), float(x["lotSizeFilter"]["qtyStep"]), float(x["lotSizeFilter"]["minOrderQty"]))
        return self._inst[symbol]

    def book(self, symbol: str) -> tuple[float, float]:
        r = self._call("GET", "/v5/market/tickers", {"category": "linear", "symbol": symbol}, signed=False)
        x = r["result"]["list"][0]
        return float(x["bid1Price"]), float(x["ask1Price"])

    def position(self, symbol: str) -> dict[str, float]:
        r = self._call("GET", "/v5/position/list", {"category": "linear", "symbol": symbol})
        if r["retCode"] != 0:
            raise ExchangeError(f"bybit position: {r.get('retMsg')}")
        out = {"LONG": 0.0, "SHORT": 0.0}
        for p in r["result"]["list"]:
            sz = float(p.get("size") or 0)
            if p.get("side") == "Buy":
                out["LONG"] += sz
            elif p.get("side") == "Sell":
                out["SHORT"] += sz
        return out

    def _idx(self, pos_side: str) -> int:
        return (1 if pos_side == LONG else 2) if self.hedge else 0

    def place(self, req: OrderReq) -> OrderInfo:
        inst = self.instrument(req.symbol)
        b = {"category": "linear", "symbol": req.symbol, "side": "Buy" if req.side == BUY else "Sell", "qty": inst.fmt_qty(req.qty),
             "orderLinkId": req.cid, "positionIdx": self._idx(req.pos_side), "reduceOnly": bool(req.reduce_only)}
        if req.kind == "MARKET":
            b["orderType"] = "Market"
        elif req.kind == "LIMIT":
            b.update(orderType="Limit", price=inst.fmt_px(req.price, req.side), timeInForce="PostOnly" if req.post_only else "GTC")
        elif req.kind == "STOP":
            # направление — по стороне, не по текущей цене: покупка-стоп (добор лонга, аварийный шорта) — на росте (1),
            # продажа-стоп — на падении (2). Уровень уже пройден — биржа откажет, исполнитель выйдет сам (executor._protect)
            b.update(orderType="Market", triggerPrice=inst.fmt_px(req.trigger), triggerDirection=1 if req.side == BUY else 2, triggerBy="LastPrice")
        else:
            raise Rejected(f"bybit: тип {req.kind}")
        r = self._call("POST", "/v5/order/create", b)
        code = r["retCode"]
        if code == 0:
            return OrderInfo(cid=req.cid, status="UNTRIGGERED" if req.kind == "STOP" else "NEW", oid=str(r["result"].get("orderId", "")))
        if code in RETRYABLE:
            raise Unknown(f"bybit create {code}: {r.get('retMsg')}")
        raise Rejected(f"bybit create {code}: {r.get('retMsg')}")

    def cancel(self, symbol: str, cid: str, kind: str, oid: str = "", placed_at: float = 0.0) -> None:
        b = {"category": "linear", "symbol": symbol, "orderLinkId": cid}
        if kind == "STOP":
            b["orderFilter"] = "StopOrder"
        r = self._call("POST", "/v5/order/cancel", b)
        if r["retCode"] == 0 or r["retCode"] in CANCEL_DONE:
            return
        raise Unknown(f"bybit cancel {r['retCode']}: {r.get('retMsg')}")

    def order(self, symbol: str, cid: str, kind: str, oid: str = "", placed_at: float = 0.0) -> OrderInfo | None:
        for path in ("/v5/order/realtime", "/v5/order/history"):
            p = {"category": "linear", "symbol": symbol, "orderLinkId": cid}
            if kind == "STOP" and path.endswith("realtime"):
                p["orderFilter"] = "StopOrder"
            r = self._call("GET", path, p)
            if r["retCode"] != 0:
                raise Incomplete(f"bybit {path} {r['retCode']}: {r.get('retMsg')}")
            rows = [x for x in r["result"].get("list", []) if x.get("orderLinkId") == cid]
            if rows:
                return parse_order(rows[0])
        return None


def parse_order(x: dict) -> OrderInfo:
    st = STATUS.get(x.get("orderStatus", ""), "")
    if not st:
        raise Incomplete(f"bybit: неизвестный статус {x.get('orderStatus')}")
    filled = float(x.get("cumExecQty") or 0)
    avg = float(x.get("avgPrice") or 0) if filled else 0.0
    # комиссия: актуальное поле cumFeeDetail {"USDT": …}, устаревшее cumExecFee — запасное; нет ни того ни другого при
    # исполнении — комиссия не дочитана (разбор aadc2a4)
    detail = x.get("cumFeeDetail") if isinstance(x.get("cumFeeDetail"), dict) else {}
    if "USDT" in detail:
        fee, known = float(detail["USDT"] or 0), True
    elif x.get("cumExecFee") not in (None, ""):
        fee, known = float(x["cumExecFee"]), True
    else:
        fee, known = 0.0, filled == 0
    return OrderInfo(cid=x.get("orderLinkId", ""), status=st, filled=filled, avg=avg, fee=fee, oid=str(x.get("orderId", "")), raw=x, fee_known=known)


def sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
