"""Шаг 11 (14.11): размер сеток × A/D при депозите $3 000 / $3 200 / $4 000 — на модели сеток, выбранной переменной
GRID_NPZ (grid_hourly2.npz — постоянный $ на ордер; grid_hourly2_fixed.npz — объём в монете, как конфиг). Вопрос: даёт
ли D держать сетки ×1 без урезания при том же риске ликвидации, что A ×0.5."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import hedge_tags as ht  # noqa: E402
import overlay2 as o2  # noqa: E402


def main():
    T, n = o2.T, o2.n
    lo3 = int(np.searchsorted(T, T[-1] - 4 * 365 * 86400))
    lo2 = int(np.searchsorted(T, T[-1] - 3 * 365 * 86400))
    print("модель:", os.environ.get("GRID_NPZ", "grid_hourly2.npz"))
    print("сетки | вариант | депозит | ликвидация (вся / с 11.2022 / с 11.2023) · медиана года · худшие 10% лет")
    trs = {"A": ht.trades(("под синей", "под жёлтой"), False), "D": ht.trades(("под синей", "под жёлтой"), True)}
    for s in (1.0, 0.75, 0.65, 0.5):
        for name, tr in trs.items():
            o2.TR = tr
            tot, hq = o2.total(1.0, "всё", s)
            gr = o2.gross(hq, s)
            for dep in (3000, 3200, 4000):
                cells = [o2.liq(tot, gr, dep, lo, n) for lo in (0, lo3, lo2)]
                print(f"×{s:<4g} | {name} | ${dep:,} | " + " / ".join(f"{c[0] * 100:3.0f}%" for c in cells)
                      + f" · {cells[0][1]:+6,.0f} · {cells[0][2]:+6,.0f}", flush=True)


if __name__ == "__main__":
    main()
