from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Tuple

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

INTERVAL_MAP: Dict[str, str] = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "1d": "1d",
}

_logger = logging.getLogger(__name__)

_session = requests.Session()
_retry = Retry(total=3, connect=3, read=3, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))
_adapter = HTTPAdapter(max_retries=_retry)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)

_CACHE_TTL_SECONDS = 12.0
_CACHE_LOCK = threading.RLock()
_KLINES_CACHE: Dict[Tuple[str, str, int], Tuple[float, pd.DataFrame]] = {}


def _copy_df(df: pd.DataFrame) -> pd.DataFrame:
    return df.copy(deep=True)


def clear_klines_cache() -> None:
    with _CACHE_LOCK:
        _KLINES_CACHE.clear()


def get_klines_cache_info() -> Dict[str, float]:
    with _CACHE_LOCK:
        return {
            "ttl_seconds": _CACHE_TTL_SECONDS,
            "entries": float(len(_KLINES_CACHE)),
        }


def _fetch_klines(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
    _logger.info("binance.klines.fetch symbol=%s timeframe=%s limit=%s", symbol.upper(), interval, limit)
    r = _session.get(url, params=params, timeout=(5, 15))
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list) or not data:
        raise RuntimeError("Пустой ответ Binance")

    cols = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "number_of_trades",
        "taker_buy_base", "taker_buy_quote", "ignore",
    ]
    df = pd.DataFrame(data, columns=cols)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    return df.dropna().reset_index(drop=True)


def load_klines(symbol: str = "BTCUSDT", timeframe: str = "1h", limit: int = 300, use_cache: bool = True) -> pd.DataFrame:
    interval = INTERVAL_MAP.get(timeframe, "1h")
    cache_key = (symbol.upper(), interval, int(limit))
    now = time.time()

    if use_cache:
        with _CACHE_LOCK:
            cached = _KLINES_CACHE.get(cache_key)
            if cached and (now - cached[0]) <= _CACHE_TTL_SECONDS:
                _logger.info("binance.klines.cache_hit symbol=%s timeframe=%s limit=%s", symbol.upper(), interval, limit)
                return _copy_df(cached[1])

    df = _fetch_klines(symbol=symbol, interval=interval, limit=limit)

    if use_cache:
        with _CACHE_LOCK:
            _KLINES_CACHE[cache_key] = (now, _copy_df(df))

    return _copy_df(df)

_HIST_CACHE_TTL_SECONDS = 3600.0
_HIST_KLINES_CACHE: Dict[Tuple[str, str, int, int], Tuple[float, pd.DataFrame]] = {}


def _to_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _fetch_klines_with_range(symbol: str, interval: str, start_ms: int, end_ms: int, limit: int = 1000) -> pd.DataFrame:
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": symbol.upper(),
        "interval": interval,
        "startTime": int(start_ms),
        "endTime": int(end_ms),
        "limit": int(limit),
    }
    r = _session.get(url, params=params, timeout=(5, 20))
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list) or not data:
        return pd.DataFrame(columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "number_of_trades",
            "taker_buy_base", "taker_buy_quote", "ignore",
        ])
    cols = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "number_of_trades",
        "taker_buy_base", "taker_buy_quote", "ignore",
    ]
    df = pd.DataFrame(data, columns=cols)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    return df.dropna().reset_index(drop=True)


def load_historical_klines(symbol: str = "BTCUSDT", timeframe: str = "1h", start_ms: int | None = None, end_ms: int | None = None, use_cache: bool = True) -> pd.DataFrame:
    interval = INTERVAL_MAP.get(timeframe, "1h")
    if start_ms is None or end_ms is None or end_ms <= start_ms:
        return pd.DataFrame()
    cache_key = (symbol.upper(), interval, int(start_ms), int(end_ms))
    now = time.time()
    if use_cache:
        with _CACHE_LOCK:
            cached = _HIST_KLINES_CACHE.get(cache_key)
            if cached and (now - cached[0]) <= _HIST_CACHE_TTL_SECONDS:
                return _copy_df(cached[1])

    all_parts = []
    cursor = int(start_ms)
    while cursor < int(end_ms):
        part = _fetch_klines_with_range(symbol=symbol, interval=interval, start_ms=cursor, end_ms=end_ms, limit=1000)
        if part.empty:
            break
        all_parts.append(part)
        last_open = int(part["open_time"].iloc[-1].timestamp() * 1000)
        next_cursor = last_open + 1
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(part) < 1000:
            break

    if not all_parts:
        return pd.DataFrame()

    df = pd.concat(all_parts, ignore_index=True).drop_duplicates(subset=["open_time"]).sort_values("open_time").reset_index(drop=True)
    if use_cache:
        with _CACHE_LOCK:
            _HIST_KLINES_CACHE[cache_key] = (now, _copy_df(df))
    return _copy_df(df)


def load_year_klines(symbol: str = "BTCUSDT", timeframe: str = "1h", year: int = 2025, use_cache: bool = True) -> pd.DataFrame:
    start_ms = _to_ms(datetime(year, 1, 1, tzinfo=timezone.utc))
    end_ms = _to_ms(datetime(year + 1, 1, 1, tzinfo=timezone.utc))
    return load_historical_klines(symbol=symbol, timeframe=timeframe, start_ms=start_ms, end_ms=end_ms, use_cache=use_cache)
