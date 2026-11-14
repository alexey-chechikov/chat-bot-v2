"""Планка CLAUDE.md: политика риска должна бить постоянный МЕНЬШИЙ размер при том же капитале.
Сетки масштаба s (итог и позиция ×s — сетка линейна по размеру ордера, потолки тоже ×s) без страховки против s=1 и
s=0.75 со страховкой системы k=1. Для депозитов $1 500 / $3 000 / $5 000: шанс ликвидации за год (старт каждый день),
медианный и худший годовой итог; отдельно вся история и последние 3 года."""
from __future__ import annotations

import json
import sys

import numpy as np

sys.path.insert(0, "/Users/alexeychechikov/code/bot7/research/grid_hedge_20261114")
import control as ct  # noqa: E402

MM = 0.005
H = 365 * 24
tr = ct.trades_of("ev.json", ("под синей", "под жёлтой"))
n, C, EQ, Q, T = ct.n, ct.C, ct.EQ, ct.Q, ct.T


def hedge_q(k):
    hq = np.zeros(n + 1)
    for a, b, x in tr:
        for i0 in (a, b):
            if i0 is not None:
                hq[i0] += k * 0.5 * Q[i0]
                hq[x] -= k * 0.5 * Q[i0]
    return np.cumsum(hq)[:n]


def year_stats(total, net, dep, lo):
    hits, rets = 0, []
    starts = range(lo, n - H, 24)
    for s in starts:
        w = total[s:s + H] - total[s] + dep
        if np.any(w <= MM * np.abs(net[s:s + H])):
            hits += 1
            rets.append(-dep)
        else:
            rets.append(total[s + H - 1] - total[s])
    r = np.array(rets)
    return hits / len(r), float(np.median(r)), float(np.percentile(r, 10)), len(r)


variants = []
for s in (1.0, 0.75, 0.5, 0.35):
    variants.append((f"сетки ×{s:g} без страховки", s, 0.0))
for s in (1.0, 0.75, 0.5):
    variants.append((f"сетки ×{s:g} + шорт системы k=1", s, 1.0))
lo3 = int(np.searchsorted(T, T[-1] - 4 * 365 * 86400))      # старты, чьи годовые окна лежат в последних ~3 годах
for label, lo in (("вся история 2018–2026", 0), ("последние 3 года (старты с 11.2022)", lo3)):
    print(f"\n=== {label} ===")
    for dep in (1500, 3000, 5000):
        print(f"депозит ${dep:,}: шанс ликвидации за год · медиана года · худшие 10% лет")
        for name, s, k in variants:
            tot, _ = ct.total_of(tr, k) if k else (EQ.copy(), 0)
            # масштаб: сетка ×s, страховка — от позиции уже уменьшенной сетки (тоже ×s)
            total = tot * s
            net = s * (Q * C - hedge_q(k) * C) + 2500 * s
            p, med, p10, cnt = year_stats(total, net, dep, lo)
            print(f"   {name:34s} {p * 100:4.0f}% · {med:+8,.0f}$ · {p10:+8,.0f}$  (стартов {cnt})")
