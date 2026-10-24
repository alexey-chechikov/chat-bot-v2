"""Дописать фандинг Binance USDT-M в backtests/frozen/<SYM>_funding_full.csv (24.10: файлы кончались 14.10 — бэктесты
после этой даты шли без фандинга). Только новые расчёты после последнего в файле; формат и CRLF — как в файле
(fundingTime,fundingRate,markPrice). Копия файла до записи — рядом, .bak_<дата>.
Запуск: fetch_funding.py [BTCUSDT ETHUSDT XRPUSDT]
"""
from __future__ import annotations

import json
import shutil
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DIR = Path("/Users/alexeychechikov/code/bot7/backtests/frozen")
SYMS = [a for a in sys.argv[1:] if a.endswith("USDT")] or ["BTCUSDT", "ETHUSDT", "XRPUSDT"]


def last_time(path: Path) -> int:
    with path.open("rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 4096))
        rows = [r for r in f.read().decode().splitlines() if r and r[0].isdigit()]
    return int(rows[-1].split(",")[0])


def main():
    for sym in SYMS:
        path = DIR / f"{sym}_funding_full.csv"
        t = last_time(path) + 1
        new = []
        while True:
            url = f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={sym}&startTime={t}&limit=1000"
            rows = json.load(urllib.request.urlopen(url, timeout=20))
            if not rows:
                break
            new += rows
            t = int(rows[-1]["fundingTime"]) + 1
            if len(rows) < 1000:
                break
            time.sleep(0.5)
        if not new:
            print(f"{sym}: новых расчётов нет")
            continue
        shutil.copy(path, path.with_name(path.name + f".bak_{datetime.now(timezone.utc):%Y%m%d}"))
        with path.open("ab") as f:
            for r in new:
                f.write(f"{r['fundingTime']},{r['fundingRate']},{r.get('markPrice') or ''}\r\n".encode())
        a = datetime.fromtimestamp(int(new[0]["fundingTime"]) / 1000, timezone.utc)
        b = datetime.fromtimestamp(int(new[-1]["fundingTime"]) / 1000, timezone.utc)
        print(f"{sym}: дописано {len(new)} расчётов {a:%d.%m %H:%M} … {b:%d.%m %H:%M} UTC")


if __name__ == "__main__":
    main()
