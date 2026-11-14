"""Шаг 5 (14.11, «пока ждём GPT»): размер сеток × депозит × страховка — на исправленной механике (grid_hourly2.npz после
разбора ead2ca4). Оператору решать размер; здесь — что каждый вариант давал на истории.

ПРАВИЛА (до прогона): масштаб сеток s ∈ {1, 0.75, 0.65, 0.5, 0.35} (ордер и потолки × s — сетка линейна по размеру);
страховка «от всего» k ∈ {0, 1} от уже уменьшенной позиции; депозит $3 000 (≈ счёт сейчас + $2 000), $4 000, $5 000.
Метрики (overlay2.liq): шанс ликвидации за год (капитал ≤ 0.5% валового номинала), медиана года, худшие 10% лет —
вся история / старты 11.2022–11.2025 / старты 11.2023–11.2025."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import overlay2 as o2  # noqa: E402


def main():
    T, n = o2.T, o2.n
    lo3 = int(np.searchsorted(T, T[-1] - 4 * 365 * 86400))
    lo2 = int(np.searchsorted(T, T[-1] - 3 * 365 * 86400))
    print("сетки | страховка | депозит | вся история: ликв · медиана · худшие 10% | старты с 11.2022 | старты с 11.2023")
    for s in (1.0, 0.75, 0.65, 0.5, 0.35):
        for k in (0.0, 1.0):
            tot, hq = o2.total(k, "всё", s)
            gr = o2.gross(hq, s)
            for dep in (3000, 4000, 5000):
                cells = []
                for lo in (0, lo3, lo2):
                    p, med, p10, _ = o2.liq(tot, gr, dep, lo, n)
                    cells.append(f"{p * 100:3.0f}% · {med:+6,.0f} · {p10:+6,.0f}")
                print(f"×{s:<4g} | {'k=1' if k else ' — '} | ${dep:,} | " + " | ".join(cells), flush=True)


if __name__ == "__main__":
    main()
