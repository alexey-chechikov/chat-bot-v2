"""Шаг 10 (14.11): «держать шорт системы до входа в лонг» (D) как самостоятельная сделка, без сеток — равным
номиналом $1000 на эпизод (вход 0.5 + добор 0.5 как у системы; цены — закрытия часов Binance, grid_hourly2.npz),
0.068%/сторону. Сравнение по годам с A (выход системы из шорта) и с хвостом «от выхода до лонга» отдельно.
Контроль хвоста: шорт той же длины со случайного часа (999), ранг (k+1)/(n+1)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import hedge_tags as ht  # noqa: E402
import overlay2 as o2  # noqa: E402

T, C, n = o2.T, o2.CB, o2.n
SC = 0.00068


def pnl(a, b, x):
    legs = [a] + ([b] if b is not None and b < x else [])
    return sum(500 * ((C[i] - C[x]) / C[i] - 2 * SC) for i in legs)


def main():
    A = ht.trades(("под синей", "под жёлтой"), False)
    D = ht.trades(("под синей", "под жёлтой"), True)
    years = pd.to_datetime(T, unit="s").year
    ra = pd.Series({T[a]: pnl(a, b, x) for a, b, x in A})
    rd = pd.Series({T[a]: pnl(a, b, x) for a, b, x in D})
    # хвост: от выхода A до выхода D (там, где D держит дольше) — отдельная «сделка»
    tails = []
    da = {a: x for a, _, x in A}
    for a, b, x in D:
        xa = da.get(a)
        if xa is not None and x > xa + 1:
            tails.append((xa, x))
    rt = np.array([500 * 2 * ((C[s] - C[e]) / C[s] - 2 * SC) for s, e in tails])
    print(f"A: эпизодов {len(A)}, итог ${ra.sum():+,.0f} на $1000; D: эпизодов {len(D)}, итог ${rd.sum():+,.0f}")
    print(f"хвост «выход системы → вход в лонг»: {len(tails)} отрезков, итог ${rt.sum():+,.0f}, средний {rt.mean():+.1f}$, "
          f"плюсовых {np.mean(rt > 0):.0%}")
    rng = np.random.default_rng(20261114)
    lens = np.array([e - s for s, e in tails])
    ctrl = []
    for _ in range(999):
        st = rng.integers(0, n - lens.max() - 1, len(lens))
        ctrl.append(sum(1000 * ((C[s] - C[s + d]) / C[s] - 2 * SC) for s, d in zip(st, lens)))
    ctrl = np.array(ctrl)
    print(f"контроль хвоста (случайные отрезки той же длины): медиана ${np.median(ctrl):+,.0f}, ранг {(np.sum(ctrl >= rt.sum()) + 1) / 1000:.3f}")
    print("\nгод | A | D | хвост")
    ya = ra.groupby(pd.to_datetime(ra.index, unit="s").year).sum()
    yd = rd.groupby(pd.to_datetime(rd.index, unit="s").year).sum()
    yt = pd.Series(rt, index=[pd.to_datetime(T[s], unit="s").year for s, _ in tails]).groupby(level=0).sum()
    for y in sorted(set(years)):
        print(f"{y} | {ya.get(y, 0):+7,.0f} | {yd.get(y, 0):+7,.0f} | {yt.get(y, 0):+7,.0f}")


if __name__ == "__main__":
    main()
