"""Какой ETH-бот GinArea работал последним и с какими параметрами (по снимкам трекера, без логина)."""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
csv.field_size_limit(sys.maxsize)

eth = {}
for row in csv.DictReader(l.replace("\0", "") for l in (ROOT / "ginarea_live" / "params.csv").open(encoding="utf-8", errors="replace")):
    if "ETH" in row["bot_name"].upper():
        eth[row["bot_id"]] = row                    # последняя запись параметров каждого бота

status_hist = defaultdict(list)                     # bot_id -> [(ts, status, position, profit, volume)]
with (ROOT / "ginarea_live" / "snapshots.csv").open(encoding="utf-8", errors="replace") as f:
    for row in csv.DictReader(l.replace("\0", "") for l in f):
        if row["bot_id"] in eth or "ETH" in row["bot_name"].upper():
            h = status_hist[row["bot_id"]]
            st = row["status"]
            if not h or h[-1][1] != st:
                h.append((row["ts_utc"], st, row["position"], row["profit"], row["trade_volume"], row["bot_name"]))
            else:
                h[-1] = h[-1][:2] + (row["position"], row["profit"], row["trade_volume"], row["bot_name"])

for bid, h in status_hist.items():
    print(f"\n=== {bid} {h[-1][5]}")
    for ts, st, pos, prof, vol, _ in h[-8:]:
        print(f"  с {ts} статус {st} позиция {pos} прибыль {prof} оборот {vol}")
    if bid in eth:
        r = eth[bid]
        print("  параметры на", r["ts_utc"], ":", json.dumps(json.loads(r["raw_params_json"]), ensure_ascii=False))
