"""Сверка живой сетки с биржей (только чтение): ордера сетки, позиции, сделки с комиссией, начисления."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.weex_api.client import FUTURES, WeexClient  # noqa: E402

c = WeexClient()
c.sync_time()
bid, ask = c.book("BTCUSDT")
print("цена", bid, ask)
oo = c.open_orders("BTCUSDT")
mine = [o for o in oo if str(o.get("clientOrderId", "")).startswith("b7g")]
print(f"открытых ордеров всего {len(oo)}, из них сетки {len(mine)}:")
for o in mine:
    print("  ", o["positionSide"], o["side"], o["price"], o["origQty"], "reduceOnly" if o["reduceOnly"] else "вход")
pos = c.futures_positions()
for p in pos:
    print("позиция", p["symbol"], p["side"], p["size"], "вход", p.get("openValue"), "мешок", p.get("unrealizePnl"),
          "комиссии открытия", p.get("cumOpenFee"))
trades = c.user_trades("BTCUSDT")
for t in trades[:10]:
    print("сделка", t["side"], t["positionSide"], t["price"], t["qty"], "комиссия", t["commission"],
          "мейкер" if t["maker"] else "тейкер", f"= {float(t['commission']) / float(t['quoteQty']) * 100:.4f}%")
try:
    inc = c.post(FUTURES, "/capi/v3/account/income", {"limit": 30})
    for it in inc.get("items", [])[:30]:
        print("начисление", it["incomeType"], it["income"], "комиссия", it.get("fillFee"), it.get("transferReason"))
except Exception as e:                      # начисления не обязательны для сверки
    print("начисления недоступны:", e)
bal = c.futures_balance()
print("баланс", json.dumps(bal))

st = json.loads((Path(__file__).resolve().parents[2] / "state" / "weex_grid_state.json").read_text())
by_id = {str(o["orderId"]): o for o in mine}
for side in ("LONG", "SHORT"):
    s = st.get(side, {})
    lots = s.get("lots", [])
    qty = sum(float(l["qty"]) for l in lots)
    no_tp = [l["entry"] for l in lots if not l.get("tp_order") or str(l["tp_order"]["id"]) not in by_id]
    ent = s.get("entry")
    ent_q = by_id.get(str(ent["id"]), {}).get("origQty") if ent else None
    print(f"учёт {side}: лотов {len(lots)} = {qty:.4f} BTC, без тейка на бирже {no_tp}, вход {ent and ent['price']} объём {ent_q}")
