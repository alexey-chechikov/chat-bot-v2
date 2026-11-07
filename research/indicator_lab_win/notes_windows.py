"""Записки оператора 07.11 по шести новым окнам: что на самом деле было с линиями в названные им даты. График Bybit. Запуск: python -X utf8 notes_windows.py [окно]
Печатает смену состояний на закрытии 4ч: порядок цветных, куда смотрят за сутки, закрепления над и под G, Y, R, B, сделки базы R."""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import lab_core as lc

WIN = {"1": ("2023-05-15", "2023-06-19"), "2": ("2023-12-18", "2024-01-29"), "3": ("2024-02-12", "2024-03-18"), "4": ("2024-03-14", "2024-05-05"), "5": ("2024-07-30", "2024-09-12"), "6": ("2025-05-19", "2025-07-14")}


def main():
    S = lc.load("BybitBTC")
    k4 = S.h4["known"]
    c = S.h4["c"]
    G, Y, R, B = S.line4(lc.G), S.line4(lc.Y), S.line4(lc.R), S.line4(lc.B)
    rG, rY, rR, rB = S.run4(lc.G), S.run4(lc.Y), S.run4(lc.R), S.run4(lc.B)
    base = lc.run(S)
    pick = sys.argv[1:] or list(WIN)
    for w in pick:
        a, z = lc.T(WIN[w][0]), lc.T(WIN[w][1])
        print(f"\n===== окно {w}: {WIN[w][0]} — {WIN[w][1]}")
        prev = None
        for j in np.flatnonzero((k4 >= a) & (k4 < z)):
            order = "G>Y>R" if G[j] > Y[j] > R[j] else "G<Y<R" if G[j] < Y[j] < R[j] else ("Y>G" if Y[j] > G[j] else "G>Y") + ("," + ("Y<R" if Y[j] < R[j] else "Y>R"))
            up = sum(x[j] > x[j - 6] for x in (G, Y, R))
            look = "вверх" if up == 3 else "вниз" if up == 0 else f"смеш{up}"
            ev = []
            for nm, r in (("G", rG), ("Y", rY), ("R", rR), ("B", rB)):
                if r[j] == 2:
                    ev.append("над" + nm)
                if r[j] == -2:
                    ev.append("под" + nm)
            st = (order, look)
            if ev or st != prev:
                d = pd.Timestamp(int(k4[j]), unit="s").strftime("%d.%m %H")
                print(f"{d} c={c[j]:.0f} G={G[j]:.0f} Y={Y[j]:.0f} R={R[j]:.0f} B={B[j]:.0f} {order} {look} {' '.join(ev)}")
            prev = st
        print("-- сделки базы R в окне")
        for x in base:
            if a <= S.t[x[0]] < z:
                n = x[4] * (x[3] / x[2] - 1) * 100 - 0.136
                print(pd.Timestamp(int(S.t[x[0]]), unit="s").strftime("%d.%m %H"), pd.Timestamp(int(S.t[x[1]]), unit="s").strftime("%d.%m %H"), "L" if x[4] == 1 else "S", round(x[2]), round(x[3]), round(n, 1))


if __name__ == "__main__":
    main()
