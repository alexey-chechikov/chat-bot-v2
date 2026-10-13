"""История фандинга Binance USDⓈ-M XAUUSDT (публичный /fapi/v1/fundingRate, без ключей) — для учёта фандинга
LONG-позиций в research/gold/sweep_backtest.py (разбор GPT 13.10, §4 п.4: интервал 8ч → 4ч с 30.01.2026 18:15 UTC).

    .venv/bin/python3 research/gold/fetch_xau_funding.py [--data-root=/Users/alexeychechikov/code/bot7] [--out=путь.csv]

Выход по умолчанию: <data-root>/backtests/frozen/XAUUSDT_PERP_funding.csv (в .gitignore):
fundingTime,fundingRate,markPrice   (markPrice пустой, если биржа его не вернула). Печатает число строк и sha256.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

DEFAULT_ROOT = "/Users/alexeychechikov/code/bot7"
START = 1765440300000                       # листинг XAUUSDT (onboardDate)
URL = "https://fapi.binance.com/fapi/v1/fundingRate?symbol=XAUUSDT&limit=1000&startTime={a}&endTime={b}"


def fetch(start: int, end: int) -> dict[int, tuple[str, str]]:
    rows: dict[int, tuple[str, str]] = {}
    a = start
    while a < end:
        for k in range(6):
            try:
                req = urllib.request.Request(URL.format(a=a, b=end), headers={"User-Agent": "bot7"})
                raw = json.loads(urllib.request.urlopen(req, timeout=30).read())
                break
            except Exception:                               # noqa: BLE001
                if k == 5:
                    raise
                time.sleep(2 ** k)
        if not raw:
            break
        for r in raw:
            rows[int(r["fundingTime"])] = (str(r["fundingRate"]), str(r.get("markPrice") or ""))
        nxt = int(raw[-1]["fundingTime"]) + 1
        if nxt <= a or len(raw) < 1000:
            break
        a = nxt
        time.sleep(0.25)
    return rows


def main() -> None:
    root = Path(next((x.split("=", 1)[1] for x in sys.argv[1:] if x.startswith("--data-root=")), DEFAULT_ROOT))
    out = Path(next((x.split("=", 1)[1] for x in sys.argv[1:] if x.startswith("--out=")),
                    root / "backtests" / "frozen" / "XAUUSDT_PERP_funding.csv"))
    end = int(time.time() * 1000)
    rows = fetch(START, end)
    tmp = out.with_suffix(".part")
    with tmp.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["fundingTime", "fundingRate", "markPrice"])
        for t in sorted(rows):
            w.writerow([t, *rows[t]])
    tmp.replace(out)
    print(out, len(rows), "начислений, sha256", hashlib.sha256(out.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
