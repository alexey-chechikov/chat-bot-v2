"""Минутки Binance USDⓈ-M (перпетуал) с объёмом покупателя-агрессора — дельта по свече без архивов сделок.

Поле taker buy base volume (k[9]) классифицирует биржа: дельта бара = 2 × taker_buy − volume — это агрессорная дельта
биржи (не оценка по направлению младших свечей, как Volume Delta TradingView). Только закрытые минуты
(close_time < начало текущей минуты − 5 с). ТЗ docs/ATLAS_TRADINGVIEW_DATA_RESEARCH_SPEC_2026-10-13.md §6–8.
Выход: backtests/frozen/<SYM>_UM_1m.csv (в .gitignore): ts,open,high,low,close,volume,taker_buy,trades

    .venv/bin/python3 research/atlas_data/fetch_binance_um_1m.py BTCUSDT [2024-05-15]
"""
import csv
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def get(url: str):
    for k in range(6):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bot7"}),
                                                     timeout=30).read())
        except Exception:                                   # noqa: BLE001
            if k == 5:
                raise
            time.sleep(2 ** k)


def main() -> None:
    sym = sys.argv[1]
    start = sys.argv[2] if len(sys.argv) > 2 else "2024-05-15"
    a = int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp() * 1000)
    end = int(time.time() // 60 * 60 * 1000) - 5_000
    out = ROOT / "backtests" / "frozen" / f"{sym}_UM_1m.csv"
    rows = {}
    while a < end:
        raw = get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=1m&limit=1500&startTime={a}"
                  f"&endTime={end}")
        if not raw:
            break
        for r in raw:
            if int(r[6]) < end:
                rows[int(r[0])] = [int(r[0]), r[1], r[2], r[3], r[4], r[5], r[9], r[8]]
        a = int(raw[-1][0]) + 60_000
        time.sleep(0.3)
    tmp = out.with_suffix(".part")
    with tmp.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "open", "high", "low", "close", "volume", "taker_buy", "trades"])
        for t in sorted(rows):
            w.writerow(rows[t])
    tmp.replace(out)
    print(out, len(rows), "минут")


if __name__ == "__main__":
    main()
