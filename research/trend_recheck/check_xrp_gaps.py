"""Справка: есть ли минуты XRPUSDT в дырах месячных архивов (2022-02-26…28, 2022-04-01…02) у REST /fapi/v1/klines
и в дневных архивах data.binance.vision. Только печать — дыры в <SYM>_UM_1m_early.csv НЕ заполняются (протокол §1).

    .venv/bin/python3 -I research/trend_recheck/check_xrp_gaps.py
"""
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone

DAYS = ("2022-02-26", "2022-02-27", "2022-02-28", "2022-04-01", "2022-04-02")


def get(url):
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bot7"}), timeout=60).read()
    except urllib.error.HTTPError as exc:
        return f"HTTP {exc.code}"


for d in DAYS:
    a = int(datetime.fromisoformat(d).replace(tzinfo=timezone.utc).timestamp() * 1000)
    raw = get(f"https://fapi.binance.com/fapi/v1/klines?symbol=XRPUSDT&interval=1m&limit=1500&startTime={a}"
              f"&endTime={a + 86_400_000 - 1}")
    rest = len(json.loads(raw)) if isinstance(raw, bytes) else raw
    ck = get(f"https://data.binance.vision/data/futures/um/daily/klines/XRPUSDT/1m/XRPUSDT-1m-{d}.zip.CHECKSUM")
    daily = "есть" if isinstance(ck, bytes) else ck
    print(f"{d}: REST минут {rest}; дневной архив {daily}")
