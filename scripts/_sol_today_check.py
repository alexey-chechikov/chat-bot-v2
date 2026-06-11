"""Что было с SOL-ботами сегодня: статусы/профит вокруг 13:19 UTC."""
import csv
import sys
from pathlib import Path

csv.field_size_limit(10_000_000)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ginarea_tracker.storage import SNAPSHOTS_HEADERS

path = ROOT / "ginarea_live" / "snapshots.csv"
size = path.stat().st_size
with path.open("rb") as fh:
    fh.seek(max(0, size - 25_000_000))
    fh.readline()
    text = fh.read().decode("utf-8", errors="replace")

bots = {}
for rec in csv.reader(text.replace("\x00", "").splitlines()):
    if len(rec) != len(SNAPSHOTS_HEADERS):
        continue
    r = dict(zip(SNAPSHOTS_HEADERS, rec))
    if "SOL" not in (r["bot_name"] or "") or r["ts_utc"] < "2026-06-11":
        continue
    slot = bots.setdefault(r["bot_id"], [])
    slot.append(r)

for bid, rows in bots.items():
    print(f"── SOL bot {bid}: {len(rows)} снапшотов сегодня, имя {rows[-1]['bot_name']!r}")
    prev = None
    for r in rows:
        if prev is None or r["status"] != prev["status"]:
            print(f"   {r['ts_utc']} status={r['status']} pos={r['position']}"
                  f" profit={r['profit'][:8]} cur={r['current_profit'][:8]}")
        prev = r
    last = rows[-1]
    print(f"   ...последний: {last['ts_utc']} status={last['status']} pos={last['position']}"
          f" profit={last['profit'][:8]}")
