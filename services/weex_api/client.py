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


class WeexIncomplete(WeexError):
    """Список ордеров не прочитан целиком (достигнут предел страниц или страница — не список): решения по
    владению/сиротам по нему принимать нельзя (разбор GPT 13.10: 10 полных страниц молча выдавались за полный
    список). Проход сетки прерывается до разбора сирот; трендовый бот считает намерение невыясненным."""


MAX_PAGES = 10


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

    def _open_pages(self, path: str, symbol: str, first_page: int) -> list[dict]:
        """Постраничный список открытых ордеров. Неполный ответ — WeexIncomplete, а не обрезанный список
        (13.10, разбор GPT: после 10 полных страниц по 100 список молча считался полным): все MAX_PAGES страниц
        полные или страница — не список (объект ошибки превращался в «список» из его ключей; 15.10, разбор GPT P1:
        null и {} через «or []» становились пустым полным списком — документация WEEX: ответ — массив)."""
        out = []
        for page in range(first_page, first_page + MAX_PAGES):
            chunk = self.get(FUTURES, path, {"symbol": symbol, "limit": 100, "page": page})
            if not isinstance(chunk, list):
                raise WeexIncomplete(f"{path} {symbol}: страница {page} — не список ({str(chunk)[:120]})")
            out.extend(chunk)
            if len(chunk) < 100:
                return out
        raise WeexIncomplete(f"{path} {symbol}: {MAX_PAGES} полных страниц по 100 — список может быть неполным")

    def open_orders(self, symbol: str) -> list[dict]:
        """Все открытые ордера символа (страницы с 0); неполный ответ — WeexIncomplete."""
        return self._open_pages("/capi/v3/openOrders", symbol, 0)

    def order_history(self, symbol: str, limit: int = 100, page: int = 0,
                      start_ms: int | None = None, end_ms: int | None = None) -> list[dict]:
        """Ордера символа (вес 10), с окном по времени и постранично — поиск ордера по clientOrderId,
        когда ответ на постановку потерян. Ответ WEEX — массив ордеров (документация; чтение со счёта 13.10).
        Не массив (null, {}, объект ошибки) — WeexIncomplete, а не «пустая полная история» (15.10, разбор GPT P1:
        «or []» превращал такой ответ в доказательство, что ордер не дошёл, и после TTL ставился второй вход)."""
        p = {"symbol": symbol, "limit": limit, "page": page}
        if start_ms is not None:
            p["startTime"] = int(start_ms)
        if end_ms is not None:
            p["endTime"] = int(end_ms)
        r = self.get(FUTURES, "/capi/v3/order/history", p)
        if not isinstance(r, list):
            raise WeexIncomplete(f"/capi/v3/order/history {symbol}: страница {page} — не список ({str(r)[:120]})")
        return r

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
        """Все открытые условные ордера символа (страницы с 1); неполный ответ — WeexIncomplete."""
        return self._open_pages("/capi/v3/openAlgoOrders", symbol, 1)

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
