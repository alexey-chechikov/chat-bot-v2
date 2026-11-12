"""Часовая сезонность BTC (Quantpedia: рост в 22:00–23:00 UTC, слабее всего 03–04) на Binance spot по периодам.
Правило Quantpedia: купить в 21:00, продать в 23:00 UTC. Итог за день после издержек: мейкер+мейкер 0.032%,
мейкер+тейкер 0.064%, тейкер+тейкер 0.096%. Плюс средний ход каждого часа и t-статистика."""
import sys

import numpy as np

sys.path.insert(0, "/Users/alexeychechikov/code/bot7")
from services.btc_signals import run as rn  # noqa: E402

R = rn.compute()
a = R["a"]
t, o, c = np.asarray(a["t"], np.int64), a["o"], a["c"]
ret = c / o - 1                                   # ход часа (закрытие t = конец часа)
hour = ((t - 3600) // 3600) % 24                  # час начала
yr = (t // 86400 // 365.25 + 1970).astype(int)
for lab, m in (("2018–2022", (yr >= 2018) & (yr <= 2022)), ("2023–2024", (yr >= 2023) & (yr <= 2024)), ("2025–2026", yr >= 2025),
               ("последние 2 года", t >= t[-1] - 2 * 365.25 * 86400)):
    x = ret[m]
    hh = hour[m]
    by = [(h_, x[hh == h_].mean() * 100, x[hh == h_].mean() / (x[hh == h_].std() / np.sqrt((hh == h_).sum()))) for h_ in range(24)]
    top = sorted(by, key=lambda z: -z[1])[:3]
    day = x[(hh == 21) | (hh == 22)]
    per_day = day.reshape(-1)  # часы 21 и 22 по отдельности — для суммы за день берём оба
    g = (x[hh == 21].mean() + x[hh == 22].mean()) * 100
    n_days = int((hh == 21).sum())
    print(f"{lab}: часы 21+22 UTC (21:00→23:00) в среднем {g:+.3f}% за день, t часа 21 {by[21][2]:+.1f}, часа 22 {by[22][2]:+.1f}; "
          f"после издержек 0.032% {g - 0.032:+.3f}%, 0.064% {g - 0.064:+.3f}%, 0.096% {g - 0.096:+.3f}%; дней {n_days}; "
          f"лучшие часы: " + ", ".join(f"{h_:02d}:00 {mu:+.3f}% (t {tt:+.1f})" for h_, mu, tt in top))
