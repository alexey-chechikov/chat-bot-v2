"""Публичные часовые бары и фандинг USDT-фьючерсов Binance для проверки PREREG_portrait.md. Только чтение, без ключей. Файлы — в scratchpad, не в git."""
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

DIR = cw.SCR / "holdout" / "coins"
DIR.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 research"}
COINS = ("LTC", "BNB", "ADA", "LINK", "SOL", "DOGE", "ETC", "TRX", "DOT", "AVAX")
BASE = "https://fapi.binance.com/fapi/v1/"
START = cw.T("2019-09-01") * 1000
END = cw.T("2026-11-05") * 1000


def get(path, params):
    req = urllib.request.Request(BASE + path + "?" + urllib.parse.urlencode(params), headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def klines(sym):
    p = DIR / f"{sym}_1h.csv"
    if p.exists():
        return
    t, rows = START, []
    while t < END:
        d = get("klines", {"symbol": sym, "interval": "1h", "startTime": t, "limit": 1500})
        if not d:
            break
        rows += [x[:6] for x in d]
        t = int(d[-1][0]) + 3600_000
        time.sleep(0.15)
    f = pd.DataFrame(rows, columns=["ms", "open", "high", "low", "close", "volume"]).astype(float).drop_duplicates("ms").sort_values("ms")
    f = f[f["ms"] < END]
    f.to_csv(p, index=False)
    print(sym, "бары", len(f), pd.Timestamp(f["ms"].iloc[0], unit="ms"), pd.Timestamp(f["ms"].iloc[-1], unit="ms"), flush=True)


def funding(sym):
    p = DIR / f"{sym}_funding.csv"
    if p.exists():
        return
    t, rows = START, []
    while t < END:
        d = get("fundingRate", {"symbol": sym, "startTime": t, "limit": 1000})
        if not d:
            break
        rows += [(x["fundingTime"], x["fundingRate"]) for x in d]
        t = int(d[-1]["fundingTime"]) + 1
        time.sleep(0.15)
    f = pd.DataFrame(rows, columns=["ms", "rate"]).astype(float).drop_duplicates("ms").sort_values("ms")
    f.to_csv(p, index=False)
    print(sym, "фандинг", len(f), flush=True)


if __name__ == "__main__":
    for c in COINS:
        klines(c + "USDT")
        funding(c + "USDT")
