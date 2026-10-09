"""Параметры контрактов WEEX (публичный exchangeInfo): мин. объём, шаг цены/объёма, комиссии."""
import json
import sys
import urllib.request

WANT = sys.argv[1:] or ["BTCUSDT", "ETHUSDT", "XAUUSDT", "XAUTUSDT", "PAXGUSDT"]
data = json.loads(urllib.request.urlopen("https://api-contract.weex.com/capi/v3/market/exchangeInfo", timeout=30).read())
syms = data.get("symbols", data if isinstance(data, list) else [])
for s in syms:
    if s.get("symbol") in WANT:
        short = {k: v for k, v in s.items() if not isinstance(v, (list, dict))}
        filt = s.get("filters") or []
        print(s["symbol"], json.dumps(short, ensure_ascii=False))
        for f in filt:
            print("   ", json.dumps(f, ensure_ascii=False))
