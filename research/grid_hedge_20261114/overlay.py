"""Шаг 1: худшие просадки BTC-сеток (grid_hourly.npz) и что в это время делала система оператора; наложение шорта
системы размером k × позиция сеток.

ПРАВИЛА (до прогона):
- Страховка = шорт, пока система в шорте (теги «под синей» и «под жёлтой»). Первый лот на входе системы: k × 0.5 ×
  позиция сеток в этот час; добор системы: ещё k × 0.5 × позиция сеток в час добора. Выход — выход системы.
  Издержка 0.068% на сторону (как в engine.SC), фандинг страховки не считается (шорт обычно получает — консервативно).
- k ∈ {0, 0.25, 0.5, 1.0}. Метрики: итог, худшая просадка, обе половины, последние 3 года; шанс ликвидации за год при
  депозите D (старт каждый день, ликвидация — капитал D + PnL с даты старта ≤ 0.5% чистого номинала).
- Контроль (тот же размер, случайные шорты с тем же временем в рынке) — следующим шагом, если вариант пройдёт базу и
  «меньший постоянный размер сеток».
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

D = "/Users/alexeychechikov/code/bot7/research/grid_hedge_20261114/"
SC = 0.00068
MM = 0.005

z = np.load(D + "grid_hourly.npz")
T, C, EQ, Q, QE = z["t"], z["c"], z["eq"], z["q"], z["qe"]
n = len(T)
pos_of_t = {int(x): i for i, x in enumerate(T)}
ev = json.load(open(D + "ev.json", encoding="utf-8"))


def hour_idx(ts):
    """Событие системы с меткой t (закрытие часа) → индекс в почасовом ряду сеток (час, который начинается в t)."""
    return pos_of_t.get(int(ts))


def hedge_series(k: float, events=ev, tags=("под синей", "под жёлтой")):
    """Почасовой объём шорта (BTC, ≥0) и издержки по часам."""
    hq = np.zeros(n)
    cost = np.zeros(n)
    cur = 0.0
    changes = []
    for e in events:
        if e.get("side") != -1 or e.get("tag") not in tags:
            continue
        i = hour_idx(e["t"])
        if i is None:
            continue
        if e["kind"] == "вход":
            d = k * 0.5 * Q[i]
        elif e["kind"] == "добор":
            d = k * 0.5 * Q[i]
        elif e["kind"] == "выход":
            d = None
        else:
            continue
        changes.append((i, e["kind"], d))
    changes.sort(key=lambda x: x[0])
    j = 0
    for i in range(n):
        while j < len(changes) and changes[j][0] == i:
            _, kind, d = changes[j]
            if kind == "выход":
                cost[i] += cur * C[i] * SC
                cur = 0.0
            else:
                cur += d
                cost[i] += d * C[i] * SC
            j += 1
        hq[i] = cur
    return hq, cost


def overlay(k):
    hq, cost = hedge_series(k)
    # шорт hq[i] держится с цены C[i] до C[i+1]
    pnl = np.zeros(n)
    pnl[1:] = -hq[:-1] * (C[1:] - C[:-1])
    return EQ + np.cumsum(pnl) - np.cumsum(cost), hq


def dd(x):
    return float(np.min(x - np.maximum.accumulate(x)))


def liq_prob(total, net_notional, dep, horizon=365 * 24, step=24):
    starts = range(0, n - horizon, step)
    hit = 0
    for s in starts:
        w = total[s:s + horizon] - total[s] + dep
        if np.any(w <= MM * np.abs(net_notional[s:s + horizon])):
            hit += 1
    return hit / max(1, len(starts))


mid = n // 2
t3 = np.searchsorted(T, T[-1] - 3 * 365 * 86400)
print(f"часов {n}: {pd.to_datetime(T[0], unit='s'):%Y-%m-%d} … {pd.to_datetime(T[-1], unit='s'):%Y-%m-%d %H:%M}, "
      f"срез половин {pd.to_datetime(T[mid], unit='s'):%Y-%m-%d}, 3 года с {pd.to_datetime(T[t3], unit='s'):%Y-%m-%d}")
print(f"сетки без страховки: итог {EQ[-1]:+,.0f}, худшая просадка {dd(EQ):+,.0f}")

# худшие эпизоды просадки сеток (без перекрытия)
x = EQ.copy()
peaks = np.maximum.accumulate(x)
under = x - peaks
eps = []
used = np.zeros(n, bool)
for _ in range(10):
    m = np.where(used, 0, under)
    j = int(np.argmin(m))
    if m[j] >= -50:
        break
    p = int(np.flatnonzero(x[:j + 1] == peaks[j])[-1])
    r = j + int(np.argmax(x[j:] >= peaks[j])) if np.any(x[j:] >= peaks[j]) else n - 1
    used[p:r + 1] = True
    eps.append((p, j, r))
hq_1, _ = hedge_series(1.0)
short_on = hq_1 > 0
print("\nхудшие просадки сеток и система в это время (страховка k=1):")
tot1, _ = overlay(1.0)
for p, j, r in sorted(eps, key=lambda e: under[e[1]]):
    seg = slice(p, j + 1)
    print(f"  {pd.to_datetime(T[p], unit='s'):%Y-%m-%d} → дно {pd.to_datetime(T[j], unit='s'):%Y-%m-%d}: сетки "
          f"{EQ[j] - EQ[p]:+,.0f}$ (BTC {C[p]:,.0f}→{C[j]:,.0f}, {C[j] / C[p] - 1:+.0%}) · система в шорте "
          f"{short_on[seg].mean():.0%} часов · страховка k=1 за эпизод {(tot1[j] - tot1[p]) - (EQ[j] - EQ[p]):+,.0f}$")

print("\nвариант | итог | худшая просадка | 1-я половина | 2-я половина | 3 года | итог/просадка | в шорте")
res = {}
for k in (0.0, 0.25, 0.5, 1.0):
    tot, hq = overlay(k)
    res[k] = (tot, hq)
    a1, a2, a3 = tot[mid] - tot[0], tot[-1] - tot[mid], tot[-1] - tot[t3]
    d1, d2, d3 = dd(tot[:mid + 1]), dd(tot[mid:]), dd(tot[t3:])
    print(f"k={k:<4} | {tot[-1]:+9,.0f} | {dd(tot):+9,.0f} | {a1:+8,.0f} ({d1:+,.0f}) | {a2:+8,.0f} ({d2:+,.0f}) | "
          f"{a3:+8,.0f} ({d3:+,.0f}) | {tot[-1] / -dd(tot):.2f} | {(hq > 0).mean():.0%}")

print("\nшанс ликвидации за год (старт каждый день):")
for dep in (1500, 3000, 5000):
    row = []
    for k, (tot, hq) in res.items():
        net = Q * C - hq * C + 2500   # + ETH-сетка номиналом до $2 500 (грубо — её мешок не в капитале)
        row.append(f"k={k}: {liq_prob(tot, net, dep) * 100:.0f}%")
    print(f"  депозит ${dep:,}: " + " · ".join(row))
