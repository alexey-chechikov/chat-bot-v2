"""Минимальный клиент WEEX: чтение (стакан, ордера, сделки, позиции, баланс) и торговля
(лимитный ордер POST_ONLY, отмена) — торговые методы вызывает только сетка services/weex_grid.

Подпись по документации WEEX: Base64(HMAC-SHA256(secret, timestamp + METHOD + path
[+ "?" + query] + body)), заголовки ACCESS-KEY / ACCESS-SIGN / ACCESS-PASSPHRASE /
ACCESS-TIMESTAMP (мс; сервер отклоняет расхождение > 30 с — время берём у сервера).
Фьючерсы: https://api-contract.weex.com, спот: https://api-spot.weex.com.
Секреты никогда не пишутся в лог и не возвращаются наружу.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
ENV_LOCAL = ROOT / ".env.local"
FUTURES = "https://api-contract.weex.com"
SPOT = "https://api-spot.weex.com"


class WeexError(RuntimeError):
    pass


def load_credentials(path: Path = ENV_LOCAL) -> tuple[str, str, str] | None:
    vals = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            vals[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        return None
    key, sec, pas = (vals.get(k) for k in ("WEEX_API_KEY", "WEEX_API_SECRET", "WEEX_API_PASSPHRASE"))
    return (key, sec, pas) if key and sec and pas else None


def sign(secret: str, ts: str, method: str, path: str, query: str = "", body: str = "") -> str:
    msg = ts + method.upper() + path + (("?" + query) if query else "") + body
    return base64.b64encode(hmac.new(secret.encode(), msg.encode(), hashlib.sha256).digest()).decode()


class WeexClient:
    def __init__(self, creds: tuple[str, str, str] | None = None, timeout: float = 15.0):
        creds = creds or load_credentials()
        if not creds:
            raise WeexError("нет WEEX_API_KEY / WEEX_API_SECRET / WEEX_API_PASSPHRASE в .env.local")
        self._key, self._secret, self._pass = creds
        self._timeout = timeout
        self._offset_ms = 0

    def _http(self, url: str, headers: dict | None = None):
        req = urllib.request.Request(url, headers={"User-Agent": "bot7/weex", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raise WeexError(f"HTTP {e.code}: {e.read().decode(errors='ignore')[:300]}") from None

    def sync_time(self) -> int:
        server = int(self._http(FUTURES + "/capi/v3/market/time")["serverTime"])
        self._offset_ms = server - int(time.time() * 1000)
        return self._offset_ms

    def _signed(self, method: str, base: str, path: str, params: dict | None = None, body: dict | None = None):
        query = urllib.parse.urlencode(params or {})
        data = json.dumps(body, separators=(",", ":")) if body is not None else ""
        ts = str(int(time.time() * 1000) + self._offset_ms)
        headers = {"ACCESS-KEY": self._key, "ACCESS-PASSPHRASE": self._pass, "ACCESS-TIMESTAMP": ts,
                   "ACCESS-SIGN": sign(self._secret, ts, method, path, query, data),
                   "Content-Type": "application/json", "locale": "en-US", "User-Agent": "bot7/weex"}
        url = base + path + (("?" + query) if query else "")
        req = urllib.request.Request(url, data=data.encode() if data else None, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raise WeexError(f"HTTP {e.code}: {e.read().decode(errors='ignore')[:300]}") from None

    def get(self, base: str, path: str, params: dict | None = None):
        return self._signed("GET", base, path, params)

    def post(self, base: str, path: str, body: dict):
        return self._signed("POST", base, path, body=body)

    def delete(self, base: str, path: str, params: dict):
        return self._signed("DELETE", base, path, params)

    # --- торговля (используется только сеткой services/weex_grid, оператор 09.10.2026:
    # «делай на этом ключе»; ордера сетки помечаются префиксом clientOrderId)
    def book(self, symbol: str) -> tuple[float, float]:
        r = self._http(FUTURES + "/capi/v3/market/ticker/bookTicker?symbol=" + symbol)
        r = r[0] if isinstance(r, list) else r
        return float(r["bidPrice"]), float(r["askPrice"])

    def open_orders(self, symbol: str) -> list[dict]:
        out, page = [], 0
        while True:
            chunk = self.get(FUTURES, "/capi/v3/openOrders", {"symbol": symbol, "limit": 100, "page": page})
            out.extend(chunk or [])
            if not chunk or len(chunk) < 100 or page >= 9:
                return out
            page += 1

    def order_history(self, symbol: str, limit: int = 100, page: int = 0,
                      start_ms: int | None = None, end_ms: int | None = None) -> list[dict]:
        """Ордера символа (вес 10), с окном по времени и постранично — поиск ордера по clientOrderId,
        когда ответ на постановку потерян."""
        p = {"symbol": symbol, "limit": limit, "page": page}
        if start_ms is not None:
            p["startTime"] = int(start_ms)
        if end_ms is not None:
            p["endTime"] = int(end_ms)
        return self.get(FUTURES, "/capi/v3/order/history", p) or []

    def order_info(self, order_id: str | int) -> dict:
        return self.get(FUTURES, "/capi/v3/order", {"orderId": order_id})

    def place_limit(self, symbol: str, side: str, position_side: str, qty: str, price: str, cid: str,
                    reduce_only: bool = False, post_only: bool = True) -> dict:
        body = {"symbol": symbol, "side": side, "positionSide": position_side, "type": "LIMIT",
                "timeInForce": "POST_ONLY" if post_only else "GTC", "quantity": qty, "price": price,
                "newClientOrderId": cid, "reduceOnly": reduce_only}
        return self.post(FUTURES, "/capi/v3/order", body)

    def place_market(self, symbol: str, side: str, position_side: str, qty: str, cid: str,
                     reduce_only: bool = False) -> dict:
        """Рыночный ордер (трендовый бот: вход по сигналу, выход по закрытию 4ч за стопом)."""
        body = {"symbol": symbol, "side": side, "positionSide": position_side, "type": "MARKET",
                "quantity": qty, "newClientOrderId": cid, "reduceOnly": reduce_only}
        return self.post(FUTURES, "/capi/v3/order", body)

    def place_stop_market(self, symbol: str, side: str, position_side: str, qty: str, trigger: str,
                          cid: str) -> dict:
        """Условный STOP_MARKET reduceOnly с ЯВНЫМ объёмом (не «вся позиция» — на ней могут быть ручные
        сделки): аварийный стоп трендового бота на самой бирже."""
        body = {"symbol": symbol, "side": side, "positionSide": position_side, "type": "STOP_MARKET",
                "quantity": qty, "triggerPrice": trigger, "clientAlgoId": cid, "reduceOnly": True,
                "workingType": "CONTRACT_PRICE"}
        return self.post(FUTURES, "/capi/v3/algoOrder", body)

    def open_algo_orders(self, symbol: str) -> list[dict]:
        out, page = [], 1
        while True:
            chunk = self.get(FUTURES, "/capi/v3/openAlgoOrders", {"symbol": symbol, "limit": 100, "page": page}) or []
            out.extend(chunk)
            if len(chunk) < 100 or page >= 10:
                return out
            page += 1

    def algo_history(self, symbol: str, start_ms: int | None = None, end_ms: int | None = None) -> list[dict]:
        """История условных ордеров (сработал ли аварийный стоп и по какой цене)."""
        p = {"symbol": symbol, "limit": 500}
        if start_ms is not None:
            p["startTime"] = int(start_ms)
        if end_ms is not None:
            p["endTime"] = int(end_ms)
        r = self.get(FUTURES, "/capi/v3/allAlgoOrders", p) or {}
        return r.get("orders", []) if isinstance(r, dict) else r

    def cancel_algo(self, algo_id: str | int) -> dict:
        return self.delete(FUTURES, "/capi/v3/algoOrder", {"orderId": algo_id})

    def cancel(self, order_id: str | int) -> dict:
        return self.delete(FUTURES, "/capi/v3/order", {"orderId": order_id})

    def user_trades(self, symbol: str, order_id: str | int | None = None,
                    start_ms: int | None = None, end_ms: int | None = None) -> list[dict]:
        """Сделки (вес 5), до 100 за запрос; окно startTime..endTime не длиннее 7 суток."""
        p = {"symbol": symbol, "limit": 100}
        if order_id is not None:
            p["orderId"] = order_id
        if start_ms is not None:
            p["startTime"] = int(start_ms)
        if end_ms is not None:
            p["endTime"] = int(end_ms)
        return self.get(FUTURES, "/capi/v3/userTrades", p)

    # --- фьючерсы
    def futures_balance(self):
        return self.get(FUTURES, "/capi/v3/account/balance")

    def futures_positions(self):
        return self.get(FUTURES, "/capi/v3/account/position/allPosition")

    def futures_commission(self, symbol: str = "BTCUSDT"):
        return self.get(FUTURES, "/capi/v3/account/commissionRate", {"symbol": symbol})

    # --- спот
    def spot_account(self):
        return self.get(SPOT, "/api/v3/account")
