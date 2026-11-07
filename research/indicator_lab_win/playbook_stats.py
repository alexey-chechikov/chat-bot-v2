"""Цифры для описания тренда, флета и поведения в сделке. Всё известно в реальном времени: пик сделки на данный час, серия убытков, волатильность.
1. Сделка дала пик X ATR: как часто заканчивается в плюс. 2. К часу H пик меньше X ATR. 3. После k убытков подряд. 4. Предсказуем ли флет: AUC будущей эффективности за 10 дней.
Запуск: python -X utf8 playbook_stats.py"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import candidate as cd
import lab_core as lc
import lab_feat as lf
import regime_map as rm

OUT = Path(__file__).parent / "out"
pd.set_option("display.width", 240, "display.max_columns", 40, "display.max_rows", 300)
SER = ("BTC", "ETH", "XRP", "Bitstamp")


def trades(S, legs):
    A = S.atr4()
    r = lc.nets(S, legs)
    out = []
    for x, v in zip(legs, r):
        i0, i1, p0, p1, s = x[:5]
        a = float(A[S.j[i0]])
        n = i1 - i0
        if n > 0:
            ex = np.maximum.accumulate(S.h[i0 + 1:i1 + 1]) - p0 if s == 1 else p0 - np.minimum.accumulate(S.l[i0 + 1:i1 + 1])
            pk = ex / a
        else:
            pk = np.zeros(1)
        out.append({"i0": i0, "s": s, "r": v, "w": x[5], "ч": n, "пик": float(pk.max()), "кривая": pk})
    return out


def main():
    rows1, rows2, rows3, rows4 = [], [], [], []
    for name in SER:
        S = lc.load(name)
        legs = cd.frozen(S)
        T = trades(S, legs)
        for sd, lab in ((1, "лонг"), (-1, "шорт")):
            q = [t for t in T if t["s"] == sd]
            for th in (1, 2, 3, 4, 5, 6):
                a = [t for t in q if t["пик"] >= th]
                b = [t for t in q if t["пик"] < th]
                rows1.append({"ряд": name, "сторона": lab, "пик≥ATR": th, "дошло_%": round(len(a) / len(q) * 100), "плюс_%": round(np.mean([t["r"] > 0 for t in a]) * 100), "итог_дошедших": round(sum(t["r"] for t in a)), "итог_не_дошедших": round(sum(t["r"] for t in b))})
            for hh, th in ((12, 0.5), (24, 1), (48, 1.5), (72, 2)):
                al = [t for t in q if t["ч"] >= hh]
                a = [t for t in al if t["кривая"][hh - 1] < th]
                b = [t for t in al if t["кривая"][hh - 1] >= th]
                if a and b:
                    rows2.append({"ряд": name, "сторона": lab, "час": hh, "пик<ATR": th, "n": len(a), "плюс_%": round(np.mean([t["r"] > 0 for t in a]) * 100), "среднее": round(np.mean([t["r"] for t in a]), 2), "n_выше": len(b), "плюс_%_выше": round(np.mean([t["r"] > 0 for t in b]) * 100), "среднее_выше": round(np.mean([t["r"] for t in b]), 2)})
        r = np.array([t["r"] for t in T])
        st = np.zeros(len(r), dtype=int)
        for i in range(1, len(r)):
            st[i] = st[i - 1] + 1 if r[i - 1] <= 0 else 0
        for lo, hi, lab in ((0, 0, "0"), (1, 2, "1-2"), (3, 4, "3-4"), (5, 99, "5+")):
            m = (st >= lo) & (st <= hi)
            rows3.append({"ряд": name, "убытков_подряд_до_входа": lab, "n": int(m.sum()), "среднее": round(float(r[m].mean()), 2), "плюс_%": round(float((r[m] > 0).mean() * 100)), "итог": round(float(r[m].sum()))})
        from sklearn.metrics import roc_auc_score
        fer, _, fx = rm.future(S)
        F = lf.feats(S)
        k4 = S.h4["known"]
        ok = (k4 >= S.t[S.i0]) & np.isfinite(fer)
        hi = fer > np.nanquantile(fer[ok], 2 / 3)
        for lab, v, sg in (("ATR% ранг (ниже → эффективнее)", F["atr_rank"], -1), ("ADX14", F["adx14"], 1), ("ER 5 дней", F["er30"], 1), ("пересечения зелёной за 10д", F["xG60"], -1), ("разброс G,Y,R", F["w_GYR"], -1), ("наклон синей |5д|", np.abs(F["sl30_B"]), 1), ("|от синей|", np.abs(F["d_B"]), 1)):
            m = ok & np.isfinite(v)
            rows4.append({"ряд": name, "признак": lab, "AUC": round(float(roc_auc_score(hi[m], sg * v[m])), 3)})
    a = pd.DataFrame(rows1)
    print("=== 1. Сделка дала пик X ATR (кандидат): как часто заканчивается в плюс")
    print(a.pivot_table(index=["сторона", "пик≥ATR"], columns="ряд", values=["дошло_%", "плюс_%"], sort=False).round(0).to_string())
    print(a.pivot_table(index=["сторона", "пик≥ATR"], columns="ряд", values=["итог_дошедших", "итог_не_дошедших"], sort=False).round(0).to_string())
    print("\n=== 2. К часу H пик сделки меньше порога")
    print(pd.DataFrame(rows2).pivot_table(index=["сторона", "час", "пик<ATR"], columns="ряд", values=["плюс_%", "плюс_%_выше", "среднее", "среднее_выше"], sort=False).round(1).to_string())
    print("\n=== 3. После серии убытков")
    print(pd.DataFrame(rows3).pivot_table(index="убытков_подряд_до_входа", columns="ряд", values=["n", "среднее", "плюс_%"], sort=False).round(1).to_string())
    print("\n=== 4. Предсказуем ли флет: AUC «следующие 10 дней в верхней трети по эффективности»")
    print(pd.DataFrame(rows4).pivot_table(index="признак", columns="ряд", values="AUC", sort=False).to_string())
    a.to_csv(OUT / "playbook_peak.csv", index=False)


if __name__ == "__main__":
    main()
