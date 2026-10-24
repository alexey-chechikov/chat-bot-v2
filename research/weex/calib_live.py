"""Калибровка бэктеста по живому отрезку: с состояния снимка 19.10 09:30:07 UTC (лоты, настройки) та же петля, что в
regime_grid/density_compare (path4 по минутам Binance spot, правило GinArea, мейкер 0.016%, касание = исполнение),
против журнала биржи WEEX по каждой сетке. Режим на отрезке — лонг (проверка: в журнале нет закрытий по режиму).
Сравниваются: входы, тейки, закрыто (gross), комиссии, лотов на конце окна."""
import json
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

ROOT = "/Users/alexeychechikov/code/bot7/state/"
SNAP = ROOT + "grid_compare_start_20261019T093007Z.json"
CSV = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--src=")),
           "/Users/alexeychechikov/code/bot7/backtests/frozen/BTCUSDT_1m_2y.csv")
JOURNAL = {"B34": "weex_grid_b34_journal.jsonl", "B49": "weex_grid_b49_journal.jsonl",
           "B89": "weex_grid_b89_journal.jsonl", "BTC": "weex_grid_journal.jsonl"}
MAKER = 0.00016


def iso(s):
    return datetime.fromisoformat(s).timestamp()


snap = json.load(open(SNAP))
t0 = iso(snap["created_utc"])
d = pd.read_csv(CSV)
d = d[d["ts"] // 1000 >= (int(t0) // 60 + 1) * 60]
o, h, l, c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
up = c >= o
pts = np.c_[o, np.where(up, l, h), np.where(up, h, l), c].tolist()
t_end = int(d["ts"].iloc[-1]) // 1000 + 60
print(f"окно {datetime.fromtimestamp(t0, timezone.utc):%d.%m %H:%M:%S} … "
      f"{datetime.fromtimestamp(t_end, timezone.utc):%d.%m %H:%M} UTC, минут {len(d)}")

for name, jf in JOURNAL.items():
    g = snap["grids"][name]
    cfg = g["config"]
    step, tgt = cfg["step_pct"] / 100, cfg["target_pct"] / 100
    qty, cap = float(cfg["order_qty"]), float(cfg["max_notional_usd"])
    max_lots = int(cfg["max_lots_per_side"])
    lots = sorted(([x["entry"], float(x["qty"]), x["tp"]] for x in g["sides"]["LONG"]["lots"]), key=lambda x: -x[0])
    n0 = len(lots)
    ref = lots[-1][0] if lots else None
    ent = tk = 0
    real = fee = 0.0
    for row in pts:
        for p in row:
            keep = []
            for lot in lots:
                if p >= lot[2]:
                    real += lot[1] * (lot[2] - lot[0])
                    fee += lot[1] * lot[2] * MAKER
                    tk += 1
                else:
                    keep.append(lot)
            lots = keep
            if lots:
                ref = min(x[0] for x in lots)
            elif ref is None:
                ref = p
            else:
                ref = max(ref, p)
            lvl = ref * (1 - step)
            cost = sum(x[0] * x[1] for x in lots)
            if p <= lvl and len(lots) < max_lots and max(cost, sum(x[1] for x in lots) * p) + qty * lvl <= cap:
                lots.append([lvl, qty, lvl * (1 + tgt)])
                fee += qty * lvl * MAKER
                ent += 1
    bag = sum(x[1] * (c[-1] - x[0]) for x in lots)
    # живое
    le = lt = 0
    lreal = lfee = 0.0
    other = {}
    for line in open(ROOT + jf):
        r = json.loads(line)
        if r.get("dry") or r.get("side") != "LONG":
            continue
        ts = iso(r["ts"])
        if not (t0 < ts <= t_end):
            continue
        k = r.get("kind")
        if k == "вход":
            le += 1
            lfee += float(r.get("fee") or 0)
        elif k == "тейк":
            lt += 1
            lreal += float(r.get("pnl") or 0)
            lfee += float(r.get("fee") or 0)
        else:
            other[k] = other.get(k, 0) + 1
    print(f"{name} {cfg['step_pct']:g}/{cfg['target_pct']:g} ордер {qty} потолок ${cap:,.0f}/{max_lots}: старт лотов {n0}\n"
          f"   бэктест: входов {ent:4d}, тейков {tk:4d}, закрыто ${real:7.2f}, комиссии ${fee:5.2f}, "
          f"лотов на конце {len(lots):2d}, мешок ${bag:+7.2f}\n"
          f"   биржа:   входов {le:4d}, тейков {lt:4d}, закрыто ${lreal:7.2f}, комиссии ${lfee:5.2f}, "
          f"лотов на конце {n0 + le - lt:2d}{'  прочее ' + str(other) if other else ''}")
