"""Как часто цена проходит X% вверх (лонговый тейк) быстрее, чем цикл успевает поставить спящий тейк.
Минутки Binance (frozen 2y). Событие: от закрытия минуты t максимум следующих K минут ≥ close·(1+X%).
«Промах» — то же, но закрытие K-й минуты уже ниже уровня (фитиль: тейк не успел бы и цена ушла назад).
Считаем по НЕперекрывающимся событиям (после события пропуск K минут)."""
import sys

import numpy as np
import pandas as pd

for path in sys.argv[1:]:
    d = pd.read_csv(path, usecols=["ts", "high", "close"]) if "ts" in open(path).readline() else pd.read_csv(path)
    cols = {c.lower(): c for c in d.columns}
    h = d[cols.get("high", "high")].to_numpy(float)
    c = d[cols.get("close", "close")].to_numpy(float)
    n = len(c)
    days = n / 1440
    print(f"{path.split('/')[-1]}: минут {n}, суток {days:.0f}")
    for K in (1, 2, 5):
        mx = np.full(n, -np.inf)
        for k in range(1, K + 1):
            mx[:-k] = np.maximum(mx[:-k], h[k:])
        last = np.full(n, np.nan)
        last[:-K] = c[K:]
        up = (mx / c - 1) * 100
        row = []
        for X in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0):
            hit = np.where(up >= X)[0]
            ev = miss = 0
            nxt = -1
            for i in hit:
                if i < nxt:
                    continue
                ev += 1
                if last[i] < c[i] * (1 + X / 100):
                    miss += 1
                nxt = i + K
            row.append(f"{X}%: {ev} ({ev / days * 365:.1f}/год), фитиль {miss}")
        print(f"  за {K} мин: " + " · ".join(row))
