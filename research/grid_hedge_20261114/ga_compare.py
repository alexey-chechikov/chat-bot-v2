"""Сравнение моей механики сетки с движком GinArea по ga_validate.jsonl (те же окна и параметры: шаг gs, цель tog,
выход по каждому ордеру, 50 ордеров, 0.001 BTC). Моя механика — та же петля, что в grid_sim.py, на минутках Binance
(frozen BTCUSDT_1m_2y.csv), путь минуты O→L→H→C (зелёная) / O→H→L→C (красная).

Два варианта поведения на старте и когда сетка пуста (это и проверяем):
  A (как grid_sim): ждать падения на gs от опорной цены; пока пусто — опорная тянется за максимумом;
  B: покупать сразу по рынку на старте и сразу после последнего тейка.
Комиссия: у меня 0 (валовое), у GinArea — своя; оцениваю её как (моё валовое закрыто − закрыто GinArea) / оборот.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
FROZEN = Path("/Users/alexeychechikov/code/bot7/backtests/frozen/BTCUSDT_1m_2y.csv")


def load():
    d = pd.read_csv(FROZEN, usecols=["ts", "open", "high", "low", "close"])
    return (d["ts"].to_numpy(np.int64), d["open"].to_numpy(float), d["high"].to_numpy(float),
            d["low"].to_numpy(float), d["close"].to_numpy(float))


def sim(data, a_ms, b_ms, gs, tog, qty=0.001, maxop=50, mode="A"):
    ts, O, H, L, Cc = data
    i0, i1 = np.searchsorted(ts, a_ms), np.searchsorted(ts, b_ms)
    g, tp = gs / 100, tog / 100
    lots = []                      # [вход, тейк]
    ref = None
    n_in = n_out = 0
    vol = real = 0.0
    maxpos = 0
    for i in range(i0, i1):
        o, h, l, c = O[i], H[i], L[i], Cc[i]
        up = c >= o
        for p in (o, l if up else h, h if up else l, c):
            while lots and p >= lots[-1][1]:
                e, t = lots.pop()
                real += qty * (t - e)
                vol += qty * t
                n_out += 1
            if mode == "B" and not lots:
                lots.append([p, p * (1 + tp)])
                vol += qty * p
                n_in += 1
                continue
            if lots:
                ref = lots[-1][0]
            elif ref is None:
                ref = p
            else:
                ref = max(ref, p)
            lvl = ref * (1 - g)
            if p <= lvl and len(lots) < maxop:
                px = min(lvl, p)
                lots.append([px, px * (1 + tp)])
                vol += qty * px
                n_in += 1
        maxpos = max(maxpos, len(lots))
    last = Cc[i1 - 1]
    pos = qty * len(lots)
    unreal = sum(qty * (last - e) for e, _ in lots)
    avg = (sum(e for e, _ in lots) / len(lots)) if lots else 0.0
    return {"входов": n_in, "тейков": n_out, "оборот": vol, "закрыто": real, "позиция": pos, "мешок": unreal,
            "итог": real + unreal, "средняя": avg, "макс. позиция": qty * maxpos}


def main():
    recs = [json.loads(x) for x in (HERE / "ga_validate.jsonl").read_text(encoding="utf-8").splitlines()]
    data = load()
    rows = []
    for r in recs:
        s = r["stat"]
        a = int(datetime.fromisoformat(r["from"]).timestamp() * 1000)
        b = int(datetime.fromisoformat(r["to"]).timestamp() * 1000)
        ga = {"входов": s["inFilledCount"], "тейков": s["outFilledCount"], "оборот": s["tradeVolume"],
              "закрыто": s["profit"], "позиция": s["position"], "итог": s["currentProfit"],
              "средняя": (s.get("extension") or {}).get("avgPL") or s["averagePrice"]}
        for mode in ("A", "B"):
            m = sim(data, a, b, r["gs"], r["tog"], mode=mode)
            fee = (m["закрыто"] - ga["закрыто"]) / ga["оборот"] if ga["оборот"] else float("nan")
            rows.append({"сетка": f"{r['gs']}/{r['tog']}", "окно": r["label"], "вариант": mode,
                         "GA входов": ga["входов"], "мои входов": m["входов"],
                         "GA тейков": ga["тейков"], "мои тейков": m["тейков"],
                         "GA оборот": round(ga["оборот"]), "мой оборот": round(m["оборот"]),
                         "GA закрыто": round(ga["закрыто"], 2), "моё валовое": round(m["закрыто"], 2),
                         "комиссия GA, % оборота": round(fee * 100, 4),
                         "GA позиция": ga["позиция"], "моя позиция": round(m["позиция"], 4),
                         "GA итог": round(ga["итог"], 2), "мой итог валовой": round(m["итог"], 2)})
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    pd.set_option("display.max_rows", 200)
    print(df.to_string(index=False))
    df.to_csv(HERE / "ga_compare.csv", index=False)
    print("\nСВОДКА: месячные окна суммой (каждый месяц с пустой сетки) и год непрерывно")
    for (grid, mode), g in df.groupby(["сетка", "вариант"]):
        mon = g[g["окно"].str.startswith("месяц")]
        yr = g[g["окно"].str.startswith("год")]
        s = mon.sum(numeric_only=True)
        err = (mon["мой итог валовой"] - mon["GA итог"]).abs().mean()
        line = (f"{grid} вар. {mode}: месяцев {len(mon)} · входов {s['мои входов']:.0f} против {s['GA входов']:.0f} "
                f"({s['мои входов'] / s['GA входов'] - 1:+.1%}) · тейков {s['мои тейков']:.0f} против {s['GA тейков']:.0f} "
                f"({s['мои тейков'] / s['GA тейков'] - 1:+.1%}) · закрыто {s['моё валовое']:+.0f} против {s['GA закрыто']:+.0f} "
                f"({s['моё валовое'] / s['GA закрыто'] - 1:+.1%}) · итог с мешком {s['мой итог валовой']:+.0f} против "
                f"{s['GA итог']:+.0f}, средняя ошибка месяца {err:.0f}$")
        if len(yr):
            y = yr.iloc[0]
            line += (f"\n      год непрерывно: закрыто {y['моё валовое']:+.0f} против {y['GA закрыто']:+.0f}, итог "
                     f"{y['мой итог валовой']:+.0f} против {y['GA итог']:+.0f}, позиция {y['моя позиция']} против "
                     f"{y['GA позиция']}, входов {y['мои входов']} против {y['GA входов']}")
        print(line)


if __name__ == "__main__":
    main()
