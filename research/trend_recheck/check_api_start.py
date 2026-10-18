"""Справка: первая минута 1m UM по REST (/fapi/v1/klines, startTime=0) против первого месячного архива.
Только печать; в данные протокола не идёт (источник P1 по протоколу — месячные архивы с .CHECKSUM).

    .venv/bin/python3 -I research/trend_recheck/check_api_start.py
"""
import json
import urllib.request
from datetime import datetime, timezone

for sym in ("ETHUSDT", "XRPUSDT", "BTCUSDT"):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=1m&limit=1&startTime=0"
    raw = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bot7"}),
                                            timeout=30).read())
    t = int(raw[0][0])
    print(sym, t, datetime.fromtimestamp(t / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
