"""Публичные данные лаборатории: часовые бары и фандинг. Только чтение публичных API, без ключей.

Отсечка END жёсткая: всё, что позже 07.11.2026 00:00 UTC, резерв Мака и сюда не попадает.
Резервные монеты (раздел 5 задания) в списках отсутствуют, их загрузка запрещена проверкой в fetch_all.
Каталог данных вне git: переменная LAB_DATA или C:\\bot7\\tmp\\indicator_lab_data.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

DATA = Path(os.environ.get("LAB_DATA", r"C:\bot7\tmp\indicator_lab_data"))
UA = {"User-Agent": "Mozilla/5.0 research"}
END = int(pd.Timestamp("2026-11-07", tz="UTC").timestamp()) * 1000
RESERVE = {"XMR", "DASH", "ZEC", "ONT", "IOTA", "BAT", "NEO", "QTUM", "IOST", "THETA", "ZIL", "KNC", "ZRX", "COMP", "KAVA", "BAND", "RLC", "SNX", "SKL", "YFI"}
COINS20 = ("LTC", "BNB", "ADA", "LINK", "SOL", "DOGE", "ETC", "TRX", "DOT", "AVAX", "BCH", "XLM", "ATOM", "ALGO", "FIL", "AAVE", "UNI", "NEAR", "VET", "XTZ")
SPOT = "https://api.binance.com/api/v3/klines"
FAPI = "https://fapi.binance.com/fapi/v1/"
COLS = ["ms", "open", "high", "low", "close", "volume", "quote", "trades", "taker_base", "taker_quote"]


def get(url, params, tries=6):
    q = url + ("?" + urllib.parse.urlencode(params) if params else "")
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(q, headers=UA), timeout=40) as r:
                return json.loads(r.read())
        except Exception as e:  # сеть и 429: пауза и повтор, в конце отказ
            if k == tries - 1:
                raise RuntimeError(f"{q}: {e}") from e
            time.sleep(2 + 3 * k)


def _klines(url, sym, start_ms, limit):
    rows, t = [], start_ms
    while t < END:
        d = get(url, {"symbol": sym, "interval": "1h", "startTime": t, "limit": limit})
        if not d:
            break
        rows += [[x[0], x[1], x[2], x[3], x[4], x[5], x[7], x[8], x[9], x[10]] for x in d]
        t = int(d[-1][0]) + 3_600_000
        time.sleep(0.06)
    f = pd.DataFrame(rows, columns=COLS).astype(float).drop_duplicates("ms").sort_values("ms")
    f["ms"] = f["ms"].astype("int64")
    return f[f["ms"] + 3_600_000 <= END]


def spot(sym):
    p = DATA / f"spot_{sym}_1h.csv"
    if not p.exists():
        _klines(SPOT, sym, 1502928000000, 1000).to_csv(p, index=False)
    return p


def perp(sym):
    p = DATA / f"um_{sym}_1h.csv"
    if not p.exists():
        _klines(FAPI + "klines", sym, 1567296000000, 1500).to_csv(p, index=False)
    return p


def funding(sym):
    p = DATA / f"um_{sym}_funding.csv"
    if p.exists():
        return p
    rows, t = [], 1567296000000
    while t < END:
        d = get(FAPI + "fundingRate", {"symbol": sym, "startTime": t, "limit": 1000})
        if not d:
            break
        rows += [(int(x["fundingTime"]), float(x["fundingRate"])) for x in d]
        t = int(d[-1]["fundingTime"]) + 1
        time.sleep(0.06)
    f = pd.DataFrame(rows, columns=["ms", "rate"]).drop_duplicates("ms").sort_values("ms")
    f[f["ms"] < END].to_csv(p, index=False)
    return p


def bitstamp():
    p = DATA / "bitstamp_btcusd_1h.csv"
    if p.exists():
        return p
    t, stop, rows = int(pd.Timestamp("2013-01-01", tz="UTC").timestamp()), int(pd.Timestamp("2018-01-02", tz="UTC").timestamp()), []
    while t < stop:
        d = get("https://www.bitstamp.net/api/v2/ohlc/btcusd/", {"step": 3600, "limit": 1000, "start": t})["data"]["ohlc"]
        if not d:
            t += 3600 * 1000
            continue
        rows += d
        t = int(d[-1]["timestamp"]) + 3600
        time.sleep(0.25)
    f = pd.DataFrame(rows).astype(float).drop_duplicates("timestamp").sort_values("timestamp")
    f[f["timestamp"] < stop].to_csv(p, index=False)
    return p


def bybit():
    p = DATA / "bybit_BTCUSDT_1h.csv"
    if p.exists():
        return p
    t, rows = int(pd.Timestamp("2020-03-25", tz="UTC").timestamp()) * 1000, []
    while t < END:
        d = get("https://api.bybit.com/v5/market/kline", {"category": "linear", "symbol": "BTCUSDT", "interval": 60, "start": t, "limit": 1000})["result"]["list"]
        if not d:
            break
        rows += d
        t = max(int(x[0]) for x in d) + 3_600_000
        time.sleep(0.12)
    f = pd.DataFrame(rows, columns=["ms", "open", "high", "low", "close", "volume", "quote"]).astype(float).drop_duplicates("ms").sort_values("ms")
    f["ms"] = f["ms"].astype("int64")
    f[f["ms"] + 3_600_000 <= END].to_csv(p, index=False)
    return p


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def manifest():
    rows = []
    for p in sorted(DATA.glob("*.csv")):
        if p.name == "manifest.csv":
            continue
        f = pd.read_csv(p)
        col = "ms" if "ms" in f else f.columns[0] if "timestamp" not in f else "timestamp"
        rows.append({"файл": p.name, "строк": len(f), "первый": f[col].iloc[0], "последний": f[col].iloc[-1], "sha256": sha(p)})
    pd.DataFrame(rows).to_csv(DATA / "manifest.csv", index=False)
    return rows


def fetch_all():
    DATA.mkdir(parents=True, exist_ok=True)
    assert not RESERVE & set(COINS20), "резервная монета в списке"
    for s in ("BTCUSDT", "ETHUSDT"):
        spot(s)
        funding(s)
        print(s, "готово", flush=True)
    perp("BTCUSDT")
    perp("XRPUSDT")
    funding("XRPUSDT")
    print("XRP готово", flush=True)
    bitstamp()
    print("bitstamp готово", flush=True)
    bybit()
    print("bybit готово", flush=True)
    if "--coins" in sys.argv:
        for c in COINS20:
            perp(c + "USDT")
            funding(c + "USDT")
            print(c, "готово", flush=True)
    for r in manifest():
        print(r["файл"], r["строк"], r["sha256"][:16], flush=True)


if __name__ == "__main__":
    fetch_all()
