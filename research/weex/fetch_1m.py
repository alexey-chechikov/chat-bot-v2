"""Минутки Binance в research/weex/data/<SYM>_1m.csv (ts_ms,open,high,low,close) с даты START.
Золото XAUUSDT — фьючерс (fapi, с 11.12.2025), остальное — спот. Докачивает, если файл есть."""
import csv
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

START = "2025-12-11"
DATA = Path(__file__).with_name("data")
DATA.mkdir(exist_ok=True)


def fetch(sym: str) -> None:
    base = ("https://fapi.binance.com/fapi/v1/klines" if sym == "XAUUSDT"
            else "https://api.binance.com/api/v3/klines")
    path = DATA / f"{sym}_1m.csv"
    start = int(datetime.fromisoformat(START).replace(tzinfo=timezone.utc).timestamp() * 1000)
    if path.exists():
        last = path.read_text().strip().splitlines()[-1].split(",")[0]
        if last.isdigit():
            start = int(last) + 60_000
    end = int(time.time() * 1000)
    n = 0
    with path.open("a", newline="") as f:
        w = csv.writer(f)
        if path.stat().st_size == 0:
            w.writerow(["ts", "open", "high", "low", "close"])
        while start < end:
            url = f"{base}?symbol={sym}&interval=1m&limit=1000&startTime={start}"
            for attempt in range(5):
                try:
                    chunk = json.loads(urllib.request.urlopen(url, timeout=30).read())
                    break
                except Exception:                       # noqa: BLE001 — сеть: повторить
                    time.sleep(2 + attempt * 3)
            else:
                raise RuntimeError(f"не скачалось {sym} {start}")
            if not chunk:
                break
            for k in chunk:
                w.writerow([k[0], k[1], k[2], k[3], k[4]])
            n += len(chunk)
            start = chunk[-1][0] + 60_000
            time.sleep(0.15)
    print(sym, "добавлено", n, "минут →", path.name)


for s in sys.argv[1:] or ["XAUUSDT", "ETHUSDT", "BTCUSDT"]:
    fetch(s)
