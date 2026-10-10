"""Проверка выхода GinArea на секундах: тянущийся стоп 0.02% на минутной модели (4 точки в минуту)
может быть переоценён — внутри минуты цена дёргается сильнее. Одни и те же последние N суток BTC:
секундные свечи Binance (spot, interval=1s) против минутных, лимитка на цели против стопа GinArea."""
import json
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fast_grid as fg  # noqa: E402

DAYS = float(sys.argv[1]) if len(sys.argv) > 1 else 3
CACHE = Path(__file__).with_name("data") / f"BTCUSDT_1s_{DAYS:g}d.csv"


def fetch(interval: str, step_ms: int) -> tuple:
    end = int(time.time() * 1000) // 60000 * 60000
    start = end - int(DAYS * 86_400_000)
    rows = []
    while start < end:
        url = (f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval={interval}&limit=1000"
               f"&startTime={start}&endTime={end - 1}")
        for k in range(5):
            try:
                chunk = json.loads(urllib.request.urlopen(url, timeout=30).read())
                break
            except Exception:                               # noqa: BLE001
                time.sleep(2 + 3 * k)
        else:
            raise RuntimeError("не скачалось")
        if not chunk:
            break
        rows += chunk
        start = chunk[-1][0] + step_ms
        time.sleep(0.05)
    a = np.array([[r[0] // 1000, float(r[1]), float(r[2]), float(r[3]), float(r[4])] for r in rows])
    return a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4]


if CACHE.exists():
    a = np.loadtxt(CACHE, delimiter=",")
    s1 = (a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4])
else:
    s1 = fetch("1s", 1000)
    np.savetxt(CACHE, np.column_stack(s1), delimiter=",", fmt="%.2f")
m1 = fetch("1m", 60_000)
print(f"BTC последние {DAYS:g} сут: секунд {len(s1[0]):,}, минут {len(m1[0]):,}; {m1[4][0]:,.0f} → {m1[4][-1]:,.0f}")
kw = dict(sides=("LONG", "SHORT"), step=0.2, target=0.21, order_qty=0.0012, cap_usd=4000.0, max_orders=50)
for name, extra in (("лимитка на цели", dict(exit_mode="limit")),
                    ("GinArea 0.006/0.02%", dict(exit_mode="trail", min_stop=0.006, max_stop=0.02, exit_fee=0.00048)),
                    ("GinArea 0.01/0.1%", dict(exit_mode="trail", min_stop=0.01, max_stop=0.1, exit_fee=0.00048))):
    out = []
    for label, data in (("минуты", m1), ("секунды", s1)):
        r = fg.run(data, **kw, **extra)
        per = r["закрыто"] / r["тейков"] if r["тейков"] else 0
        out.append(f"{label}: итог ${r['итог']:+.2f}, закрыто ${r['закрыто']:.2f}, на лот ${per:.4f}, лотов {r['тейков']}")
    print(f"{name:<22} | " + " | ".join(out))
