"""Минутки Binance spot за 2 года в формате backtests/frozen/<SYM>_1m_2y.csv (ts,open,high,low,close,volume) —
для монет, которых там нет (11.10: PAXG как длинная история золота; XAUUSDT-фьючерс только с 11.12.2025).
Только закрытые минуты (endTime = начало текущей минуты). Запуск: fetch_frozen_1m.py PAXGUSDT [2024-05-15]"""
import csv
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SYM = sys.argv[1]
START = sys.argv[2] if len(sys.argv) > 2 else "2024-05-15"
OUT = ROOT / "backtests" / "frozen" / f"{SYM}_1m_2y.csv"


def main():
    a = int(datetime.fromisoformat(START).replace(tzinfo=timezone.utc).timestamp() * 1000)
    end = int(time.time() // 60 * 60 * 1000)                 # начало текущей (незакрытой) минуты
    tmp = OUT.with_suffix(".part")
    n = 0
    with tmp.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "open", "high", "low", "close", "volume"])
        while a < end:
            url = (f"https://api.binance.com/api/v3/klines?symbol={SYM}&interval=1m&limit=1000&startTime={a}"
                   f"&endTime={end - 1}")
            for k in range(5):
                try:
                    rows = json.loads(urllib.request.urlopen(url, timeout=30).read())
                    break
                except Exception:                           # noqa: BLE001
                    time.sleep(2 + 3 * k)
            else:
                raise RuntimeError(f"не скачалось {a}")
            if not rows:
                break
            for r in rows:
                w.writerow([r[0], *(float(x) for x in r[1:6])])
            n += len(rows)
            a = rows[-1][0] + 60_000
            time.sleep(0.12)
    tmp.replace(OUT)
    print(SYM, n, "минут →", OUT)


if __name__ == "__main__":
    main()
