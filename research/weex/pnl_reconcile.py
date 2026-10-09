"""Сверка прибыли сетки по сделкам биржи (только чтение).

ВСЕ сделки символа с момента запуска сетки (окна по времени, окно с 100 сделками делится пополам —
не только последние 100), разделение на сетку (clientOrderId b7g…) и ручные; по каждой стороне:
деньги по исполнениям + остаток по текущей цене против учёта бота, отдельно ДО и ПОСЛЕ комиссий.
Не сверяет фандинг и полный капитал счёта (там ручные позиции) — это отдельная задача."""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.weex_api.client import WeexClient  # noqa: E402
from services.weex_grid import engine as eg  # noqa: E402

c = WeexClient()
c.sync_time()
bid, ask = c.book("BTCUSDT")
mid = (bid + ask) / 2
first = json.loads(eg.JOURNAL.read_text(encoding="utf-8").splitlines()[0])["ts"]
start = int((datetime.fromisoformat(first).timestamp() - 3600) * 1000)
end = int(time.time() * 1000) + 60_000


def fetch(a: int, b: int) -> list[dict]:
    rows = c.user_trades("BTCUSDT", start_ms=a, end_ms=b) or []
    if len(rows) >= 100 and b - a > 60_000:           # окно переполнено — делим пополам
        m = (a + b) // 2
        return fetch(a, m) + fetch(m + 1, b)
    return rows


trades, a = [], start
while a < end:
    b = min(a + 6 * 86_400_000, end)
    trades += fetch(a, b)
    a = b + 1
trades = list({str(t["id"]): t for t in trades}.values())
cid_of = {}
for t in trades:
    oid = str(t["orderId"])
    if oid not in cid_of:
        cid_of[oid] = str(c.order_info(oid).get("clientOrderId", ""))
grid = [t for t in trades if cid_of[str(t["orderId"])].startswith(eg.PREFIX)]
manual = [t for t in trades if not cid_of[str(t["orderId"])].startswith(eg.PREFIX)]
print(f"цена {mid:,.1f}; сделок с {first[:16]}: {len(trades)} (сетки {len(grid)}, ручных {len(manual)})")
for t in manual:
    print("  ручная:", t["side"], t["positionSide"], t["price"], t["qty"])

st = json.loads(eg.STATE.read_text())
ok = True
for side, d in (("LONG", 1), ("SHORT", -1)):
    ts = [t for t in grid if t["positionSide"] == side]
    cash = sum((1 if t["side"] == "SELL" else -1) * float(t["price"]) * float(t["qty"]) for t in ts)
    net = sum((1 if t["side"] == "BUY" else -1) * float(t["qty"]) for t in ts)
    fee = sum(float(t["commission"]) for t in ts)
    exch = cash + net * mid
    s = st[side]
    bag = sum(d * float(l["qty"]) * (mid - l["entry"]) for l in s["lots"])
    held = sum(float(l["qty"]) for l in s["lots"])
    bot = s["realized"] + bag
    diff, fdiff, qdiff = bot - exch, s["fees"] - fee, held - abs(net)
    ok &= abs(diff) < 0.01 and abs(fdiff) < 0.01 and abs(qdiff) < 1e-9
    print(f"{side}: биржа — сделок {len(ts)}, остаток {abs(net):.4f}, до комиссий ${exch:+.4f}, комиссии ${fee:.4f}, "
          f"после ${exch - fee:+.4f}")
    print(f"{side}: бот   — остаток {held:.4f}, закрыто ${s['realized']:+.4f} + мешок ${bag:+.4f} = ${bot:+.4f}, "
          f"комиссии ${s['fees']:.4f}, после ${bot - s['fees']:+.4f}")
    print(f"{side}: расхождение — деньги ${diff:+.4f}, комиссии ${fdiff:+.4f}, объём {qdiff:+.4f}")
print("ИТОГ:", "совпадает (деньги и комиссии ±$0.01, объём точно)" if ok else "ЕСТЬ РАСХОЖДЕНИЕ")
