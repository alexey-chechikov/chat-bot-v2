"""Вход в уже идущий шорт системы с опозданием (14.11: шорт системы с 12.11 идёт, исполнитель его пропустил как старый
сигнал). Вопрос: что даёт шорт от часа t внутри эпизода до выхода системы — против входа на сигнале и против шорта
в случайный час с той же длительностью до выхода.

ПРАВИЛА (до прогона): эпизоды шорта системы (под синей / под жёлтой, ev.json), цены — закрытия часов Binance
(grid_hourly2.npz, 2018–11.2026); шорт равным номиналом $1000 от закрытия часа входа до закрытия часа выхода,
0.068%/сторону. «Опоздание» L ∈ {4, 12, 24, 48, 96 ч}: только эпизоды, ещё открытые через L часов. Плюс разрез «на
момент опоздания эпизод уже в плюсе ≥ 3%» (как сейчас: 71 710 → 68 250, −4.8%). Контроль: шорт с того же часа на
случайный другой час той же длины — 999 перестановок времени старта, ранг (k+1)/(n+1)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
NPZ = next(p for p in (HERE / "grid_hourly2.npz", Path("/Users/alexeychechikov/code/bot7/research/grid_hedge_20261114/grid_hourly2.npz"))
           if p.exists())
SC = 0.00068
z = np.load(NPZ)
T, C = z["t"], z["cb"]
n = len(T)
class _Rows:
    """Событие с меткой t (закрытие часа) → строка часа, закончившегося не позже t; пропуск ряда > 3 ч — None
    (разбор ead2ca4: точное равенство меток теряло события на пропусках, метка начала часа брала будущий час)."""

    def __init__(self, T):
        self.T = T

    def get(self, t, default=None):
        i = int(np.searchsorted(self.T, int(t), side="right")) - 1
        return i if i >= 0 and int(t) - int(self.T[i]) <= 3 * 3600 else default


pos = _Rows(T)
ev = json.load(open(HERE / "ev.json", encoding="utf-8"))
eps, cur = [], None
for e in ev:
    if e.get("side") != -1 or e.get("tag") not in ("под синей", "под жёлтой"):
        continue
    i = pos.get(int(e["t"]))
    if i is None:
        continue
    if e["kind"] == "вход":
        cur = i
    elif e["kind"] == "выход" and cur is not None:
        eps.append((cur, i))
        cur = None
eps = np.array(eps)
y3 = int(np.searchsorted(T, T[-1] - 3 * 365 * 86400))
rng = np.random.default_rng(20261114)


def short_ret(a, x):
    return (C[a] / C[x] - 1) - 2 * SC          # шорт от a до x, доля номинала (как $ на $1000 / 1000)


print(f"эпизодов шорта {len(eps)}; длительность медиана {np.median(eps[:, 1] - eps[:, 0]):.0f} ч")
print("опоздание | эпизодов | вход на сигнале $/1000 | вход с опозданием $/1000 | случайный старт $/1000 | ранг | из них в плюсе ≥3%: n, $/1000")
for L in (0, 4, 12, 24, 48, 96):
    for lab, lo in (("вся история", 0), ("с 11.2023", y3)):
        sel = [(a, x) for a, x in eps if x - a > L and a >= lo]
        if not sel:
            continue
        on = np.mean([short_ret(a, x) for a, x in sel]) * 1000
        late = np.array([short_ret(a + L, x) for a, x in sel]) * 1000
        lens = np.array([x - a - L for a, x in sel])
        ctrl = []
        for _ in range(999):
            st = rng.integers(0, n - lens.max() - 1, len(sel))
            ctrl.append(np.mean([short_ret(s, s + d) for s, d in zip(st, lens)]) * 1000)
        ctrl = np.array(ctrl)
        rank = (np.sum(ctrl >= late.mean()) + 1) / 1000
        inplus = [(a, x) for a, x in sel if C[a] / C[a + L] - 1 >= 0.03]
        ip = np.mean([short_ret(a + L, x) for a, x in inplus]) * 1000 if inplus else float("nan")
        print(f"{L:4d} ч ({lab:11s}) | {len(sel):4d} | {on:+7.1f} | {late.mean():+7.1f} | {np.median(ctrl):+7.1f} | {rank:.3f} | "
              f"{len(inplus)}, {ip:+.1f}")
