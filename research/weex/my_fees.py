"""Только чтение: ставки комиссии аккаунта WEEX по API (мейкер/тейкер) для BTC, ETH, золота."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.weex_api.client import WeexClient  # noqa: E402

c = WeexClient()
c.sync_time()
for sym in ("BTCUSDT", "ETHUSDT", "XAUUSDT"):
    try:
        print(sym, json.dumps(c.futures_commission(sym), ensure_ascii=False))
    except Exception as exc:                                   # noqa: BLE001
        print(sym, "ошибка:", exc)
