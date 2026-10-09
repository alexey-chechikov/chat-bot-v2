"""Сверка быстрого прогона (fast_grid) с настоящим движком сетки (services/weex_grid) на одних
минутках BTC за последние N суток. Должны совпасть тейки/оборот/итог в пределах нескольких %."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import fast_grid as fg  # noqa: E402
import refill_compare as rc  # noqa: E402
from services.weex_grid import engine as eg  # noqa: E402

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 21
ts, o, h, l, c = fg.load("BTCUSDT")
n = DAYS * 1440
ts, o, h, l, c = ts[-n:], o[-n:], h[-n:], l[-n:], c[-n:]
ks = [[int(t) * 1000, str(a), str(b), str(x), str(y)] for t, a, b, x, y in zip(ts, o, h, l, c)]
cfg = {**eg.load_config(), "enabled": True, "dry_run": True, "order_qty": "0.0012", "max_notional_usd": 4000.0,
       "max_lots_per_side": 50, "step_pct": 0.2, "target_pct": 0.21}
eng = rc.run(eg.Grid, ks, cfg)
fast = fg.run((ts, o, h, l, c), ("LONG", "SHORT"), 0.2, 0.21, order_qty=0.0012, cap_usd=4000.0,
              max_orders=50)                    # объём фиксирован в BTC — как у движка (10.10, замечание GPT)
print(f"{DAYS} сут BTC {c[0]:,.0f} → {c[-1]:,.0f}")
for k in ("тейков", "оборот", "закрыто", "комиссии", "мешок", "итог", "худший мешок"):
    a, b = eng[k], fast[k]
    print(f"{k:>13}: движок {a:>10,.2f}  быстрый {b:>10,.2f}  ({(b / a - 1) * 100 if a else 0:+.1f}%)")
