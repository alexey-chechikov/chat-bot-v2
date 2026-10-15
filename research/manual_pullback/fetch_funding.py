"""История фандинга Binance USDⓈ-M (публичный /fapi/v1/fundingRate, без ключей) для протокола
docs/PULLBACK_4H_PROTOCOL_2026-10-15.md: время начисления, ставка, markPrice.

    .venv/bin/python3 research/manual_pullback/fetch_funding.py ETHUSDT [2024-05-01]

Выход: backtests/frozen/<SYM>_funding.csv (в .gitignore): fundingTime,fundingRate,markPrice
(markPrice пустой, если биржа его не вернула). Печатает число строк, интервалы и sha256.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/Users/alexeychechikov/code/bot7")
URL = "https://fapi.binance.com/fapi/v1/fundingRate?symbol={s}&limit=1000&startTime={a}&endTime={b}"


def get(url: str):
    for k in range(6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "bot7"})
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except Exception:                                   # noqa: BLE001
            if k == 5:
                raise
            time.sleep(2 ** k)


def fetch(sym: str, start: int, end: int) -> dict[int, tuple[str, str]]:
    rows: dict[int, tuple[str, str]] = {}
    a = start
    while a < end:
        raw = get(URL.format(s=sym, a=a, b=end))
        if not raw:
            break
        for r in raw:
            rows[int(r["fundingTime"])] = (str(r["fundingRate"]), str(r.get("markPrice") or ""))
        nxt = int(raw[-1]["fundingTime"]) + 1
        if nxt <= a or len(raw) < 1000:
            break
        a = nxt
        time.sleep(0.3)
    return rows


def main() -> None:
    sym = sys.argv[1]
    start = sys.argv[2] if len(sys.argv) > 2 else "2024-05-01"
    a = int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp() * 1000)
    end = int(time.time() * 1000)
    rows = fetch(sym, a, end)
    out = ROOT / "backtests" / "frozen" / f"{sym}_funding.csv"
    tmp = out.with_suffix(".part")
    with tmp.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["fundingTime", "fundingRate", "markPrice"])
        for t in sorted(rows):
            w.writerow([t, *rows[t]])
    tmp.replace(out)
    ts = sorted(rows)
    gaps = Counter(round((y - x) / 3_600_000, 2) for x, y in zip(ts, ts[1:]))
    miss = sum(1 for t in ts if not rows[t][1])
    print(out, len(rows), "начислений", "интервалы ч", dict(gaps), "без mark", miss,
          "sha256", hashlib.sha256(out.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
