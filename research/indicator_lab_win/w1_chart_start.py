"""Экран оператора 07.11: на 4ч Bybit 144 сделки −9.3 (лонг −6.4, шорт −2.9), на 1ч 120 сделок +1.1 (лонг −7.5, шорт +8.6). Какое начало часового графика даёт второе число.
Линии 4ч по всей истории, автомат стартует с первой свечи графика. Запуск: python -X utf8 w1_chart_start.py"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lab_core as lc
import pine_mirror_plus as pm

COST = 0.068


def closed_since(S, start, frm):
    S.i0 = int(np.searchsorted(S.t, start))
    legs = [x for x in pm.run(S, plus=False) if S.t[x[0]] >= frm]
    n = np.array([x[4] * (x[3] / x[2] - 1) * 100 - COST - COST * x[3] / x[2] for x in legs])
    s = np.array([x[4] for x in legs])
    return len(n), round(float(n.sum()), 1), round(float(n[s == 1].sum()), 1), round(float(n[s == -1].sum()), 1)


def main():
    frm = lc.T("2025-01-01")
    S = lc.load("BybitBTC")
    print("с начала всей истории:", closed_since(S, int(S.t[0]), frm))
    last = int(S.t[-1])
    rows = []
    for st in pd.date_range("2025-02-15", "2025-05-15", freq="4h"):
        r = closed_since(S, int(st.timestamp()), frm)
        rows.append({"начало": st.strftime("%d.%m.%Y %H"), "сделок": r[0], "итог": r[1], "лонг": r[2], "шорт": r[3], "часов_до_конца": (last - int(st.timestamp())) // 3600})
    d = pd.DataFrame(rows)
    d["откл"] = (d["итог"] - 1.1).abs() + (d["лонг"] + 7.5).abs() + (d["шорт"] - 8.6).abs() + (d["сделок"] - 120).abs()
    print(d.sort_values("откл").head(6).drop(columns="откл").to_string(index=False))
    print("по сделкам 118-122:", d[d["сделок"].between(118, 122)][["начало", "сделок", "итог", "лонг", "шорт"]].drop_duplicates(["сделок", "итог"]).head(10).to_string(index=False))


if __name__ == "__main__":
    main()
