"""Маршрут цены и план «вход на откате» (22.10, спор с оператором и разбор GPT: «что вероятнее следующим — 82 900 или
81 152», «план Copilot 81 050 / стоп 80 173 / цель 82 900, R:R 2.1 → нужно больше 32.2% попаданий»).

ПРАВИЛА ДО ПРОГОНА:
- Данные: BTC 1m Binance spot (копия frozen), старты — каждый час (закрытие минуты :59 → решение на следующей).
- Маршрут: от цены старта уровни +1.07% и −1.06% (как сейчас 82 900 / 81 152 от 82 025); что первым за 24 ч (high ≥
  верх / low ≤ низ); оба в одной минуте — считается «низ первым» (против лонга). Все старты и условие «после падения
  без отката»: цена ≥ 3.5% ниже максимума последних 12 ч (как утром 22.10). Условные события — не чаще раза в 24 ч.
- План Copilot в общем виде: лимит на −1.19% от цены старта (81 050 от 82 025), исполнен, если low ≤ лимита за 24 ч; затем
  стоп −1.08% и цель +2.28% от входа; ожидание до 7 суток, иначе выход по закрытию; одновременно — стоп. Расходы: вход
  мейкер 0.016%, цель мейкер 0.016%, стоп тейкер 0.048% + 0.02%. Безубыток до расходов — 1.08/(1.08+2.28) = 32.1%.
- Половины: условные события отдельно до и после середины окна (разрез по времени).
- Для случайного блуждания без сноса доля «верх первым» = расстояние до низа / сумма расстояний: 50% для маршрута и 32.1%
  для плана. Всё, что не отличается от этих чисел с 95% интервалом, — не преимущество.
Запуск: route_check.py --src=<копия frozen BTC>
"""
from __future__ import annotations

import math
import sys

import numpy as np
import pandas as pd

SRC = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--src=")),
           "/Users/alexeychechikov/code/bot7/backtests/frozen/BTCUSDT_1m_2y.csv")
UP, DN = 0.0107, 0.0106
LIM, SL, TP = 0.0119, 0.0108, 0.0228
DROP, LOOK = 0.035, 720
COST_TP, COST_SL = 0.00016 + 0.00016, 0.00016 + 0.00048 + 0.0002


def first_pass(h, l, i, up, dn, w):
    """(-1 низ первым / +1 верх первым / 0 никто), минута события."""
    hs, ls = h[i + 1:i + 1 + w], l[i + 1:i + 1 + w]
    a = np.flatnonzero(hs >= up)
    b = np.flatnonzero(ls <= dn)
    ta = a[0] if len(a) else None
    tb = b[0] if len(b) else None
    if ta is None and tb is None:
        return 0, i + len(hs)
    if ta is not None and tb is not None and ta == tb:
        return 2, i + 1 + ta              # 25.10 R5: оба в одной минуте — порядок неизвестен
    if tb is not None and (ta is None or tb < ta):
        return -1, i + 1 + tb
    return 1, i + 1 + ta


def ci(k, n):
    p = k / n
    z = 1.96 * math.sqrt(p * (1 - p) / n)
    return f"{p * 100:.1f}% [{(p - z) * 100:.1f}…{(p + z) * 100:.1f}] n={n}"


def main():
    d = pd.read_csv(SRC)
    h, l, c = (d[k].to_numpy(float) for k in ("high", "low", "close"))
    ts = d["ts"].to_numpy(np.int64)
    n = len(c)
    print(f"данные {pd.to_datetime(ts[0], unit='ms')} … {pd.to_datetime(ts[-1], unit='ms')} UTC, минут {n}")
    hmax = pd.Series(h).rolling(LOOK, min_periods=LOOK).max().to_numpy()
    starts = np.arange(LOOK + 59, n - 10080 - 1, 60)
    route = {"все": [0, 0, 0], "после падения": [0, 0, 0], "после падения 1-я пол": [0, 0, 0],
             "после падения 2-я пол": [0, 0, 0]}
    mid = n // 2
    plan = {k: [] for k in route}
    last_cond = -10**9
    for i in starts:
        cond = c[i] <= hmax[i] * (1 - DROP)
        keys = ["все"]
        if cond and i - last_cond >= 1440:
            keys += ["после падения", "после падения 1-я пол" if i < mid else "после падения 2-я пол"]
            last_cond = i
        r, _ = first_pass(h, l, i, c[i] * (1 + UP), c[i] * (1 - DN), 1440)
        for k in keys:
            if r != 2:
                route[k][{1: 0, -1: 1, 0: 2}[r]] += 1
        e = c[i] * (1 - LIM)
        f = np.flatnonzero(l[i + 1:i + 1441] <= e)
        if not len(f):
            continue
        j = i + 1 + f[0]
        r2, k2 = first_pass(h, l, j, e * (1 + TP), e * (1 - SL), 10080)
        if r2 == 2:
            continue                             # неоднозначно — вне доли
        if r2 == 1:
            res = TP - COST_TP
        elif r2 == -1:
            res = -SL - COST_SL
        else:
            res = c[min(k2, n - 1)] / e - 1 - COST_SL
        for k in keys:
            plan[k].append((r2, res))
    print(f"\nМаршрут за 24 ч: +{UP * 100:.2f}% раньше −{DN * 100:.2f}%? (блуждание без сноса: {DN / (UP + DN) * 100:.1f}%)")
    for k, (u, dn, none) in route.items():
        tot = u + dn
        if tot:
            print(f"  {k:<22}: верх первым {ci(u, tot)}; ни один за 24 ч — {none}")
    print(f"\nПлан: лимит −{LIM * 100:.2f}%, стоп −{SL * 100:.2f}%, цель +{TP * 100:.2f}% (безубыток до расходов "
          f"{SL / (SL + TP) * 100:.1f}%)")
    for k, rows in plan.items():
        if not rows:
            continue
        r = np.array([x[0] for x in rows])
        res = np.array([x[1] for x in rows])
        dec = r != 0
        m, s = res.mean(), res.std(ddof=1) / math.sqrt(len(res))
        print(f"  {k:<22}: входов {len(rows)}; цель раньше стопа {ci(int((r == 1).sum()), int(dec.sum()))}; "
              f"по времени {int((r == 0).sum())}; в среднем на сделку {m * 100:+.3f}% [{(m - 1.96 * s) * 100:+.3f}…"
              f"{(m + 1.96 * s) * 100:+.3f}] после расходов")


if __name__ == "__main__":
    main()
