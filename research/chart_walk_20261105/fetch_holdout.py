"""Публичные часовые бары для проверки на новых данных (PREREG_gpt_check.md): BTCUSD Bitstamp 2013–2017, BTCUSDT linear Bybit с 2020 и его фандинг.
Только чтение публичных API, без ключей. Файлы — в scratchpad, не в git."""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402

DIR = cw.SCR / "holdout"
DIR.mkdir(exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 research"}


def get(url, params):
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def bitstamp():
    p = DIR / "bitstamp_btcusd_1h.csv"
    if p.exists():
        return
    t, end, rows = cw.T("2013-01-01"), cw.T("2018-01-02"), []
    while t < end:
        d = get("https://www.bitstamp.net/api/v2/ohlc/btcusd/", {"step": 3600, "limit": 1000, "start": t})["data"]["ohlc"]
        if not d:
            t += 3600 * 1000
            continue
        rows += d
        t = int(d[-1]["timestamp"]) + 3600
        time.sleep(0.5)
    f = pd.DataFrame(rows).astype(float).drop_duplicates("timestamp").sort_values("timestamp")
    f = f[f["timestamp"] < end]
    f.to_csv(p, index=False)
    print("bitstamp", len(f), pd.Timestamp(f["timestamp"].iloc[0], unit="s"), pd.Timestamp(f["timestamp"].iloc[-1], unit="s"), flush=True)


def bybit():
    p = DIR / "bybit_btcusdt_1h.csv"
    if not p.exists():
        t, end, rows = cw.T("2020-03-25") * 1000, cw.T("2026-11-05") * 1000, []
        while t < end:
            d = get("https://api.bybit.com/v5/market/kline", {"category": "linear", "symbol": "BTCUSDT", "interval": 60, "start": t, "limit": 1000})["result"]["list"]
            if not d:
                break
            rows += d
            t = max(int(x[0]) for x in d) + 3600_000
            time.sleep(0.2)
        f = pd.DataFrame(rows, columns=["ms", "open", "high", "low", "close", "volume", "turnover"]).astype(float).drop_duplicates("ms").sort_values("ms")
        f.to_csv(p, index=False)
        print("bybit", len(f), pd.Timestamp(f["ms"].iloc[0], unit="ms"), pd.Timestamp(f["ms"].iloc[-1], unit="ms"), flush=True)
    p = DIR / "bybit_btcusdt_funding.csv"
    if not p.exists():
        end, start, rows = cw.T("2026-11-05") * 1000, cw.T("2020-03-25") * 1000, []
        while end > start:
            d = get("https://api.bybit.com/v5/market/funding/history", {"category": "linear", "symbol": "BTCUSDT", "startTime": start, "endTime": end, "limit": 200})["result"]["list"]
            if not d:
                break
            rows += d
            end = min(int(x["fundingRateTimestamp"]) for x in d) - 1
            time.sleep(0.2)
        f = pd.DataFrame(rows)[["fundingRateTimestamp", "fundingRate"]].astype(float).drop_duplicates("fundingRateTimestamp").sort_values("fundingRateTimestamp")
        f.to_csv(p, index=False)
        print("bybit фандинг", len(f), pd.Timestamp(f["fundingRateTimestamp"].iloc[0], unit="ms"), pd.Timestamp(f["fundingRateTimestamp"].iloc[-1], unit="ms"), flush=True)


if __name__ == "__main__":
    bitstamp()
    bybit()
