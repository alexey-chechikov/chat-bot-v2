"""Таблица маршрутов для утренней аналитики (22.10, оператор: «нужны выводы, а не сухие данные»): в каком состоянии рынка
что вероятнее первым за 24 ч — +1% или −1%. Состояние — где цена относительно максимума и минимума последних 12 ч.

ПРАВИЛА ДО ПРОГОНА:
- Данные: frozen 1m Binance spot BTC и ETH (копии), старты каждый час; уровни ±1.0% от цены старта; что первым за 24 ч
  (оба в одной минуте — «низ»); никто — не в доле.
- Состояния (заранее): «падение ≥3.5%» — цена ≥3.5% ниже максимума 12 ч; «падение 2–3.5%»; «рост ≥3.5%» — ≥3.5% выше
  минимума 12 ч; «рост 2–3.5%»; иначе «спокойно». Оба условия сразу — берётся большее по модулю.
- Внутри состояния события не чаще раза в 24 ч (иначе один эпизод считается десятки раз); доля «вверх первым», 95%
  интервал, половины по времени.
Пишет state/market_brief/route_table.json. Запуск: route_table.py --btc=<копия> --eth=<копия>
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ARG = {a.split("=", 1)[0]: a.split("=", 1)[1] for a in sys.argv[1:] if "=" in a}
SRC = {"BTCUSDT": ARG.get("--btc", "/Users/alexeychechikov/code/bot7/backtests/frozen/BTCUSDT_1m_2y.csv"),
       "ETHUSDT": ARG.get("--eth", "/Users/alexeychechikov/code/bot7/backtests/frozen/ETHUSDT_1m_2y.csv")}
OUT = Path("/Users/alexeychechikov/code/bot7/state/market_brief/route_table.json")
B, LOOK, W = 0.01, 720, 1440
STATES = ("падение ≥3.5%", "падение 2–3.5%", "спокойно", "рост 2–3.5%", "рост ≥3.5%")


def state_of(c: float, hmax: float, lmin: float) -> str:
    dd, ru = c / hmax - 1, c / lmin - 1
    if -dd >= ru:
        return "падение ≥3.5%" if dd <= -0.035 else "падение 2–3.5%" if dd <= -0.02 else "спокойно"
    return "рост ≥3.5%" if ru >= 0.035 else "рост 2–3.5%" if ru >= 0.02 else "спокойно"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if not n:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def table(path: str) -> dict:
    d = pd.read_csv(path)
    h, l, c = (d[k].to_numpy(float) for k in ("high", "low", "close"))
    ts = d["ts"].to_numpy(np.int64)
    n = len(c)
    hmax = pd.Series(h).rolling(LOOK, min_periods=LOOK).max().to_numpy()
    lmin = pd.Series(l).rolling(LOOK, min_periods=LOOK).min().to_numpy()
    mid = n // 2
    acc = {s: {"up": [0, 0], "dn": [0, 0]} for s in STATES}       # [1-я половина, 2-я]
    last = {s: -10**9 for s in STATES}
    for i in range(LOOK + 59, n - W - 1, 60):
        s = state_of(c[i], hmax[i], lmin[i])
        if i - last[s] < W:
            continue
        hs, ls = h[i + 1:i + 1 + W], l[i + 1:i + 1 + W]
        a, b = np.flatnonzero(hs >= c[i] * (1 + B)), np.flatnonzero(ls <= c[i] * (1 - B))
        if not len(a) and not len(b):
            continue
        last[s] = i
        up = len(a) and (not len(b) or a[0] < b[0])
        acc[s]["up" if up else "dn"][0 if i < mid else 1] += 1
    out = {}
    for s, v in acc.items():
        up, dn = sum(v["up"]), sum(v["dn"])
        n_ = up + dn
        lo, hi = wilson(up, n_)
        halves = [v["up"][k] / (v["up"][k] + v["dn"][k]) if v["up"][k] + v["dn"][k] else None for k in (0, 1)]
        out[s] = {"n": n_, "p_up": up / n_ if n_ else None, "lo": lo, "hi": hi, "halves": halves}
    return {"from": str(pd.to_datetime(ts[0], unit="ms")), "to": str(pd.to_datetime(ts[-1], unit="ms")), "states": out}


def main():
    res = {"built_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "barrier": B, "look_min": LOOK,
           "window_min": W, "symbols": {s: table(p) for s, p in SRC.items()}}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for sym, t in res["symbols"].items():
        print(f"{sym} {t['from']} … {t['to']}")
        for s, v in t["states"].items():
            hv = " / ".join("—" if x is None else f"{x * 100:.0f}%" for x in v["halves"])
            print(f"  {s:<15} n {v['n']:4d} · вверх первым {v['p_up'] * 100:5.1f}% [{v['lo'] * 100:.0f}…{v['hi'] * 100:.0f}]"
                  f" · половины {hv}")


if __name__ == "__main__":
    main()
