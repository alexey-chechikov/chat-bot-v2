"""Последние параметры ботов GinArea из params.csv трекера (без логина). Аргументы — bot_id."""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
csv.field_size_limit(sys.maxsize)
want = set(sys.argv[1:])
last = {}
with (ROOT / "ginarea_live" / "params.csv").open(encoding="utf-8", errors="replace") as f:
    for r in csv.DictReader(l.replace("\0", "") for l in f):
        if r["bot_id"] in want:
            last[r["bot_id"]] = r
for bid, r in last.items():
    p = json.loads(r["raw_params_json"])
    keep = {k: p.get(k) for k in ("side", "gs", "gsr", "maxOp", "maxOpL", "maxOpS", "so", "ioo", "obap", "hedge",
                                  "dsblin", "dsblinbap", "border", "gap", "q", "in")}
    print(bid, r["bot_name"], r["ts_utc"], json.dumps(keep, ensure_ascii=False))
