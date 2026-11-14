"""Шаг 1 «сетки + система как страховка»: BTC-сетки оператора как сейчас — без закрытия по SMA, общий потолок — по
минуткам Binance 2018-01-01 … последний полный час. Пишет почасовой ряд: капитал (закрыто − комиссии − фандинг + мешок),
позиция BTC, себестоимость лотов.

ПРАВИЛА (записаны до прогона):
- Сетки (конфиги state/weex_grid*_config.json на 13.11, ордер в $ по сегодняшней цене ≈68k, как в trend_down_pause):
  BTC 0.6/1.4 — $82 (0.0012 BTC), потолок $12 000, 50 лотов; B34 0.1/0.34, B49 0.1/0.49, B89 0.1/0.89 — $41 (0.0006),
  потолки $4 462 / $4 361 / $3 709, лотов 61 / 59 / 56. Общий потолок BTC-сеток $12 500 (портфель $15 000 − ETH $2 500).
  Динамические тейки B89 (окно 2/3) не моделируются.
- Механика — trend_down_pause.run без режима: шаг от нижнего открытого лота, тейк у каждого лота, путь минуты
  O→L→H→C (зелёная) / O→H→L→C (красная); мейкер 0.016%; фандинг Binance на позицию.
- Это база для разбора; выводы — только после наложения системы и контроля.
"""
from __future__ import annotations

import hashlib
import sys
import time

import numpy as np
import pandas as pd

FROZEN = "/Users/alexeychechikov/code/bot7/backtests/frozen/"
OUT = "/Users/alexeychechikov/code/bot7/research/grid_hedge_20261114/grid_hourly.npz"
MAKER = 0.00016
GRIDS = [("BTC 0.6/1.4", 0.6, 1.4, 82.0, 12000.0, 50), ("B34", 0.1, 0.34, 41.0, 4462.0, 61),
         ("B49", 0.1, 0.49, 41.0, 4361.0, 59), ("B89", 0.1, 0.89, 41.0, 3709.0, 56)]
SHARED = 12500.0
START = 1514764800  # 2018-01-01


def load():
    parts = []
    for f in ("BTCUSDT_1m_2017_2024.csv", "BTCUSDT_1m_2y.csv"):
        raw = open(FROZEN + f, "rb").read()
        raw = raw[:raw.rfind(b"\n") + 1]
        print(f, "sha256", hashlib.sha256(raw).hexdigest()[:16], flush=True)
        parts.append(pd.read_csv(FROZEN + f))
    d = pd.concat(parts).drop_duplicates("ts").sort_values("ts")
    d["t"] = d["ts"] // 1000
    d = d[d["t"] >= START]
    last_full = (int(d["t"].iloc[-1]) + 60) // 3600 * 3600
    d = d[d["t"] < last_full]
    return d


def main():
    d = load()
    t = d["t"].to_numpy(np.int64)
    o, h, l, c = (d[k].to_numpy(float).tolist() for k in ("open", "high", "low", "close"))
    fr = pd.read_csv(FROZEN + "BTCUSDT_funding_full.csv")
    ft = fr["fundingTime"].to_numpy(np.int64) // 1000
    idx = np.searchsorted(t, ft, side="left")
    ok = (idx < len(t)) & (ft >= t[0])
    F = {int(i): float(r) for i, r in zip(idx[ok], fr["fundingRate"].to_numpy(float)[ok])}
    hr = (t // 3600).tolist()
    n = len(t)
    print(f"минут {n}, {pd.to_datetime(t[0], unit='s')} … {pd.to_datetime(t[-1], unit='s')}", flush=True)
    G = []
    for name, step, tgt, usd, cap, mx in GRIDS:
        G.append({"name": name, "g": step / 100, "tp": tgt / 100, "usd": usd, "cap": cap, "mx": mx,
                  "lots": [], "Q": 0.0, "QE": 0.0, "real": 0.0, "fee": 0.0, "ref": None, "n_tp": 0})
    fund = 0.0
    rec_t, rec_c, rec_eq, rec_q, rec_qe, rec_real = [], [], [], [], [], []
    t0 = time.time()
    for i in range(n):
        if i in F:
            fund += sum(g["Q"] for g in G) * o[i] * F[i]
        up = c[i] >= o[i]
        for p in (o[i], l[i] if up else h[i], h[i] if up else l[i], c[i]):
            tot_qe = sum(g["QE"] for g in G)
            for g in G:
                lots = g["lots"]
                while lots and p >= lots[-1][1]:
                    e, tp, q = lots.pop()
                    g["real"] += q * (tp - e)
                    g["fee"] += q * tp * MAKER
                    g["Q"] -= q
                    g["QE"] -= q * e
                    tot_qe -= q * e
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
                    px_in = min(lvl, p)
                    usd = g["usd"]
                    if max(g["QE"], g["Q"] * p) + usd <= g["cap"] and tot_qe + usd <= SHARED:
                        q = usd / px_in
                        lots.append([px_in, px_in * (1 + g["tp"]), q])
                        g["fee"] += usd * MAKER
                        g["Q"] += q
                        g["QE"] += usd
                        tot_qe += usd
        if i + 1 == n or hr[i + 1] != hr[i]:
            Q = sum(g["Q"] for g in G)
            QE = sum(g["QE"] for g in G)
            real = sum(g["real"] - g["fee"] for g in G) - fund
            rec_t.append(hr[i] * 3600)
            rec_c.append(c[i])
            rec_eq.append(real + Q * c[i] - QE)
            rec_q.append(Q)
            rec_qe.append(QE)
            rec_real.append(real)
        if i % 500000 == 0 and i:
            print(f"  {i}/{n} {time.time() - t0:.0f} с, капитал {rec_eq[-1]:+,.0f}", flush=True)
    np.savez(OUT, t=np.array(rec_t), c=np.array(rec_c), eq=np.array(rec_eq), q=np.array(rec_q), qe=np.array(rec_qe),
             real=np.array(rec_real))
    for g in G:
        print(f"{g['name']}: закрыто {g['real']:+,.0f}, комиссии {g['fee']:,.0f}, тейков {g['n_tp']}, лотов сейчас "
              f"{len(g['lots'])}, мешок {g['Q'] * c[-1] - g['QE']:+,.0f}")
    print(f"фандинг {fund:,.0f}; итог {rec_eq[-1]:+,.0f}; худший капитал {min(rec_eq):+,.0f}; "
          f"худшая просадка {min(np.array(rec_eq) - np.maximum.accumulate(rec_eq)):+,.0f}; {time.time() - t0:.0f} с")


if __name__ == "__main__":
    main()
