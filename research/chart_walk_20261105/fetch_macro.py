"""Дневные S&P 500, золото и индекс доллара → backtests/frozen/ext_<имя>_d.csv (в .gitignore).
Источник — Yahoo Finance chart API (Stooq 09.11 не отвечал). Только числа: дата и закрытие проверяются.
Запуск: python fetch_macro.py"""
from __future__ import annotations

import csv
import hashlib
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT = Path("/Users/alexeychechikov/code/bot7/backtests/frozen")
SYMS = {"spx": "^GSPC", "xau": "GC=F", "dxy": "DX-Y.NYB", "ndx": "^NDX"}
START = int(datetime(2013, 1, 1, tzinfo=timezone.utc).timestamp())


def fetch(sym: str) -> list[tuple[str, float]]:
    q = urllib.parse.quote(sym)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{q}?period1={START}&period2={int(time.time())}&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (bot7-research)"})
    js = json.loads(urllib.request.urlopen(req, timeout=40).read().decode())
    r = js["chart"]["result"][0]
    ts, cl = r["timestamp"], r["indicators"]["quote"][0]["close"]
    off = int(r["meta"].get("gmtoffset", 0))
    rows = {}
    for t, c in zip(ts, cl):
        if c is None or not isinstance(c, (int, float)) or c <= 0:
            continue
        d = datetime.fromtimestamp(int(t) + off, timezone.utc).strftime("%Y-%m-%d")
        rows[d] = float(c)
    return sorted(rows.items())


def main():
    for name, sym in SYMS.items():
        try:
            rows = fetch(sym)
        except Exception as exc:  # noqa: BLE001
            print(f"{name} ({sym}): ошибка {exc!r}")
            continue
        if len(rows) < 100:
            print(f"{name} ({sym}): мало строк ({len(rows)}) — не сохраняю")
            continue
        p = OUT / f"ext_{name}_d.csv"
        with p.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["date", "close"])
            w.writerows(rows)
        h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        print(f"{name} ({sym}): {len(rows)} дней {rows[0][0]} … {rows[-1][0]}, sha256 {h}")


if __name__ == "__main__":
    main()
