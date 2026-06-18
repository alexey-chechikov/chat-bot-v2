"""Форензика обрыва SOL (5693279219): что было вокруг слива к −350.
Таймлайн снапшотов 14-16.06: позиция, profit, мешок, статус — где набрался завал."""
import csv
import sys
from pathlib import Path

csv.field_size_limit(10_000_000)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ginarea_tracker.storage import SNAPSHOTS_HEADERS

BOT = "5693279219"
path = ROOT / "ginarea_live" / "snapshots.csv"
size = path.stat().st_size
with path.open("rb") as fh:
    fh.seek(max(0, size - 60_000_000))
    fh.readline()
    text = fh.read().decode("utf-8", errors="replace")

rows = []
for rec in csv.reader(text.replace("\x00", "").splitlines()):
    if len(rec) != len(SNAPSHOTS_HEADERS) or rec[1] != BOT:
        continue
    r = dict(zip(SNAPSHOTS_HEADERS, rec))
    if r["ts_utc"] < "2026-06-14T18":
        continue
    rows.append(r)

print(f"SOL снапшотов 14.06 18:00+: {len(rows)}")
print(f"{'ts':22}{'st':>3}{'pos':>10}{'profit':>9}{'curProf':>9}{'мешок':>8}{'цена~avg':>10}")
prev_key = None
peak_bag = 0.0
worst = None
for r in rows:
    try:
        pos = float(r["position"] or 0); pr = float(r["profit"] or 0)
        cur = float(r["current_profit"] or 0); avg = float(r["average_price"] or 0)
    except ValueError:
        continue
    bag = cur - pr
    if bag < peak_bag:
        peak_bag = bag; worst = (r["ts_utc"], bag, pos, cur)
    key = (r["status"], round(pos, 1))
    if key != prev_key:   # печатаем на смену статуса/позиции (узлы)
        print(f"{r['ts_utc']:22}{r['status']:>3}{pos:>10.2f}{pr:>9.1f}{cur:>9.1f}{bag:>8.0f}{avg:>10.2f}")
        prev_key = key
print(f"\nХУДШИЙ мешок: {worst[1]:.0f}$ в {worst[0]} (поза {worst[2]:.1f}, total {worst[3]:.0f})" if worst else "нет")
