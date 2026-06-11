"""Q4 Вина: меняется ли step Dynamic-Auto на живом боте без рестарта/сброса позиции.
Смотрим экспорт 10.06: история gs (step) по ботам + статус/позиция вокруг смены."""
import csv
import json
from pathlib import Path

D = Path("/Users/alexeychechikov/code/bot7/docs/CONTEXT/data/alt_run_2026-06-10")

params = list(csv.DictReader((D / "params.csv").open(encoding="utf-8")))
snaps = list(csv.DictReader((D / "snapshots.csv").open(encoding="utf-8")))

for bot, name in (("5693279219", "SOL"), ("5617871752", "WLD"), ("4306550166", "XRP")):
    rows = [p for p in params if p["bot_id"] == bot]
    prev = None
    changes = []
    for p in rows:
        raw = json.loads(p["raw_params_json"])
        key = (raw.get("gs"), raw.get("gap", {}).get("tog"), raw.get("tsl"), raw.get("ttp"))
        if prev is not None and key != prev:
            changes.append((p["ts_utc"], prev, key))
        prev = key
    print(f"── {name}: {len(rows)} params-строк, изменений (gs/tog/tsl/ttp): {len(changes)}")
    for ts, old, new in changes:
        print(f"   {ts}: gs {old[0]}→{new[0]} tog {old[1]}→{new[1]} tsl {old[2]}→{new[2]} ttp {old[3]}→{new[3]}")
        # позиция/статус вокруг смены
        around = [s for s in snaps if s["bot_id"] == bot and abs(
            (int(ts[11:13]) * 60 + int(ts[14:16])) - (int(s["ts_utc"][11:13]) * 60 + int(s["ts_utc"][14:16]))) <= 3
            and s["ts_utc"][:10] == ts[:10]]
        for s in around:
            print(f"      {s['ts_utc']} st={s['status']} pos={s['position']} profit={s['profit'][:8]}")
