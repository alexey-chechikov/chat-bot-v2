"""OKX v5, USDT-перпы (instId BTC-USDT-SWAP, объём в контрактах: ctVal = 0.01 BTC). Хедж-режим (long_short_mode):
posSide long/short; односторонний (net) — без posSide.

Подпись: base64(HMAC_SHA256(secret, timestamp + METHOD + requestPath(+query) + body)), заголовки OK-ACCESS-KEY /
OK-ACCESS-SIGN / OK-ACCESS-TIMESTAMP (ISO, мс) / OK-ACCESS-PASSPHRASE; демо-счёт — заголовок x-simulated-trading: 1.
Свой номер — clOrdId (= cid, буквы и цифры до 32). Условный (STOP) — /api/v5/trade/order-algo ordType=trigger,
orderPx=-1 (рыночный по срабатыванию), свой номер algoClOrdId; исполнение — по ordId сработавшего алгоритма.
Ключи: OKX_API_KEY / OKX_API_SECRET / OKX_API_PASSPHRASE (демо: OKX_DEMO_*) в .env.local — вписывает оператор.
ПРОВЕРЕНО ВЖИВУЮ: только публичные методы (instrument, book). Торговые — по документации, до демо-счёта не включать."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .base import BUY, LONG, Exchange, ExchangeError, Incomplete, Instrument, OrderInfo, OrderReq, Rejected, Unknown
from .bybit import _load_env

BASE = "https://www.okx.com"
STATUS = {"live": "NEW", "partially_filled": "PARTIAL", "filled": "FILLED", "canceled": "CANCELED", "mmp_canceled": "CANCELED"}
ALGO = {"live": "UNTRIGGERED", "pause": "UNTRIGGERED", "partially_effective": "NEW", "effective": "NEW", "canceled": "CANCELED", "order_failed": "REJECTED"}
NOT_FOUND = {"51603"}                    # Order does not exist
CANCEL_DONE = {"51400", "51401", "51402", "51410"}  # уже исполнен / отменён / нет
RETRYABLE = {"50001", "50004", "50011", "50013", "50026"}


def inst_id(symbol: str) -> str:
    return symbol.replace("USDT", "-USDT-SWAP") if "-" not in symbol else symbol


class OkxExchange(Exchange):
    name = "okx"

    def __init__(self, key: str = "", secret: str = "", passphrase: str = "", demo: bool = False, hedge: bool = True, timeout: float = 10.0, http=None):
        self.key, self.secret, self.pp, self.demo, self.hedge, self.timeout = key, secret, passphrase, demo, hedge, timeout
        self._http = http or self._urlopen
        self._inst: dict[str, Instrument] = {}

    @classmethod
    def from_env(cls, demo: bool = False, hedge: bool = True):
        env = {**_load_env(), **os.environ}
        p = "OKX_DEMO_" if demo else "OKX_"
        k, s, pp = env.get(p + "API_KEY"), env.get(p + "API_SECRET"), env.get(p + "API_PASSPHRASE")
        if not (k and s and pp):
            raise ExchangeError("нет ключей OKX в .env.local")
        return cls(k, s, pp, demo=demo, hedge=hedge)

    def _urlopen(self, method: str, url: str, headers: dict, data: bytes | None):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode())

    def _call(self, method: str, path: str, params: dict | list | None = None, signed: bool = True) -> dict:
        if method == "GET":
            q = urllib.parse.urlencode(params or {})
            rp, body, data = path + ("?" + q if q else ""), "", None
        else:
            rp, body = path, json.dumps(params or {}, separators=(",", ":"))
            data = body.encode()
        h = {"Content-Type": "application/json", "User-Agent": "bot7-sigexec/1.0"}
        if signed:
            n = datetime.now(timezone.utc)
            ts = n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"
            h.update({"OK-ACCESS-KEY": self.key, "OK-ACCESS-SIGN": sign(self.secret, ts + method + rp + body), "OK-ACCESS-TIMESTAMP": ts,
                      "OK-ACCESS-PASSPHRASE": self.pp})
        if self.demo:
            h["x-simulated-trading"] = "1"
        try:
            r = self._http(method, BASE + rp, h, data)
        except urllib.error.HTTPError as e:
            # разбор aadc2a4 P1-2: OKX отдаёт 50004 (таймаут, исход заявки неизвестен) как HTTP 400 — код берётся из тела;
            # тело без кода — исход неизвестен, а не отказ
            try:
                r = json.loads(e.read().decode())
            except Exception:  # noqa: BLE001
                raise Unknown(f"okx HTTP {e.code} без разбираемого тела") from None
            if not isinstance(r, dict) or "code" not in r:
                raise Unknown(f"okx HTTP {e.code}: {str(r)[:120]}") from None
        except Exception as e:  # noqa: BLE001
            raise Unknown(f"okx {path}: {e!r}") from None
        if not isinstance(r, dict) or "code" not in r:
            raise Unknown(f"okx {path}: ответ без code ({str(r)[:120]})")
        return r

    def now(self) -> float:
        return time.time()

    def instrument(self, symbol: str) -> Instrument:
        if symbol not in self._inst:
            r = self._call("GET", "/api/v5/public/instruments", {"instType": "SWAP", "instId": inst_id(symbol)}, signed=False)
            x = r["data"][0]
            ct = float(x["ctVal"])
            self._inst[symbol] = Instrument(symbol, float(x["tickSz"]), float(x["lotSz"]) * ct, float(x["minSz"]) * ct, ct)
        return self._inst[symbol]

    def book(self, symbol: str) -> tuple[float, float]:
        x = self._call("GET", "/api/v5/market/ticker", {"instId": inst_id(symbol)}, signed=False)["data"][0]
        return float(x["bidPx"]), float(x["askPx"])

    def position(self, symbol: str) -> dict[str, float]:
        r = self._call("GET", "/api/v5/account/positions", {"instType": "SWAP", "instId": inst_id(symbol)})
        if r["code"] != "0":
            raise ExchangeError(f"okx positions: {r.get('msg')}")
        ct = self.instrument(symbol).ct_val
        out = {"LONG": 0.0, "SHORT": 0.0}
        for p in r["data"]:
            q = float(p.get("pos") or 0) * ct
            side = p.get("posSide")
            if side == "long" or (side == "net" and q > 0):
                out["LONG"] += abs(q)
            elif side == "short" or (side == "net" and q < 0):
                out["SHORT"] += abs(q)
        return out

    def _sz(self, symbol: str, qty: float) -> str:
        inst = self.instrument(symbol)
        n = qty / inst.ct_val
        lot_ct = inst.lot / inst.ct_val
        return _fmt_ct(round(n / lot_ct) * lot_ct, lot_ct)

    def place(self, req: OrderReq) -> OrderInfo:
        inst = self.instrument(req.symbol)
        b = {"instId": inst_id(req.symbol), "tdMode": "cross", "side": "buy" if req.side == BUY else "sell", "sz": self._sz(req.symbol, req.qty)}
        if self.hedge:
            b["posSide"] = "long" if req.pos_side == LONG else "short"
        elif req.reduce_only:
            b["reduceOnly"] = True
        if req.kind == "STOP":
            b.update(ordType="trigger", triggerPx=inst.fmt_px(req.trigger), orderPx="-1", algoClOrdId=req.cid, triggerPxType="last")
            r = self._call("POST", "/api/v5/trade/order-algo", b)
        else:
            if req.kind == "MARKET":
                b["ordType"] = "market"
            else:
                b.update(ordType="post_only" if req.post_only else "limit", px=inst.fmt_px(req.price, req.side))
            b["clOrdId"] = req.cid
            r = self._call("POST", "/api/v5/trade/order", b)
        d = (r.get("data") or [{}])[0]
        s_code = str(d.get("sCode", r["code"]))
        if r["code"] == "0" and s_code == "0":
            return OrderInfo(cid=req.cid, status="UNTRIGGERED" if req.kind == "STOP" else "NEW", oid=str(d.get("algoId") or d.get("ordId") or ""))
        if s_code in RETRYABLE or r["code"] in RETRYABLE:
            raise Unknown(f"okx place {s_code}: {d.get('sMsg') or r.get('msg')}")
        raise Rejected(f"okx place {s_code}: {d.get('sMsg') or r.get('msg')}")

    def cancel(self, symbol: str, cid: str, kind: str, oid: str = "", placed_at: float = 0.0) -> None:
        if kind == "STOP":
            info = self.order(symbol, cid, kind)
            if info is None or info.final:
                return
            child = (info.raw or {}).get("child_id")
            if child:                                          # алгоритм сработал: снимать порождённую заявку (разбор aadc2a4)
                r = self._call("POST", "/api/v5/trade/cancel-order", {"instId": inst_id(symbol), "ordId": child})
            else:
                aid = oid or (info.raw or {}).get("algoId", "")
                r = self._call("POST", "/api/v5/trade/cancel-algos", [{"instId": inst_id(symbol), "algoId": aid}])
        else:
            r = self._call("POST", "/api/v5/trade/cancel-order", {"instId": inst_id(symbol), "clOrdId": cid})
        d = (r.get("data") or [{}])[0]
        code = str(d.get("sCode", r["code"]))
        if r["code"] == "0" and code == "0" or code in CANCEL_DONE:
            return
        raise Unknown(f"okx cancel {code}: {d.get('sMsg') or r.get('msg')}")

    def order(self, symbol: str, cid: str, kind: str, oid: str = "", placed_at: float = 0.0) -> OrderInfo | None:
        ct = self.instrument(symbol).ct_val
        if kind == "STOP":
            r = self._call("GET", "/api/v5/trade/order-algo", {"algoClOrdId": cid})
            if r["code"] in NOT_FOUND or (r["code"] == "0" and not r.get("data")):
                return None
            if r["code"] != "0":
                raise Incomplete(f"okx order-algo {r['code']}: {r.get('msg')}")
            a = r["data"][0]
            st = ALGO.get(a.get("state", ""))
            if st is None:
                raise Incomplete(f"okx: неизвестное состояние алгоритма {a.get('state')}")
            info = OrderInfo(cid=cid, status=st, oid=str(a.get("algoId", "")), raw=a)
            child = a.get("ordId") or next(iter(a.get("ordIdList") or []), "")
            if st == "NEW":                                    # сработал — исполнение смотрим у порождённого ордера
                if not child:
                    raise Incomplete(f"okx: алгоритм {a.get('state')} без порождённой заявки")
                r2 = self._call("GET", "/api/v5/trade/order", {"instId": inst_id(symbol), "ordId": child})
                if r2["code"] != "0" or not r2.get("data"):
                    raise Incomplete(f"okx order {child}: {r2.get('msg')}")
                o = parse_order(r2["data"][0], ct)
                info = OrderInfo(cid=cid, status=o.status, filled=o.filled, avg=o.avg, fee=o.fee, oid=info.oid, raw={**a, "child": o.raw, "child_id": child})
            return info
        r = self._call("GET", "/api/v5/trade/order", {"instId": inst_id(symbol), "clOrdId": cid})
        if r["code"] in NOT_FOUND:
            return None
        if r["code"] != "0" or not r.get("data"):
            raise Incomplete(f"okx order {r['code']}: {r.get('msg')}")
        return parse_order(r["data"][0], ct)


def parse_order(x: dict, ct: float) -> OrderInfo:
    st = STATUS.get(x.get("state", ""))
    if st is None:
        raise Incomplete(f"okx: неизвестное состояние {x.get('state')}")
    filled = float(x.get("accFillSz") or 0) * ct
    avg = float(x.get("avgPx") or 0) if filled else 0.0
    return OrderInfo(cid=x.get("clOrdId", ""), status=st, filled=filled, avg=avg, fee=-float(x.get("fee") or 0), oid=str(x.get("ordId", "")), raw=x)


def _fmt_ct(n: float, lot_ct: float) -> str:
    dec = 0
    while dec < 8 and abs(round(lot_ct, dec) - lot_ct) > 1e-12:
        dec += 1
    return f"{n:.{dec}f}"


def sign(secret: str, payload: str) -> str:
    return base64.b64encode(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()).decode()
