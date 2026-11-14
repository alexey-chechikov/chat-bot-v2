"""Шаг 7 (14.11): устойчивость варианта D («держать страховку до следующего входа системы в лонг») — найден среди 4
вариантов hedge_tags.py, поэтому проверка на разрезах, которые при выборе не смотрелись:
- по годам: прибавка итога и изменение худшей просадки года против A (оба тега, выход по выходу системы);
- обе половины истории;
- шанс ликвидации за год: сетки ×1 / ×0.75 / ×0.65 / ×0.5, депозит $3 000 / $4 000 / $5 000, A против D;
- фандинг шорта (D держит шорт 49% часов, шорт получает фандинг) — отдельной строкой.
Правило выбора записано ДО прогона: D лучше A, только если прибавка итога ≥ A в обеих половинах ИЛИ просадка лучше A в
обеих половинах, и ликвидаций не больше A ни в одной ячейке."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import hedge_tags as ht  # noqa: E402
import hedge_variants as hv  # noqa: E402
import overlay2 as o2  # noqa: E402

T, n, EQ = o2.T, o2.n, o2.EQ
TR_A = ht.trades(("под синей", "под жёлтой"), False)
TR_D = ht.trades(("под синей", "под жёлтой"), True)


def run(tr, s=1.0):
    o2.TR = tr
    return o2.total(1.0, "всё", s)


def main():
    a, hqa = run(TR_A)
    d, hqd = run(TR_D)
    mid = o2.mid
    print("половины (прибавка итога к сеткам / просадка всего счёта):")
    for lab, lo, hi in (("1-я", 0, mid), ("2-я", mid, n - 1)):
        for nm, tot in (("A", a), ("D", d)):
            print(f"  {lab} {nm}: прибавка {(tot[hi] - tot[lo]) - (EQ[hi] - EQ[lo]):+8,.0f} · просадка {o2.dd(tot[lo:hi + 1]):+8,.0f} "
                  f"(сетки {o2.dd(EQ[lo:hi + 1]):+,.0f})")
    print("\nпо годам: прибавка A / D · худшая просадка года: сетки / A / D")
    years = pd.to_datetime(T, unit="s").year
    for y in sorted(set(years)):
        m = np.flatnonzero(years == y)
        lo, hi = m[0], m[-1]
        print(f"  {y}: {(a[hi] - a[lo]) - (EQ[hi] - EQ[lo]):+7,.0f} / {(d[hi] - d[lo]) - (EQ[hi] - EQ[lo]):+7,.0f} · "
              f"{o2.dd(EQ[lo:hi + 1]):+7,.0f} / {o2.dd(a[lo:hi + 1]):+7,.0f} / {o2.dd(d[lo:hi + 1]):+7,.0f}")
    # фандинг шорта по часам (hedge_variants.FR — ставка, отнесённая к часу расчёта; ставка > 0 — шорт получает)
    fa = float(np.sum(hqa * o2.CB * hv.FR))
    fd = float(np.sum(hqd * o2.CB * hv.FR))
    print(f"\nфандинг шорта за всю историю: A {fa:+,.0f}$, D {fd:+,.0f}$ (в итоги выше не входит)")
    lo3 = int(np.searchsorted(T, T[-1] - 4 * 365 * 86400))
    lo2 = int(np.searchsorted(T, T[-1] - 3 * 365 * 86400))
    print("\nликвидация за год · медиана · худшие 10% (вся история / старты с 11.2022 / с 11.2023)")
    for s in (1.0, 0.75, 0.65, 0.5):
        for dep in (3000, 4000, 5000):
            line = []
            for nm, tr in (("A", TR_A), ("D", TR_D)):
                tot, hq = run(tr, s)
                gr = o2.gross(hq, s)
                cells = [o2.liq(tot, gr, dep, lo, n) for lo in (0, lo3, lo2)]
                line.append(f"{nm}: " + " / ".join(f"{c[0] * 100:.0f}%" for c in cells) + f" · {cells[0][1]:+,.0f} · {cells[0][2]:+,.0f}")
            print(f"  ×{s:<4g} ${dep:,}: " + " | ".join(line), flush=True)


if __name__ == "__main__":
    main()
