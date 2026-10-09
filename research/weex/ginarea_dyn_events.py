"""Показ событий DYNAMIC: минуты, где менялись уровни from/to, позиция, входы или выходы."""
import csv
import sys
from pathlib import Path

BOT = sys.argv[1] if len(sys.argv) > 1 else "4470088018"
A = sys.argv[2] if len(sys.argv) > 2 else "2026-09-22 03:20"
B = sys.argv[3] if len(sys.argv) > 3 else "2026-09-22 09:00"
f = Path(__file__).with_name(f"ginarea_dyn_{BOT}.csv")
prev = None
for r in csv.DictReader(f.open()):
    if not (A <= r["ts"] <= B):
        continue
    key = (r["from"], r["to"], r["position"], r["in_cnt"], r["out_cnt"], r["status"])
    if key != prev:
        fr, to = float(r["from"] or 0), float(r["to"] or 0)
        c = float(r["close"])
        mid = (fr + to) / 2 if fr and to else 0
        print(f"{r['ts']} st{r['status']} цена o{float(r['open']):.2f} h{float(r['high']):.2f} l{float(r['low']):.2f} "
              f"c{c:.2f} | from {fr:.2f} to {to:.2f} центр {mid:.2f} ({(mid / c - 1) * 100 if mid else 0:+.2f}%) | "
              f"поз {r['position']} вх {r['in_cnt']}/{r['in_qty']} вых {r['out_cnt']}/{r['out_qty']} ср {r['avg']} "
              f"приб {float(r['profit']):.2f}")
        prev = key
