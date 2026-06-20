"""Compact bot stats — one line per bot."""
import os
import sys

ROOT = "/Users/alexeychechikov/code/bot7"
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from services.short_bots_guard.control import _build_api  # noqa: E402

api, err = _build_api()
if api is None:
    print(f"FAIL: {err}")
    sys.exit(1)

# status code → label
STATUS = {0: "off", 2: "act", 12: "stop"}

bots = api.list_bots()
print(f"{'id':<11} {'st':<4} {'pos':>10} {'profit':>10} {'curP':>10} {'fills':>6} {'bal':>10}  name")
print("-" * 90)
for b in bots:
    bid = getattr(b, "id", "?")
    st = getattr(b, "status", "?")
    st_lbl = STATUS.get(st, str(st))
    name = (getattr(b, "name", "") or "").strip()
    try:
        s = api.get_stat(int(bid))
        pos = float(getattr(s, "position", 0))
        profit = float(getattr(s, "profit", 0))
        cur = float(getattr(s, "currentProfit", 0))
        fills = int(getattr(s, "inFilledCount", 0))
        bal = float(getattr(s, "balance", 0))
        print(f"{bid:<11} {st_lbl:<4} {pos:>10.4f} {profit:>10.2f} {cur:>10.2f} {fills:>6} {bal:>10.1f}  {name}")
    except Exception as e:  # noqa: BLE001
        print(f"{bid:<11} {st_lbl:<4}  err {e!r}")
