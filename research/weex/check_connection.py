"""Проверка связи с WEEX: баланс, позиции, комиссия, права ключа. Ключи не печатаются."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.weex_api.client import WeexClient, WeexError  # noqa: E402

c = WeexClient()
print("сдвиг времени к серверу, мс:", c.sync_time())
for name, fn in (("фьючерсы: баланс", c.futures_balance), ("фьючерсы: позиции", c.futures_positions),
                 ("фьючерсы: комиссия BTCUSDT", c.futures_commission)):
    try:
        print(name, "→", fn())
    except WeexError as e:
        print(name, "→ ОШИБКА", e)
try:
    s = c.spot_account()
    bal = [b for b in s.get("balances", []) if float(b.get("free", 0)) + float(b.get("locked", 0)) > 0]
    print("спот: права ключа", s.get("permissions"), "| canTrade", s.get("canTrade"),
          "| canWithdraw", s.get("canWithdraw"), "| ненулевые балансы", bal)
except WeexError as e:
    print("спот → ОШИБКА", e)
