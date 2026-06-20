"""Кто торговал BTC 16:52–16:55 (CEST, оператор) = 14:52–14:55 UTC 2026-06-12.

Смотрим: (1) события всех GinArea-ботов в окне ±10 мин, (2) изменения позиций
BTC-ботов из снапшотов, (3) auto_executor (живые BitMEX-ордера bot7)."""
import csv
import json
import sys
from pathlib import Path

csv.field_size_limit(10_000_000)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ginarea_tracker.storage import EVENTS_HEADERS, SNAPSHOTS_HEADERS

LO, HI = "2026-06-12T14:40", "2026-06-12T15:10"


def tail(path, headers, max_bytes=20_000_000):
    size = path.stat().st_size
    with path.open("rb") as fh:
        if size > max_bytes:
            fh.seek(size - max_bytes)
            fh.readline()
        text = fh.read().decode("utf-8", errors="replace")
    for rec in csv.reader(text.replace("\x00", "").splitlines()):
        if len(rec) == len(headers):
            yield dict(zip(headers, rec))


print(f"=== GinArea события {LO}–{HI} UTC (все боты) ===")
n = 0
for e in tail(ROOT / "ginarea_live" / "events.csv", EVENTS_HEADERS):
    if LO <= e["ts_utc"] <= HI:
        n += 1
        print(f"{e['ts_utc']} {e['bot_name'][:24]:24} {e['event_type']:10} "
              f"price={e['price_last']} pos_after={e['position_after']} profit_after={e['profit_after'][:9]}")
print(f"(событий: {n})")

print(f"\n=== BTC-боты: позиция вокруг окна (снапшоты) ===")
seen = {}
for s in tail(ROOT / "ginarea_live" / "snapshots.csv", SNAPSHOTS_HEADERS):
    if "2026-06-12T14:35" <= s["ts_utc"] <= "2026-06-12T15:15":
        name = s["bot_name"]
        if "SHORT" in name or "BTC" in name or "T2" in name or "T3" in name:
            key = (s["bot_id"], s["position"])
            if seen.get(s["bot_id"]) != s["position"]:
                print(f"{s['ts_utc']} {name[:22]:22} pos={s['position']:>10} profit={s['profit'][:9]}")
                seen[s["bot_id"]] = s["position"]

print("\n=== auto_executor (живые BitMEX-ордера bot7) ===")
st = ROOT / "state" / "auto_executor_state.json"
if st.exists():
    print("state:", st.read_text(encoding="utf-8")[:400])
out = ROOT / "state" / "auto_executor_outcomes.jsonl"
if out.exists():
    lines = out.read_text(encoding="utf-8").splitlines()
    print(f"outcomes: {len(lines)} всего, последние 3:")
    for line in lines[-3:]:
        print(" ", line[:250])
