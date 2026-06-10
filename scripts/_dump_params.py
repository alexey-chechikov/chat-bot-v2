"""Полный raw params JSON последней записи бота из params.csv (найти поле SL)."""
import csv
import json
import sys
from pathlib import Path

csv.field_size_limit(10_000_000)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ginarea_tracker.storage import PARAMS_HEADERS

target = sys.argv[1] if len(sys.argv) > 1 else "4306550166"
last = None
with (ROOT / "ginarea_live" / "params.csv").open(newline="", encoding="utf-8", errors="replace") as fh:
    cleaned = (line.replace("\x00", "") for line in fh)
    for rec in csv.reader(cleaned):
        if len(rec) == len(PARAMS_HEADERS) and rec[1] == target:
            last = rec
if not last:
    print("нет params для", target)
    raise SystemExit(1)
row = dict(zip(PARAMS_HEADERS, last))
print("ts:", row["ts_utc"], "bot:", row["bot_name"])
print(json.dumps(json.loads(row["raw_params_json"]), ensure_ascii=False, indent=1, sort_keys=True))
