"""Thin signed REST client for the BitMEX autotrader sub-account.

Reads creds from env (BITMEX_AUTOTRADER_API_KEY / _SECRET). Permissions
expected on this key: ["order"] only — no withdraw.

Public surface kept minimal — only what auto_executor needs:
  - get_instrument(symbol)           — for tickSize/lotSize/lastPrice
  - get_position(symbol)             — currentQty + avgEntryPrice
  - get_margin()                     — USDt wallet balance/available
  - place_limit_buy(...)             — post-only LIMIT BUY (open long)
  - place_market_exit_long(...)      — market SELL to flatten long
  - place_limit_sell(...)            — post-only LIMIT SELL (open short)
  - place_market_exit_short(...)     — market BUY to flatten short
  - cancel_order(order_id)           — best-effort cancel
  - get_order(order_id)              — status lookup

All write methods raise on HTTP != 200 — caller is responsible for retries.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any, Optional
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://www.bitmex.com"


class BitMEXError(Exception):
    """Raised for non-200 responses; carries status and body."""

    def __init__(self, status: int, body: str):
        super().__init__(f"BitMEX HTTP {status}: {body[:200]}")
        self.status = status
        self.body = body


class BitMEXClient:
    def __init__(self, api_key: str, api_secret: str, base_url: str = BASE_URL,
                 timeout: float = 10.0):
        if not api_key or not api_secret:
            raise ValueError("api_key and api_secret are required")
        self._key = api_key
        self._secret = api_secret
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()

    @classmethod
    def from_env(cls) -> "BitMEXClient":
        key = os.environ.get("BITMEX_AUTOTRADER_API_KEY", "").strip()
        sec = os.environ.get("BITMEX_AUTOTRADER_API_SECRET", "").strip()
        if not key or not sec:
            raise RuntimeError(
                "BITMEX_AUTOTRADER_API_KEY / BITMEX_AUTOTRADER_API_SECRET not set"
            )
        return cls(key, sec)

    # ─── signing ─────────────────────────────────────────────────────
    def _sign(self, verb: str, path: str, expires: int, body: str = "") -> str:
        msg = f"{verb}{path}{expires}{body}"
        return hmac.new(
            self._secret.encode("utf-8"),
            msg.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _request(self, verb: str, path: str, params: Optional[dict] = None,
                  body: Optional[dict] = None, signed: bool = True) -> Any:
        url = self._base + path
        body_str = ""
        if body is not None:
            body_str = json.dumps(body, separators=(",", ":"))
        full_path = path
        if params:
            qs = urlencode(params, doseq=True)
            url = url + "?" + qs
            full_path = path + "?" + qs
        headers: dict = {"Content-Type": "application/json"}
        if signed:
            expires = int(time.time()) + 30
            sig = self._sign(verb, full_path, expires, body_str)
            headers["api-expires"] = str(expires)
            headers["api-key"] = self._key
            headers["api-signature"] = sig
        try:
            r = self._session.request(
                verb, url, data=(body_str or None), headers=headers,
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            logger.warning("bitmex_autotrader.request_failed verb=%s path=%s err=%s",
                            verb, path, exc)
            raise BitMEXError(0, str(exc)) from exc
        if r.status_code != 200:
            logger.warning("bitmex_autotrader.http_status verb=%s path=%s code=%d body=%s",
                            verb, path, r.status_code, r.text[:300])
            raise BitMEXError(r.status_code, r.text)
        try:
            return r.json()
        except ValueError as exc:
            raise BitMEXError(r.status_code, r.text) from exc

    # ─── read-only ──────────────────────────────────────────────────
    def get_instrument(self, symbol: str) -> dict:
        """Public — instrument metadata. Used for tickSize/lotSize/lastPrice."""
        r = self._request("GET", "/api/v1/instrument",
                          params={"symbol": symbol}, signed=False)
        if not isinstance(r, list) or not r:
            raise BitMEXError(200, f"empty instrument response for {symbol}")
        return r[0]

    def get_last_price(self, symbol: str) -> float:
        i = self.get_instrument(symbol)
        return float(i.get("lastPrice") or i.get("markPrice") or 0.0)

    def get_position(self, symbol: str) -> Optional[dict]:
        """Returns single position dict or None if no position open."""
        r = self._request("GET", "/api/v1/position",
                          params={"filter": json.dumps({"symbol": symbol})})
        if not isinstance(r, list) or not r:
            return None
        for p in r:
            if p.get("symbol") == symbol and (p.get("currentQty") or 0) != 0:
                return p
        return None

    def get_margin(self, currency: str = "USDt") -> dict:
        """USDt wallet for linear contracts. XBt for inverse."""
        return self._request(
            "GET", "/api/v1/user/margin", params={"currency": currency}
        )

    def get_order(self, order_id: str) -> Optional[dict]:
        r = self._request("GET", "/api/v1/order",
                          params={"filter": json.dumps({"orderID": order_id})})
        if not isinstance(r, list) or not r:
            return None
        return r[0]

    def get_open_orders(self, symbol: str) -> list[dict]:
        r = self._request("GET", "/api/v1/order",
                          params={"symbol": symbol, "filter":
                                  json.dumps({"open": True})})
        return r if isinstance(r, list) else []

    # ─── write ──────────────────────────────────────────────────────
    def place_limit_buy(self, symbol: str, qty_lots: int, price: float,
                         cl_ord_id: Optional[str] = None,
                         post_only: bool = True) -> dict:
        """LIMIT BUY for opening LONG. post_only=True asks BitMEX to reject
        the order if it would take liquidity (we want maker rebate)."""
        body: dict = {
            "symbol": symbol,
            "side": "Buy",
            "orderQty": int(qty_lots),
            "price": float(price),
            "ordType": "Limit",
        }
        if post_only:
            body["execInst"] = "ParticipateDoNotInitiate"
        if cl_ord_id:
            body["clOrdID"] = cl_ord_id
        return self._request("POST", "/api/v1/order", body=body)

    def place_market_exit_long(self, symbol: str, qty_lots: int,
                                cl_ord_id: Optional[str] = None) -> dict:
        """Market SELL to flatten a long. execInst Close = position-aware."""
        body: dict = {
            "symbol": symbol,
            "side": "Sell",
            "orderQty": int(qty_lots),
            "ordType": "Market",
            "execInst": "Close",
        }
        if cl_ord_id:
            body["clOrdID"] = cl_ord_id
        return self._request("POST", "/api/v1/order", body=body)

    def place_limit_sell(self, symbol: str, qty_lots: int, price: float,
                         cl_ord_id: Optional[str] = None,
                         post_only: bool = True) -> dict:
        """LIMIT SELL for opening SHORT (2026-05-29). Mirror of place_limit_buy.
        post_only asks BitMEX to reject if it would take liquidity (maker rebate)."""
        body: dict = {
            "symbol": symbol,
            "side": "Sell",
            "orderQty": int(qty_lots),
            "price": float(price),
            "ordType": "Limit",
        }
        if post_only:
            body["execInst"] = "ParticipateDoNotInitiate"
        if cl_ord_id:
            body["clOrdID"] = cl_ord_id
        return self._request("POST", "/api/v1/order", body=body)

    def place_market_exit_short(self, symbol: str, qty_lots: int,
                                 cl_ord_id: Optional[str] = None) -> dict:
        """Market BUY to flatten a short. execInst Close = position-aware."""
        body: dict = {
            "symbol": symbol,
            "side": "Buy",
            "orderQty": int(qty_lots),
            "ordType": "Market",
            "execInst": "Close",
        }
        if cl_ord_id:
            body["clOrdID"] = cl_ord_id
        return self._request("POST", "/api/v1/order", body=body)

    def cancel_order(self, order_id: str) -> list[dict]:
        return self._request("DELETE", "/api/v1/order",
                              params={"orderID": order_id})

    def cancel_all(self, symbol: str) -> list[dict]:
        return self._request("DELETE", "/api/v1/order/all",
                              params={"symbol": symbol})
