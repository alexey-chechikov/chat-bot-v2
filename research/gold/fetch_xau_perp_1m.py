"""Минутки Binance USDⓈ-M XAUUSDT (TRADIFI_PERPETUAL, листинг 11.12.2025) с объёмом и объёмом покупателя-агрессора —
для проверки золота по ТЗ docs/GOLD_LIQUIDITY_SWEEP_SPEC_2026-10-13.md. Только закрытые минуты (close_time < начало
текущей минуты − 5 с). Выход: backtests/frozen/XAUUSDT_PERP_1m.csv (в .gitignore):
ts,open,high,low,close,volume,taker_buy

    .venv/bin/python3 research/gold/fetch_xau_perp_1m.py
"""
import csv
import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "backtests" / "frozen" / "XAUUSDT_PERP_1m.csv"
START = 1765440300000                       # onboardDate из exchangeInfo


def main() -> None:
    end = int(time.time() // 60 * 60 * 1000) - 5_000
    rows, a = {}, START
    while a < end:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol=XAUUSDT&interval=1m&limit=1500&startTime={a}&endTime={end}"
        for k in range(6):
            try:
                raw = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bot7"}),
                                                        timeout=30).read())
                break
            except Exception:                               # noqa: BLE001
                if k == 5:
                    raise
                time.sleep(2 ** k)
        if not raw:
            break
        for r in raw:
            if int(r[6]) < end:
                rows[int(r[0])] = [int(r[0]), r[1], r[2], r[3], r[4], r[5], r[9]]
        a = int(raw[-1][0]) + 60_000
        time.sleep(0.25)
    tmp = OUT.with_suffix(".part")
    with tmp.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "open", "high", "low", "close", "volume", "taker_buy"])
        for t in sorted(rows):
            w.writerow(rows[t])
    tmp.replace(OUT)
    print(OUT, len(rows), "минут")


if __name__ == "__main__":
    main()
