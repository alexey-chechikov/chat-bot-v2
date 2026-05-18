"""Текущий статус TB бота из последних snapshots."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / "ginarea_live" / "snapshots.csv"
TB_ID = "4525648417"

STATUS_MAP = {
    "0": "CREATED",  "1": "STARTING", "2": "ACTIVE",
    "3": "PAUSED", "4": "DISABLE_IN", "10": "FAILED",
    "11": "STOPPING", "12": "STOPPED",
}


def main():
    if not SNAPSHOTS.exists():
        print("No snapshots.csv")
        return
    rows = []
    with SNAPSHOTS.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            bid = str(row.get("bot_id", "")).split(".")[0]
            if bid != TB_ID:
                continue
            rows.append(row)
    if not rows:
        print(f"No TB ({TB_ID}) snapshots")
        return

    print(f"TB snapshots total: {len(rows)}")
    print()
    print("Last 20 status changes:")
    last_status = None
    changes = []
    for r in rows:
        st = str(r.get("status", "")).split(".")[0]
        if st != last_status:
            changes.append((r.get("ts_utc", ""), st, r.get("position", "?"),
                             r.get("current_profit", "?")))
            last_status = st

    for ts, st, pos, cp in changes[-20:]:
        st_name = STATUS_MAP.get(st, st)
        print(f"  {ts[:19]}  status={st_name:12}  pos={pos}  unrealized_profit={cp}")

    # Time spent in each status
    from collections import defaultdict
    time_in_status = defaultdict(float)
    prev_ts = None
    prev_st = None
    for r in rows:
        try:
            ts = datetime.fromisoformat(r["ts_utc"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        st = str(r.get("status", "")).split(".")[0]
        if prev_ts is not None and prev_st is not None:
            elapsed = (ts - prev_ts).total_seconds()
            if elapsed < 600:  # Skip gaps > 10 min
                time_in_status[prev_st] += elapsed
        prev_ts = ts
        prev_st = st

    total = sum(time_in_status.values())
    if total > 0:
        print(f"\nTime distribution per status (по 1-min snapshots):")
        for st, sec in sorted(time_in_status.items(), key=lambda x: -x[1]):
            print(f"  {STATUS_MAP.get(st, st):12} {sec/3600:>6.1f}h  ({100*sec/total:>5.1f}%)")


if __name__ == "__main__":
    main()
