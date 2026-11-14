"""Контроль страховки: те же шорт-сделки системы (вход, добор, выход — их длины и порядок), сдвинутые по времени на
случайный круговой сдвиг (≥30 сут), размер — тем же правилом от позиции сеток в час входа/добора. 999 сдвигов.
Ранг = (k+1)/(n+1) — доля сдвигов, где улучшение не хуже настоящего. Метрики — улучшение итога, просадки и итога/
просадки против сеток без страховки: вся история, 2-я половина, последние 3 года.
Плюс «случайные шорты, тот же процент времени в шорте» — это и есть сдвиг (время в рынке сохраняется)."""
from __future__ import annotations

import json

import numpy as np

D = "/Users/alexeychechikov/code/bot7/research/grid_hedge_20261114/"
SC = 0.00068
z = np.load(D + "grid_hourly.npz")
T, C, EQ, Q = z["t"], z["c"], z["eq"], z["q"]
n = len(T)
pos_of_t = {int(x): i for i, x in enumerate(T)}
mid = n // 2
t3 = int(np.searchsorted(T, T[-1] - 3 * 365 * 86400))


def trades_of(path, tags):
    ev = json.load(open(D + path, encoding="utf-8"))
    out, cur = [], None
    for e in ev:
        if e.get("side") != -1 or e.get("tag") not in tags:
            continue
        i = pos_of_t.get(int(e["t"]))
        if i is None:
            continue
        if e["kind"] == "вход":
            cur = [i, None, None]
        elif e["kind"] == "добор" and cur:
            cur[1] = i
        elif e["kind"] == "выход" and cur:
            cur[2] = i
            out.append(tuple(cur))
            cur = None
    if cur:                                                     # открытая сейчас — до конца ряда
        out.append((cur[0], cur[1], n - 1))
    return out


def total_of(trades, k, shift=0):
    hq = np.zeros(n + 1)
    cost = np.zeros(n)
    for a, b, x in trades:
        a2, x2 = a + shift, x + shift
        b2 = None if b is None else b + shift
        if shift:
            a2, x2 = a2 % n, x2 % n
            b2 = None if b2 is None else b2 % n
            if x2 <= a2 or (b2 is not None and not a2 <= b2 <= x2):
                continue                                         # сделка перешла через конец ряда — выброшена
        for i0, part in ((a2, 0.5), (b2, 0.5)):
            if i0 is None:
                continue
            q = k * part * Q[i0]
            hq[i0] += q
            hq[x2] -= q
            cost[i0] += q * C[i0] * SC
            cost[x2] += q * C[x2] * SC
    hq = np.cumsum(hq)[:n]
    pnl = np.zeros(n)
    pnl[1:] = -hq[:-1] * (C[1:] - C[:-1])
    return EQ + np.cumsum(pnl) - np.cumsum(cost), (hq > 1e-12).mean()


def dd(x):
    return float(np.min(x - np.maximum.accumulate(x)))


def metrics(tot):
    return {"итог": tot[-1] - EQ[-1], "просадка": dd(tot) - dd(EQ),
            "2-я": (tot[-1] - tot[mid]) - (EQ[-1] - EQ[mid]), "2-я просадка": dd(tot[mid:]) - dd(EQ[mid:]),
            "3 года": (tot[-1] - tot[t3]) - (EQ[-1] - EQ[t3]), "3 года просадка": dd(tot[t3:]) - dd(EQ[t3:])}


rng = np.random.default_rng(20261114)
shifts = rng.integers(30 * 24, n - 30 * 24, 999)
for label, path, tags in (("система (под синей + под жёлтой)", "ev.json", ("под синей", "под жёлтой")),
                          ("только под синей", "ev.json", ("под синей",)),
                          ("432 шорты", "ev432.json", ("432",)),
                          ("система + 432", None, None)):
    if path:
        tr = trades_of(path, tags)
    else:
        tr = trades_of("ev.json", ("под синей", "под жёлтой")) + trades_of("ev432.json", ("432",))
    for k in (0.5, 1.0):
        real, share = total_of(tr, k)
        m = metrics(real)
        ctrl = [metrics(total_of(tr, k, int(s))[0]) for s in shifts]
        print(f"\n{label}, k={k}: сделок {len(tr)}, в шорте {share:.0%} часов")
        for key, v in m.items():
            arr = np.array([c[key] for c in ctrl])
            rank = (np.sum(arr >= v) + 1) / (len(arr) + 1)
            print(f"   {key:16s} {v:+9,.0f}$ · случайные: медиана {np.median(arr):+9,.0f}$, 90% {np.percentile(arr, 90):+9,.0f}$"
                  f" · ранг {rank:.3f}")
