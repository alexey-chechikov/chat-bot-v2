"""Форензика остановки WLD (5617871752): таймлайн снапшотов вокруг смены статуса,
последние события (fills, price_last) и история params (менялся ли tsl/ttp/border).
"""
import csv
import json
import sys
from pathlib import Path

csv.field_size_limit(10_000_000)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ginarea_tracker.storage import SNAPSHOTS_HEADERS, EVENTS_HEADERS, PARAMS_HEADERS

BOT = "5617871752"


def tail_rows(path, headers, bot_id, max_bytes=30_000_000):
    size = path.stat().st_size
    with path.open("rb") as fh:
        if size > max_bytes:
            fh.seek(size - max_bytes)
            fh.readline()
        text = fh.read().decode("utf-8", errors="replace")
    out = []
    for rec in csv.reader(text.replace("\x00", "").splitlines()):
        if len(rec) == len(headers) and rec[1] == bot_id:
            out.append(dict(zip(headers, rec)))
    return out

snaps = tail_rows(ROOT / "ginarea_live" / "snapshots.csv", SNAPSHOTS_HEADERS, BOT)
print(f"снапшотов WLD в хвосте: {len(snaps)}")
# найти смену статуса
prev = None
flip_i = None
for i, r in enumerate(snaps):
    if prev is not None and r["status"] != prev:
        flip_i = i
        print(f"\nСМЕНА СТАТУСА: {prev} → {r['status']} в {r['ts_utc']}")
    prev = r["status"]
if flip_i is None:
    flip_i = len(snaps) - 1
    print("смены статуса в хвосте нет; показываю конец")

lo = max(0, flip_i - 12)
hi = min(len(snaps), flip_i + 4)
print(f"\n{'ts':25}{'st':>3}{'profit':>10}{'curProfit':>11}{'bag':>9}{'pos':>9}{'avg':>9}")
for r in snaps[lo:hi]:
    p = float(r["profit"] or 0)
    c = float(r["current_profit"] or 0)
    pos = float(r["position"] or 0)
    avg = float(r["average_price"] or 0)
    print(f"{r['ts_utc']:25}{r['status']:>3}{p:>10.2f}{c:>11.2f}{c-p:>9.2f}{pos:>9.1f}{avg:>9.4f}")

events = tail_rows(ROOT / "ginarea_live" / "events.csv", EVENTS_HEADERS, BOT)
print(f"\nпоследние события ({len(events)} всего в хвосте):")
for e in events[-8:]:
    print(f"  {e['ts_utc']} {e['event_type']:10} dQ={e['delta_qty'] or e['delta_count']}"
          f" price_last={e['price_last']} pos_after={e['position_after']} profit_after={e['profit_after']}")

params = tail_rows(ROOT / "ginarea_live" / "params.csv", PARAMS_HEADERS, BOT)
print(f"\nparams-записей: {len(params)}")
for p in params[-4:]:
    raw = {}
    try:
        raw = json.loads(p["raw_params_json"])
    except json.JSONDecodeError:
        pass
    print(f"  {p['ts_utc']}: tsl={raw.get('tsl')} ttp={raw.get('ttp')} ttpinc={raw.get('ttpinc')}"
          f" border={raw.get('border')} p(вкл)={raw.get('p')}")
