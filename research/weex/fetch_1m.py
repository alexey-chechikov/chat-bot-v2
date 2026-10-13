"""Минутки Binance в research/weex/data/<SYM>_1m.csv (ts_ms,open,high,low,close) с даты START.
Золото XAUUSDT — фьючерс (fapi, с 11.12.2025), остальное — спот. Докачивает, если файл есть.

Только ЗАКРЫТЫЕ минуты (аддендум GPT 13.10, B3: прежняя версия писала минуту, ещё идущую в момент запуска, а
следующий запуск начинал с last+1 мин — обрезанный бар оставался навсегда): граница — открытие последней закрытой
минуты по ВРЕМЕНИ СЕРВЕРА (/api/v3/time, /fapi/v1/time), явный endTime в запросе, и каждый бар — close_time <
server_now. При продолжении последняя записанная минута перекачивается и перезаписывается.
Файлы, скачанные до 13.10, могут хранить обрезанный бар на стыке каждого прежнего запуска — их перекачать с нуля.

    .venv/bin/python3 research/weex/fetch_1m.py [XAUUSDT ETHUSDT BTCUSDT]
"""
import csv
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

START = "2025-12-11"
DATA = Path(__file__).with_name("data")
MIN = 60_000


def _api(sym: str) -> str:
    return "https://fapi.binance.com/fapi/v1" if sym == "XAUUSDT" else "https://api.binance.com/api/v3"


def _get(url: str):
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.loads(r.read())
        except Exception:                               # noqa: BLE001 — сеть: повторить
            time.sleep(2 + attempt * 3)
    raise RuntimeError(f"не скачалось: {url}")


def server_now(sym: str) -> int:
    """Время сервера Binance, мс — граница закрытых минут не зависит от часов мака."""
    return int(_get(f"{_api(sym)}/time")["serverTime"])


def _last_row(path: Path) -> tuple[int | None, int | None]:
    """(метка последней записанной минуты, смещение начала её строки) или (None, None)."""
    if not path.exists():
        return None, None
    data = path.read_bytes().rstrip(b"\r\n")
    cut = data.rfind(b"\n") + 1
    first = data[cut:].split(b",", 1)[0]
    return (int(first), cut) if first.isdigit() else (None, None)


def fetch(sym: str) -> None:
    DATA.mkdir(exist_ok=True)
    path = DATA / f"{sym}_1m.csv"
    start = int(datetime.fromisoformat(START).replace(tzinfo=timezone.utc).timestamp() * 1000)
    last, cut = _last_row(path)
    if last is not None:
        start = last                                    # последнюю записанную минуту — перекачать и перезаписать
    now = server_now(sym)
    end = now // MIN * MIN - MIN                         # открытие последней закрытой минуты: close_time < now
    rows: list[list] = []
    cur = start
    while cur <= end:
        chunk = _get(f"{_api(sym)}/klines?symbol={sym}&interval=1m&limit=1000&startTime={cur}&endTime={end}")
        if not chunk:
            break
        for k in chunk:
            t = int(k[0])
            if t < cur or t > end or int(k[6]) >= now:  # вне окна или ещё не закрыта — не писать
                continue
            if rows and t <= rows[-1][0]:
                continue
            rows.append([t, k[1], k[2], k[3], k[4]])
        nxt = int(chunk[-1][0]) + MIN
        if nxt <= cur:
            break
        cur = nxt
        time.sleep(0.15)
    if last is not None:
        if rows and rows[0][0] == last:                  # последняя минута перекачана — старую строку заменить
            with path.open("r+b") as f:
                f.truncate(cut)
        else:                                            # сервер её не вернул — оставить как есть
            rows = [r for r in rows if r[0] > last]
    with path.open("a", newline="") as f:
        w = csv.writer(f)
        if path.stat().st_size == 0:
            w.writerow(["ts", "open", "high", "low", "close"])
        w.writerows(rows)
    print(sym, "записано", len(rows), "закрытых минут (последняя прежняя перекачана) →", path.name,
          "по", datetime.fromtimestamp(end / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M"), "UTC")


def main(argv: list[str]) -> None:
    for s in argv or ["XAUUSDT", "ETHUSDT", "BTCUSDT"]:
        fetch(s)


if __name__ == "__main__":
    main(sys.argv[1:])
