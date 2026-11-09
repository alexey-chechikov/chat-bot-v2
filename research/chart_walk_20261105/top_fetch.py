"""Часовые свечи USDT-фьючерсов Binance с объёмом агрессивных покупок и фандинг для PREREG_top_breadth_1108.md.
Публичный API, без ключей. Файлы — в scratchpad (cw.SCR/top), не в git. Свечи — только закрытые часы."""
from __future__ import annotations

import sys
import time
import urllib.error
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import fetch_coins as fc  # noqa: E402

DIR = cw.SCR / "top"
DIR.mkdir(parents=True, exist_ok=True)
TOP = ("BTC", "ETH", "XRP", "BNB", "SOL", "DOGE", "ADA", "TRX", "LINK", "AVAX", "SUI", "XLM", "HBAR", "TON", "BCH", "LTC", "DOT", "1000SHIB", "UNI", "NEAR", "HYPE", "AAVE", "1000PEPE", "APT")
START = cw.T("2019-09-01") * 1000
END = int(time.time()) // 3600 * 3600 * 1000
COLS = ["ms", "open", "high", "low", "close", "volume", "close_ms", "quote", "trades", "tb_base", "tb_quote"]


def get(path, params, tries=5):
    for k in range(tries):
        try:
            return fc.get(path, params)
        except urllib.error.HTTPError:
            raise
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(5 * (k + 1))


def universe():
    old = sorted(p.name.replace("USDT_1h.csv", "") for p in fc.DIR.glob("*USDT_1h.csv"))
    return list(TOP) + [c for c in old if c not in TOP]


def klines(sym):
    p = DIR / f"{sym}_1h.csv"
    if p.exists():
        return "есть"
    t, rows = START, []
    while t < END:
        d = get("klines", {"symbol": sym, "interval": "1h", "startTime": t, "limit": 1500})
        if not d:
            break
        rows += [x[:11] for x in d]
        t = int(d[-1][0]) + 3600_000
        time.sleep(0.12)
    if not rows:
        return "нет данных"
    f = pd.DataFrame(rows, columns=COLS).astype(float).drop_duplicates("ms").sort_values("ms")
    f = f[f["ms"] + 3600_000 <= END].drop(columns=["close_ms"])
    f.to_csv(p, index=False)
    return f"{len(f)} баров {pd.Timestamp(f['ms'].iloc[0], unit='ms'):%Y-%m-%d} – {pd.Timestamp(f['ms'].iloc[-1], unit='ms'):%Y-%m-%d %H:%M}"


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
        time.sleep(0.12)
    pd.DataFrame(rows, columns=["ms", "rate"]).astype(float).drop_duplicates("ms").sort_values("ms").to_csv(p, index=False)


def main():
    for c in universe():
        sym = c + "USDT"
        try:
            msg = klines(sym)
            if c in TOP and msg != "нет данных":
                funding(sym)
        except urllib.error.HTTPError as e:
            msg = f"ошибка {e.code}"
        print(sym, msg, flush=True)


if __name__ == "__main__":
    main()
