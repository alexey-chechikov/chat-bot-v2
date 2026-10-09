"""Публичные параметры контрактов WEEX: минимальный объём, шаг цены/объёма (без ключей)."""
import json
import urllib.request

url = "https://api-contract.weex.com/capi/v3/market/exchangeInfo"
data = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bot7"}), timeout=20))
syms = data.get("symbols", data) if isinstance(data, dict) else data
for s in syms:
    if s.get("symbol") in ("BTCUSDT", "ETHUSDT"):
        print(json.dumps(s, ensure_ascii=False)[:1500])
