"""Шаг 9 (14.11, «что ещё, пока ждём»): ТОРМОЗ — шорт на весь объём лонгов, когда мешок сеток глубоко ниже их
средней цены входа, независимо от сигнала системы. Цель — обвалы, где система не шортила (05.2021, 08.2024) и
ликвидация. Механизм новый (не размер, не плотность сетки).

ПРАВИЛА (записаны до прогона):
- глубина мешка = 1 − стоимость лонгов BTC+ETH по цене часа / их себестоимость (grid_hourly2.npz, исправленная механика);
- тормоз включается на закрытии часа, когда глубина ≥ ON; шорт BTC = k_b × стоимость лонгов / цена BTC (k_b = 1 —
  счёт нейтрален), объём фиксирован до выключения; выключается, когда глубина ≤ ON / 2; издержка 0.068%/сторону;
- ON ∈ {8, 10, 12, 15}% — все четыре печатаются (соседние ячейки, ворота плоской поверхности);
- варианты: без страховок; только тормоз; страховка системы A (k=1); A + тормоз; D + тормоз;
- сетки ×1 и ×0.5; депозит $3 200; ликвидация за год (капитал ≤ 0.5% валового номинала, лонги + все шорты),
  медиана года, худшие 10% лет — вся история / старты с 11.2022 / с 11.2023; итог и просадка.
- Планка CLAUDE.md: политика риска должна бить постоянный меньший размер при том же капитале.
  Проходит, если при сетках ×1 с тормозом ликвидаций не больше, чем у сеток ×0.65 без тормоза, а медиана года выше."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import hedge_tags as ht  # noqa: E402
import overlay2 as o2  # noqa: E402

T, n, CB, CE, QB, QE, EQ = o2.T, o2.n, o2.CB, o2.CE, o2.QB, o2.QE, o2.EQ
z = np.load(HERE / "grid_hourly2.npz")
COST = z["qeb"] + z["qee"]
VAL = QB * CB + QE * CE
DEPTH = np.where(COST > 0, 1 - VAL / np.maximum(COST, 1e-9), 0.0)
SC = 0.00068
TR_A = ht.trades(("под синей", "под жёлтой"), False)
TR_D = ht.trades(("под синей", "под жёлтой"), True)


def brake(on, s=1.0, kb=1.0):
    hq = np.zeros(n)
    cost = np.zeros(n)
    cur, active = 0.0, False
    for i in range(n):
        if not active and DEPTH[i] >= on and VAL[i] > 0:
            cur = kb * s * VAL[i] / CB[i]
            cost[i] += cur * CB[i] * SC
            active = True
        elif active and DEPTH[i] <= on / 2:
            cost[i] += cur * CB[i] * SC
            cur, active = 0.0, False
        hq[i] = cur
    pnl = np.zeros(n)
    pnl[1:] = -hq[:-1] * (CB[1:] - CB[:-1])
    return np.cumsum(pnl) - np.cumsum(cost), hq


def system(tr, s):
    o2.TR = tr
    tot, hq = o2.total(1.0, "всё", s)
    return tot - s * EQ, hq                                  # только страховка


def main():
    lo3 = int(np.searchsorted(T, T[-1] - 4 * 365 * 86400))
    lo2 = int(np.searchsorted(T, T[-1] - 3 * 365 * 86400))
    dep = 3200
    print(f"глубина мешка: ≥8% — {np.mean(DEPTH >= 0.08):.1%} часов, ≥10% — {np.mean(DEPTH >= 0.10):.1%}, ≥15% — {np.mean(DEPTH >= 0.15):.1%}")
    print("вариант | итог | просадка | 2 года | ликвидация (вся / с 11.2022 / с 11.2023) · медиана года · худшие 10%")
    for s in (1.0, 0.65, 0.5):
        sysA, hqA = system(TR_A, s)
        sysD, hqD = system(TR_D, s)
        rows = [("без страховок", np.zeros(n), np.zeros(n)), ("A", sysA, hqA), ("D", sysD, hqD)]
        for on in (0.08, 0.10, 0.12, 0.15):
            bp, bq = brake(on, s)
            rows += [(f"тормоз {on:.0%}", bp, bq), (f"A + тормоз {on:.0%}", sysA + bp, hqA + bq), (f"D + тормоз {on:.0%}", sysD + bp, hqD + bq)]
        print(f"\nсетки ×{s:g}, депозит ${dep:,}:")
        for name, hp, hq in rows:
            tot = s * EQ + hp
            gr = s * VAL + hq * CB
            cells = [o2.liq(tot, gr, dep, lo, n) for lo in (0, lo3, lo2)]
            print(f"  {name:18s} | {tot[-1]:+8,.0f} | {o2.dd(tot):+7,.0f} | {tot[-1] - tot[o2.y2]:+7,.0f} | "
                  + " / ".join(f"{c[0] * 100:3.0f}%" for c in cells) + f" · {cells[0][1]:+6,.0f} · {cells[0][2]:+6,.0f}", flush=True)


if __name__ == "__main__":
    main()
