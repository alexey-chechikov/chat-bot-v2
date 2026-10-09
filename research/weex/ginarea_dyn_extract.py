"""Реверс механики GinArea DYNAMIC по живому ETH-боту 4470088018 (Auto, hedge=false):
поминутно уровни входа border.from/to (params.csv), позиция/входы/выходы/средняя (snapshots.csv)
и цена ETH (Binance 1m). Пишет research/weex/ginarea_dyn_eth.csv."""
import csv
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOT = sys.argv[1] if len(sys.argv) > 1 else "4470088018"
SYM = sys.argv[2] if len(sys.argv) > 2 else "ETHUSDT"
OUT = Path(__file__).with_name(f"ginarea_dyn_{BOT}.csv")
csv.field_size_limit(sys.maxsize)


def minute(ts: str) -> int:
    return int(datetime.fromisoformat(ts).timestamp()) // 60 * 60


def rows(path: Path):
    with path.open(encoding="utf-8", errors="replace") as f:
        yield from csv.DictReader(l.replace("\0", "") for l in f)


par = {}
for r in rows(ROOT / "ginarea_live" / "params.csv"):
    if r["bot_id"] == BOT:
        p = json.loads(r["raw_params_json"])
        b = p.get("border") or {}
        par[minute(r["ts_utc"])] = (b.get("from"), b.get("to"), p.get("gs"), p.get("so"), p.get("ioo"),
                                    (p.get("gap") or {}).get("tog"))
snap = {}
for r in rows(ROOT / "ginarea_live" / "snapshots.csv"):
    if r["bot_id"] == BOT:
        snap[minute(r["ts_utc"])] = r

t0, t1 = min(snap), max(snap)
px = {}
start = t0 * 1000
while start < t1 * 1000:
    url = f"https://api.binance.com/api/v3/klines?symbol={SYM}&interval=1m&limit=1000&startTime={start}"
    chunk = json.loads(urllib.request.urlopen(url, timeout=20).read())
    if not chunk:
        break
    for k in chunk:
        px[k[0] // 1000] = (float(k[1]), float(k[2]), float(k[3]), float(k[4]))
    start = chunk[-1][0] + 60_000
    time.sleep(0.1)

cols = ["ts", "open", "high", "low", "close", "from", "to", "gs", "so", "ioo", "tog", "status", "position",
        "in_cnt", "in_qty", "out_cnt", "out_qty", "avg", "profit", "cur_profit", "volume"]
last_par = (None,) * 6
n = 0
with OUT.open("w", newline="") as f:
    w = csv.writer(f)
    w.writerow(cols)
    for t in sorted(snap):
        s = snap[t]
        last_par = par.get(t, last_par)
        o = px.get(t, (None,) * 4)
        w.writerow([datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M"), *o, *last_par,
                    s["status"], s["position"], s["in_filled_count"], s["in_filled_qty"], s["out_filled_count"],
                    s["out_filled_qty"], s["average_price"], s["profit"], s["current_profit"], s["trade_volume"]])
        n += 1
print(f"{BOT}: {n} минут {datetime.fromtimestamp(t0, timezone.utc)} → {datetime.fromtimestamp(t1, timezone.utc)}, "
      f"минут с уровнями {len(par)}, с ценой {sum(1 for t in snap if t in px)} → {OUT.name}")
