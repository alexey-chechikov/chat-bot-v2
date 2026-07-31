"""Live deriv poll loop. See package __init__ for context."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

DERIV_LIVE_PATH = Path("state/deriv_live.json")
HISTORY_PATH = Path("state/deriv_live_history.jsonl")  # append-only за час для расчёта delta
# 2026-07-31: добавлены SOL и AVAX — оператор запустил по ним боты на OKX,
# а харвестеру нужна РЕАЛЬНАЯ цена (market_mark из этого файла), иначе он
# по ним просто молчит (fail-safe). Без цены = без фиксации плюсовых ордеров.
SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "AVAXUSDT"]
POLL_INTERVAL_SEC = 300  # 5 min


def _binance_get(path: str, params: dict[str, Any], timeout: float = 10) -> Any | None:
    url = f"https://fapi.binance.com{path}"
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        if resp.status_code != 200:
            logger.warning("deriv_live.http_status code=%d path=%s", resp.status_code, path)
            return None
        return resp.json()
    except requests.RequestException:
        logger.exception("deriv_live.http_failed path=%s", path)
        return None


def _fetch_oi(symbol: str) -> dict | None:
    """GET /fapi/v1/openInterest (current OI in BTC)."""
    data = _binance_get("/fapi/v1/openInterest", {"symbol": symbol})
    if not data:
        return None
    try:
        return {"oi_native": float(data["openInterest"]), "ts_ms": int(data.get("time", 0))}
    except (KeyError, ValueError, TypeError):
        return None


def _fetch_funding(symbol: str) -> dict | None:
    """GET /fapi/v1/premiumIndex (current funding + premium + mark)."""
    data = _binance_get("/fapi/v1/premiumIndex", {"symbol": symbol})
    if not data:
        return None
    try:
        return {
            "funding_rate_8h": float(data.get("lastFundingRate", 0)),
            "next_funding_time_ms": int(data.get("nextFundingTime", 0)),
            "mark_price": float(data.get("markPrice", 0)),
            "index_price": float(data.get("indexPrice", 0)),
        }
    except (ValueError, TypeError):
        return None


def _fetch_oi_hist_1h(symbol: str) -> float | None:
    """GET /futures/data/openInterestHist limit=2 → compute 1h-ago OI for delta."""
    data = _binance_get(
        "/futures/data/openInterestHist",
        {"symbol": symbol, "period": "1h", "limit": 2},
    )
    if not data or not isinstance(data, list) or len(data) < 1:
        return None
    try:
        # data[0] = oldest, data[-1] = newest
        # We want oldest one (1h ago)
        return float(data[0].get("sumOpenInterest", 0))
    except (KeyError, ValueError, TypeError):
        return None


def _fetch_binance_long_short(symbol: str) -> dict | None:
    """Binance global account L/S + top trader + taker buy/sell — 5min snapshot.

    3 endpoints (free, no auth):
      /futures/data/globalLongShortAccountRatio  — все аккаунты
      /futures/data/topLongShortPositionRatio    — top traders, по объёму позиций
      /futures/data/takerlongshortRatio          — taker buy/sell volume
    """
    out: dict = {}
    # 1) Global accounts
    data = _binance_get(
        "/futures/data/globalLongShortAccountRatio",
        {"symbol": symbol, "period": "5m", "limit": 1},
    )
    if isinstance(data, list) and data:
        try:
            r = data[0]
            out["global_long_account_pct"] = round(float(r["longAccount"]) * 100, 1)
            out["global_short_account_pct"] = round(float(r["shortAccount"]) * 100, 1)
            out["global_ls_ratio"] = round(float(r["longShortRatio"]), 3)
        except (KeyError, ValueError, TypeError):
            pass
    # 2) Top trader positions (smart money по объёму)
    data = _binance_get(
        "/futures/data/topLongShortPositionRatio",
        {"symbol": symbol, "period": "5m", "limit": 1},
    )
    if isinstance(data, list) and data:
        try:
            r = data[0]
            out["top_trader_long_pct"] = round(float(r["longAccount"]) * 100, 1)
            out["top_trader_short_pct"] = round(float(r["shortAccount"]) * 100, 1)
            out["top_trader_ls_ratio"] = round(float(r["longShortRatio"]), 3)
        except (KeyError, ValueError, TypeError):
            pass
    # 3) Taker buy/sell volume (последние 5 мин)
    data = _binance_get(
        "/futures/data/takerlongshortRatio",
        {"symbol": symbol, "period": "5m", "limit": 1},
    )
    if isinstance(data, list) and data:
        try:
            r = data[0]
            buy_vol = float(r["buyVol"])
            sell_vol = float(r["sellVol"])
            total = buy_vol + sell_vol
            if total > 0:
                out["taker_buy_pct"] = round(buy_vol / total * 100, 1)
                out["taker_sell_pct"] = round(sell_vol / total * 100, 1)
                out["taker_buy_sell_ratio"] = round(float(r["buySellRatio"]), 3)
        except (KeyError, ValueError, TypeError):
            pass
    return out or None


def _fetch_market_cap_global() -> dict | None:
    """CoinGecko /global — total market cap + BTC dominance (free, no auth).

    Rate limit: 30 calls/min. Cached в state снимке (poll каждые 5 мин = OK).
    """
    try:
        resp = requests.get("https://api.coingecko.com/api/v3/global", timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json().get("data", {})
        out: dict = {}
        # Total market cap USD
        mcap = data.get("total_market_cap", {})
        if isinstance(mcap, dict):
            out["total_mcap_usd"] = mcap.get("usd")
        # BTC dominance %
        dom = data.get("market_cap_percentage", {})
        if isinstance(dom, dict):
            out["btc_dominance_pct"] = round(float(dom.get("btc", 0)), 2)
            out["eth_dominance_pct"] = round(float(dom.get("eth", 0)), 2)
        # 24h change
        if "market_cap_change_percentage_24h_usd" in data:
            out["mcap_change_24h_pct"] = round(float(data["market_cap_change_percentage_24h_usd"]), 2)
        return out or None
    except (requests.RequestException, KeyError, ValueError, TypeError):
        return None


def _fetch_bybit_oi(symbol: str) -> float | None:
    """Bybit V5 GET /v5/market/open-interest — current OI for linear."""
    try:
        resp = requests.get(
            "https://api.bybit.com/v5/market/open-interest",
            params={"category": "linear", "symbol": symbol, "intervalTime": "5min", "limit": 1},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        lst = resp.json().get("result", {}).get("list", [])
        if not lst:
            return None
        return float(lst[0].get("openInterest", 0))
    except (requests.RequestException, KeyError, ValueError, TypeError):
        return None


def _fetch_bybit_long_short(symbol: str) -> dict | None:
    """Bybit V5 GET /v5/market/account-ratio — buy/sell ratio."""
    url = "https://api.bybit.com/v5/market/account-ratio"
    try:
        resp = requests.get(
            url,
            params={"category": "linear", "symbol": symbol, "period": "5min", "limit": 1},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        payload = resp.json()
        lst = payload.get("result", {}).get("list", [])
        if not lst:
            return None
        r = lst[0]
        buy = float(r["buyRatio"])
        sell = float(r["sellRatio"])
        return {
            "bybit_long_pct": round(buy * 100, 1),
            "bybit_short_pct": round(sell * 100, 1),
            "bybit_ls_ratio": round(buy / sell, 3) if sell > 0 else None,
        }
    except (requests.RequestException, KeyError, ValueError, TypeError):
        return None


def build_snapshot() -> dict:
    """Build single snapshot of all SYMBOLS. Returns dict ready to write."""
    out = {
        "last_updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    # Global market context (BTC.D, total mcap, eth.D) — fetched once per snapshot
    global_ctx = _fetch_market_cap_global()
    if global_ctx:
        out["global"] = global_ctx
    for sym in SYMBOLS:
        oi = _fetch_oi(sym)
        funding = _fetch_funding(sym)
        oi_1h_ago = _fetch_oi_hist_1h(sym)

        sym_data = {}
        if oi:
            sym_data["oi_native"] = oi["oi_native"]
            if oi_1h_ago and oi_1h_ago > 0:
                pct = (oi["oi_native"] / oi_1h_ago - 1) * 100
                sym_data["oi_change_1h_pct"] = round(pct, 3)
        if funding:
            sym_data["funding_rate_8h"] = funding["funding_rate_8h"]
            sym_data["mark_price"] = funding["mark_price"]
            sym_data["index_price"] = funding["index_price"]
            if funding["index_price"] > 0:
                premium = (funding["mark_price"] / funding["index_price"] - 1) * 100
                sym_data["premium_pct"] = round(premium, 4)
            sym_data["next_funding_time_ms"] = funding["next_funding_time_ms"]

        # Long/Short market sentiment (TZ-MARKET-LONG-SHORT-RATIO 2026-05-07)
        binance_ls = _fetch_binance_long_short(sym)
        if binance_ls:
            sym_data.update(binance_ls)
        bybit_ls = _fetch_bybit_long_short(sym)
        if bybit_ls:
            sym_data.update(bybit_ls)
        # Multi-exchange OI (A3, 2026-05-07): только для BTCUSDT (другие — низкий OI на Bybit)
        if sym == "BTCUSDT":
            bybit_oi = _fetch_bybit_oi(sym)
            if bybit_oi:
                sym_data["bybit_oi_native"] = bybit_oi
                if oi:
                    sym_data["total_oi_native"] = oi["oi_native"] + bybit_oi

        if sym_data:
            out[sym] = sym_data
        else:
            out[sym] = {"_error": "fetch_failed"}

    return out


def write_snapshot(snapshot: dict) -> None:
    DERIV_LIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DERIV_LIVE_PATH.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # Append history line for trend analysis
    try:
        with HISTORY_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("deriv_live.history_write_failed")


async def deriv_live_loop(stop_event: asyncio.Event, *, interval_sec: int = POLL_INTERVAL_SEC) -> None:
    """Async loop. Polls Binance REST every interval_sec until stop_event."""
    logger.info("deriv_live.loop.start interval=%ds symbols=%s", interval_sec, SYMBOLS)
    while not stop_event.is_set():
        t0 = time.time()
        try:
            snap = build_snapshot()
            write_snapshot(snap)
            errors = [k for k, v in snap.items() if isinstance(v, dict) and v.get("_error")]
            logger.info(
                "deriv_live.snapshot ok=%d errors=%d elapsed=%.1fs",
                len(SYMBOLS) - len(errors), len(errors), time.time() - t0,
            )
        except Exception:
            logger.exception("deriv_live.poll_failed")

        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            pass
    logger.info("deriv_live.loop.stopped")
