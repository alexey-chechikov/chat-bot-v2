"""Определения тренда и флета: что из проверяемых описаний реально разделяет результат простого правила и будущее поведение цены.
Истина для проверки: будущая эффективность движения (|ход| / путь) и пересечения зелёной за следующие 10 дней, результат сделок, открытых в этом состоянии. Смотрим одно и то же на BTC, ETH, XRP, Bitstamp: значение состояния принимается только при одном знаке на всех рядах.
Запуск: python -X utf8 regime_map.py"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import lab_core as lc
import lab_feat as lf

OUT = Path(__file__).parent / "out"
pd.set_option("display.width", 240, "display.max_columns", 40, "display.max_rows", 300, "display.max_colwidth", 60)
SER = ("BTC", "ETH", "XRP", "Bitstamp")
FWD = 60


def future(S):
    c = S.h4["c"]
    n = len(c)
    path = np.abs(np.diff(c, prepend=c[0]))
    cs = np.cumsum(path)
    fer = np.full(n, np.nan)
    fret = np.full(n, np.nan)
    fx = np.full(n, np.nan)
    G = S.line4(lc.G)
    sg = np.sign(c - G)
    ch = np.r_[0, (sg[1:] != sg[:-1]).astype(int)]
    cc = np.cumsum(ch)
    A = S.atr4()
    fer[:n - FWD] = np.abs(c[FWD:] - c[:n - FWD]) / np.maximum(cs[FWD:] - cs[:n - FWD], 1e-12)
    fret[:n - FWD] = (c[FWD:] - c[:n - FWD]) / A[:n - FWD]
    fx[:n - FWD] = cc[FWD:] - cc[:n - FWD]
    return fer, fret, fx


def states(S):
    """Описания на закрытой 4ч. Пороги выбраны один раз, не подбирались под результат; соседи считаются отдельно."""
    F = lf.feats(S)
    out = {}
    sB = F["sl30_B"]
    above = F["d_B"] > 0
    st = F["stack"]
    # 1. Фазы индикатора как в state_map.py и Pine (без голубой 1ч)
    out["фаза индикатора"] = np.where(above, np.where((sB > 0.5) & (st == 1), "рост", "над синей, рост не сформирован"), np.where(st == -1, "падение", np.where(st == 1, "отскок под синей", "под синей, цветные смешаны")))
    # 2. Наклон синей за 5 дней
    out["наклон синей"] = np.where(sB > 0.5, "вверх", np.where(sB < -0.5, "вниз", "плоско"))
    # 3. Пила: пересечения зелёной за 10 дней
    x = F["xG60"]
    out["пересечений зелёной за 10д"] = np.where(x <= 3, "0-3", np.where(x <= 6, "4-6", np.where(x <= 9, "7-9", "10+")))
    # 4. Эффективность за 5 дней
    e = F["er30"]
    out["эффективность 5д"] = np.where(e < 0.1, "<0.1", np.where(e < 0.2, "0.1-0.2", np.where(e < 0.35, "0.2-0.35", ">=0.35")))
    # 5. ADX
    a = F["adx14"]
    out["ADX14"] = np.where(a < 20, "<20", np.where(a < 30, "20-30", ">=30"))
    # 6. Волатильность к своему году
    r = pd.Series(S.atr4() / S.h4["c"]).rolling(365 * 6, min_periods=500).rank(pct=True).to_numpy()
    out["ATR% к году"] = np.where(r < 1 / 3, "низкая", np.where(r < 2 / 3, "средняя", "высокая"))
    # 7. Сжатие линий
    w = F["w_GYR"]
    out["разброс G,Y,R"] = np.where(w < 1.5, "<1.5", np.where(w < 3, "1.5-3", np.where(w < 6, "3-6", ">=6")))
    # 8. Дневной тренд
    d = F["d_sma100"]
    out["день к SMA100"] = np.where(d > 0, "над", "под")
    # 9. Положение в месячном диапазоне
    p = F["pos180"]
    out["в месячном диапазоне"] = np.where(p < 0.25, "низ", np.where(p > 0.75, "верх", "середина"))
    # 10. Предложенная классификация, собрана из того, что устойчиво в 1–9
    flat = (x >= 7) | (e < 0.1)
    up = above & (sB > 0.25) & ~flat
    dn = (~above) & (sB < -0.25) & ~flat
    out["режим: тренд или флет"] = np.where(flat, "ФЛЕТ", np.where(up, "ТРЕНД ВВЕРХ", np.where(dn, "ТРЕНД ВНИЗ", "ПЕРЕХОД")))
    return out


def table(S, st, legs, r, fer, fret, fx):
    j0 = S.j[[x[0] for x in legs]]
    side = np.array([x[4] for x in legs])
    rows = []
    for name, lab in st.items():
        lj = lab[j0]
        for v in sorted(set(lab.tolist())):
            m4 = (lab == v) & (S.h4["known"] >= S.t[S.i0])
            ml, ms = (lj == v) & (side == 1), (lj == v) & (side == -1)
            rows.append({"ряд": S.name, "описание": name, "состояние": v, "%времени": round(float(m4.mean() / ((S.h4["known"] >= S.t[S.i0]).mean()) * 100), 1),
                         "будущая_эфф": round(float(np.nanmean(fer[m4])), 3), "будущие_пересеч": round(float(np.nanmean(fx[m4])), 1), "будущий_ход_ATR": round(float(np.nanmean(fret[m4])), 1),
                         "лонг_n": int(ml.sum()), "лонг_итог": round(float(r[ml].sum()), 1), "лонг_сред": round(float(r[ml].mean()), 2) if ml.sum() else np.nan, "шорт_n": int(ms.sum()), "шорт_итог": round(float(r[ms].sum()), 1), "шорт_сред": round(float(r[ms].mean()), 2) if ms.sum() else np.nan})
    return rows


def main():
    rows = []
    for name in SER:
        S = lc.load(name)
        legs = lc.run(S)
        r = lc.nets(S, legs)
        fer, fret, fx = future(S)
        rows += table(S, states(S), legs, r, fer, fret, fx)
    d = pd.DataFrame(rows)
    d.to_csv(OUT / "regime_map.csv", index=False)
    for name, g in d.groupby("описание", sort=False):
        print(f"\n=== {name}")
        p = g.pivot_table(index="состояние", columns="ряд", values=["%времени", "будущая_эфф", "будущие_пересеч"], sort=False).round(2)
        q = g.pivot_table(index="состояние", columns="ряд", values=["лонг_итог", "шорт_итог"], sort=False).round(0)
        q2 = g.pivot_table(index="состояние", columns="ряд", values=["лонг_n", "шорт_n"], sort=False).round(0)
        print(pd.concat([p["%времени"].add_prefix("вр_"), p["будущая_эфф"].add_prefix("эф_")], axis=1).to_string())
        print(pd.concat([q["лонг_итог"].add_prefix("Л_"), q2["лонг_n"].add_prefix("n_")], axis=1).to_string())
        print(pd.concat([q["шорт_итог"].add_prefix("Ш_"), q2["шорт_n"].add_prefix("n_")], axis=1).to_string())


if __name__ == "__main__":
    main()
