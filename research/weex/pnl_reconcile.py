"""Сверка прибыли сетки по сделкам биржи (только чтение): деньги по исполнениям ордеров сетки
(b7g…) + остаток позиции по текущей цене против учёта бота (закрыто + мешок) по каждой стороне."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.weex_api.client import WeexClient  # noqa: E402
from services.weex_grid import engine as eg  # noqa: E402

c = WeexClient()
c.sync_time()
bid, ask = c.book("BTCUSDT")
mid = (bid + ask) / 2
trades = c.user_trades("BTCUSDT")
cid_of = {}
for t in trades:
    oid = str(t["orderId"])
    if oid not in cid_of:
        cid_of[oid] = str(c.order_info(oid).get("clientOrderId", ""))
grid = [t for t in trades if cid_of[str(t["orderId"])].startswith(eg.PREFIX)]
manual = [t for t in trades if not cid_of[str(t["orderId"])].startswith(eg.PREFIX)]
print(f"цена {mid:,.1f}; сделок в выгрузке {len(trades)}: сетки {len(grid)}, ручных {len(manual)}")
for t in manual:
    print("  ручная:", t["side"], t["positionSide"], t["price"], t["qty"])

st = json.loads(eg.STATE.read_text())
for side, d in (("LONG", 1), ("SHORT", -1)):
    ts = [t for t in grid if t["positionSide"] == side]
    cash = sum((1 if t["side"] == "SELL" else -1) * float(t["price"]) * float(t["qty"]) for t in ts)
    net = sum((1 if t["side"] == "BUY" else -1) * float(t["qty"]) for t in ts)
    fee = sum(float(t["commission"]) for t in ts)
    exch = cash + net * mid
    s = st[side]
    bag = sum(d * float(l["qty"]) * (mid - l["entry"]) for l in s["lots"])
    held = sum(float(l["qty"]) for l in s["lots"])
    print(f"{side}: биржа — сделок {len(ts)}, остаток {abs(net):.4f}, прибыль до комиссий ${exch:+.4f}, комиссии ${fee:.4f}")
    print(f"{side}: бот   — остаток {held:.4f}, закрыто ${s['realized']:+.4f} + мешок ${bag:+.4f} = ${s['realized'] + bag:+.4f}, "
          f"комиссии ${s['fees']:.4f}  | расхождение ${s['realized'] + bag - exch:+.4f}")
