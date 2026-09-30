"""Длинная история свечей BTC/ETH для карточки шансов: дневные и часовые.

867 дней из market_1m дают в «истощённой» зоне (>20% над SMA100) два-три
независимых эпизода — слишком мало. Binance отдаёт свечи USDT-пар с августа
2017 публично, без ключа; зеркало data-api.binance.vision не режется по гео.
Сохраняем в data/historical/ (daily_<SYMBOL>.csv для дневных,
<interval>_<SYMBOL>.csv для остальных), дописываем только новое.

    .venv/bin/python3 tools/fetch_daily_history.py            # дневные
    .venv/bin/python3 tools/fetch_daily_history.py 1h         # часовые
"""
from __future__ import annotations

import csv
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "historical"
HOSTS = ("https://data-api.binance.vision", "https://api.binance.com")
START_MS = 1502928000000          # 2017-08-17
STEP_MS = {"1d": 86_400_000, "4h": 14_400_000, "1h": 3_600_000}


def _get(url: str) -> list:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def path_for(symbol: str, interval: str = "1d") -> Path:
    name = f"daily_{symbol}.csv" if interval == "1d" else f"{interval}_{symbol}.csv"
    return OUT / name


def fetch(symbol: str, interval: str = "1d") -> Path:
    step = STEP_MS[interval]
    path = path_for(symbol, interval)
    rows: dict[int, list] = {}
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for rec in csv.DictReader(f):
                rows[int(rec["ts_ms"])] = [rec["open"], rec["high"], rec["low"],
                                           rec["close"], rec["volume"]]
    start = max(rows) + step if rows else START_MS
    now_ms = int(time.time() * 1000)
    host_err = None
    while start < now_ms - step:
        batch = None
        for host in HOSTS:
            try:
                batch = _get(f"{host}/api/v3/klines?symbol={symbol}"
                             f"&interval={interval}&startTime={start}&limit=1000")
                break
            except Exception as exc:                      # noqa: BLE001
                host_err = exc
        if batch is None:
            raise RuntimeError(f"{symbol} {interval}: все хосты недоступны: {host_err}")
        if not batch:
            break
        for k in batch:
            if int(k[6]) < now_ms:                        # только закрытые свечи
                rows[int(k[0])] = [k[1], k[2], k[3], k[4], k[5]]
        start = int(batch[-1][0]) + step
        time.sleep(0.15)
    OUT.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts_ms", "open", "high", "low", "close", "volume"])
        for ts in sorted(rows):
            w.writerow([ts, *rows[ts]])
    return path


if __name__ == "__main__":
    args = sys.argv[1:]
    interval = "1d"
    if args and args[0] in STEP_MS:
        interval, args = args[0], args[1:]
    for sym in (args or ["BTCUSDT", "ETHUSDT"]):
        p = fetch(sym, interval)
        n = sum(1 for _ in p.open(encoding="utf-8")) - 1
        print(f"{sym} {interval}: {n} свечей → {p}")
