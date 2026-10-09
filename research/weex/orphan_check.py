"""Только чтение: свои (b7g) ордера на бирже, о которых не знает живой учёт сетки (их новый код снимет)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.weex_api.client import WeexClient  # noqa: E402
from services.weex_grid import engine as eg  # noqa: E402

c = WeexClient()
c.sync_time()
for name in eg.GRIDS:
    cfg_path, st_path, _ = eg.grid_files(name)
    if not st_path.exists():
        print(name, "живого учёта нет")
        continue
    st = json.loads(st_path.read_text())
    sym = json.loads(cfg_path.read_text()).get("symbol", "BTCUSDT")
    known = set()
    for s in ("LONG", "SHORT"):
        if st.get(s, {}).get("entry"):
            known.add(st[s]["entry"]["id"])
        known.update(l["tp_order"]["id"] for l in st.get(s, {}).get("lots", []) if l.get("tp_order"))
    mine = [o for o in c.open_orders(sym) if str(o.get("clientOrderId", "")).startswith(eg.PREFIX)]
    orphans = [o for o in mine if str(o["orderId"]) not in known]
    print(f"{name} {sym}: своих ордеров {len(mine)}, в учёте {len(known)}, сирот {len(orphans)}")
    for o in orphans:
        print("   сирота:", o["positionSide"], o["side"], o["price"], o["origQty"], o.get("clientOrderId"))
    for o in mine:
        print("   ", o["positionSide"], o["side"], o["price"], o["origQty"], "исп", o.get("executedQty"),
              "reduce" if o.get("reduceOnly") else "вход")
