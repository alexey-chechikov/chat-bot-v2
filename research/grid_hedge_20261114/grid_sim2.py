"""Шаг 1б (14.11, оператор: «досчитай с эфиром»): BTC-сетки и ETH-сетка оператора ВМЕСТЕ на одном счёте — без
закрытия по SMA, общий потолок портфеля $15 000 по себестоимости (state/weex_portfolio_config.json), минутки Binance
2018-01-01 … последний полный час. Пишет почасовой ряд по каждой монете: капитал (закрыто − комиссии − фандинг + мешок),
позиция, себестоимость.

ПРАВИЛА (записаны до прогона):
- BTC — как grid_sim.py: 0.6/1.4 $82 (0.0012 BTC), потолок $12 000, 50 лотов; B34/B49/B89 шаг 0.1, цели 0.34/0.49/0.89,
  $41 (0.0006 BTC), потолки $4 462 / $4 361 / $3 709, лотов 61 / 59 / 56. Динамические тейки B89 не моделируются.
- ETH 0.6/1.4: 0.020 ETH по цене последней минуты (≈$39), потолок $2 500, 50 лотов (state/weex_grid_eth_config.json).
- Общий потолок всех пяти сеток $15 000 по себестоимости (у grid_sim.py было BTC $12 500 — ETH вне счёта).
- Механика та же: шаг от нижнего открытого лота, тейк у каждого лота; когда сетка пуста, опорная цена тянется за
  максимумом (первый вход на шаг ниже максимума); путь минуты O→L→H→C / O→H→L→C; мейкер 0.016%; фандинг Binance.
- Минуты — пересечение BTC и ETH по метке времени (внутри минуты сначала BTC, потом ETH).
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

import numpy as np
import pandas as pd

FROZEN = "/Users/alexeychechikov/code/bot7/backtests/frozen/"
OUT = Path(__file__).with_name("grid_hourly2.npz")
MAKER = 0.00016
SHARED = 15000.0
ETH_USD = 38.60                               # 0.020 ETH × 1 929.88 (закрытие 13.11.2026)
START = 1514764800  # 2018-01-01


def load(sym):
    parts = []
    for f in (f"{sym}_1m_2017_2024.csv", f"{sym}_1m_2y.csv"):
        raw = open(FROZEN + f, "rb").read()
        raw = raw[:raw.rfind(b"\n") + 1]
        print(f, "sha256", hashlib.sha256(raw).hexdigest()[:16], flush=True)
        parts.append(pd.read_csv(FROZEN + f, usecols=["ts", "open", "high", "low", "close"]))
    d = pd.concat(parts).drop_duplicates("ts").sort_values("ts")
    d["t"] = d["ts"] // 1000
    return d[d["t"] >= START].set_index("t")[["open", "high", "low", "close"]]


def funding(sym, t):
    fr = pd.read_csv(FROZEN + f"{sym}_funding_full.csv")
    ft = fr["fundingTime"].to_numpy(np.int64) // 1000
    idx = np.searchsorted(t, ft, side="left")
    ok = (idx < len(t)) & (ft >= t[0])
    return {int(i): float(r) for i, r in zip(idx[ok], fr["fundingRate"].to_numpy(float)[ok])}


def main():
    b, e = load("BTCUSDT"), load("ETHUSDT")
    d = b.join(e, how="inner", lsuffix="_b", rsuffix="_e")
    last_full = (int(d.index[-1]) + 60) // 3600 * 3600
    d = d[d.index < last_full]
    t = d.index.to_numpy(np.int64)
    n = len(t)
    eth_px = float(d["close_e"].iloc[-1])
    eth_usd = ETH_USD                         # разбор ead2ca4: константа, а не 0.020 × последняя цена выборки
    print(f"минут {n} (пересечение), {pd.to_datetime(t[0], unit='s')} … {pd.to_datetime(t[-1], unit='s')}; "
          f"ETH {eth_px:,.2f} → ордер ETH ${eth_usd:.2f}", flush=True)
    px = {s: [d[f"{k}_{s}"].to_numpy(float).tolist() for k in ("open", "high", "low", "close")] for s in ("b", "e")}
    F = {"b": funding("BTCUSDT", t), "e": funding("ETHUSDT", t)}
    specs = [("b", "BTC 0.6/1.4", 0.6, 1.4, 82.0, 12000.0, 50), ("b", "B34", 0.1, 0.34, 41.0, 4462.0, 61),
             ("b", "B49", 0.1, 0.49, 41.0, 4361.0, 59), ("b", "B89", 0.1, 0.89, 41.0, 3709.0, 56),
             ("e", "ETH 0.6/1.4", 0.6, 1.4, eth_usd, 2500.0, 50)]
    G = [{"s": s, "name": nm, "g": st / 100, "tp": tg / 100, "usd": u, "cap": cap, "mx": mx, "lots": [], "Q": 0.0,
          "QE": 0.0, "real": 0.0, "fee": 0.0, "ref": None, "n_tp": 0} for s, nm, st, tg, u, cap, mx in specs]
    by = {s: [g for g in G if g["s"] == s] for s in ("b", "e")}
    fund = {"b": 0.0, "e": 0.0}
    hr = (t // 3600).tolist()
    rec = {k: [] for k in ("t", "cb", "ce", "eqb", "eqe", "qb", "qe", "qeb", "qee")}
    t0 = time.time()
    tot_qe = 0.0
    prev = {"b": None, "e": None}
    for i in range(n):
        for s in ("b", "e"):
            o, h, l, c = (px[s][k][i] for k in range(4))
            if i in F[s]:
                fund[s] += sum(g["Q"] for g in by[s]) * o * F[s][i]
            up = c >= o
            for p in (o, l if up else h, h if up else l, c):
                pp, prev[s] = prev[s], p
                for g in by[s]:
                    lots = g["lots"]
                    while lots and p >= lots[-1][1]:
                        en, tp, q = lots.pop()
                        g["real"] += q * (tp - en)
                        g["fee"] += q * tp * MAKER
                        g["Q"] -= q
                        g["QE"] -= q * en
                        tot_qe -= q * en
                        g["n_tp"] += 1
                    if not lots:
                        tot_qe -= g["QE"]
                        g["Q"] = g["QE"] = 0.0
                    if lots:
                        g["ref"] = lots[-1][0]
                    elif g["ref"] is None:
                        g["ref"] = p
                    else:
                        g["ref"] = max(g["ref"], p)
                    lvl = g["ref"] * (1 - g["g"])
                    if p <= lvl and len(lots) < g["mx"]:
                        px_in = lvl if (pp is not None and pp > lvl) else p  # разбор ead2ca4: лимитка входа исполняется по своему уровню, если цена прошла его сверху; ниже уже — по цене точки
                        usd = g["usd"]
                        if max(g["QE"], g["Q"] * p) + usd <= g["cap"] and tot_qe + usd <= SHARED:
                            q = usd / px_in
                            lots.append([px_in, px_in * (1 + g["tp"]), q])
                            g["fee"] += usd * MAKER
                            g["Q"] += q
                            g["QE"] += usd
                            tot_qe += usd
        if i + 1 == n or hr[i + 1] != hr[i]:
            rec["t"].append(hr[i] * 3600 + 3600)        # разбор ead2ca4: метка — КОНЕЦ часа (значения на его закрытии)
            for s in ("b", "e"):
                c = px[s][3][i]
                Q = sum(g["Q"] for g in by[s])
                QE = sum(g["QE"] for g in by[s])
                real = sum(g["real"] - g["fee"] for g in by[s]) - fund[s]
                rec["c" + s].append(c)
                rec["eq" + s].append(real + Q * c - QE)
                rec["q" + s].append(Q)
                rec["qe" + s].append(QE)
        if i % 1000000 == 0 and i:
            print(f"  {i}/{n} {time.time() - t0:.0f} с, BTC {rec['eqb'][-1]:+,.0f}, ETH {rec['eqe'][-1]:+,.0f}", flush=True)
    np.savez(OUT, **{k: np.array(v) for k, v in rec.items()}, eth_usd=eth_usd)
    for g in G:
        last = px[g["s"]][3][-1]
        print(f"{g['name']}: закрыто {g['real']:+,.0f}, комиссии {g['fee']:,.0f}, тейков {g['n_tp']}, лотов сейчас "
              f"{len(g['lots'])}, мешок {g['Q'] * last - g['QE']:+,.0f}")
    eq = np.array(rec["eqb"]) + np.array(rec["eqe"])
    print(f"фандинг BTC {fund['b']:,.0f}, ETH {fund['e']:,.0f}; итог BTC {rec['eqb'][-1]:+,.0f}, ETH {rec['eqe'][-1]:+,.0f}, "
          f"вместе {eq[-1]:+,.0f}; худшая просадка вместе {np.min(eq - np.maximum.accumulate(eq)):+,.0f}; "
          f"{time.time() - t0:.0f} с")


if __name__ == "__main__":
    main()
