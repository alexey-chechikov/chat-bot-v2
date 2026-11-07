"""G3 деньгами: можно ли заработать на разделимости коротких убытков и длинных сделок с учётом всех следующих входов.
Модель учится по прошлым сделкам базы и раз в год переобучается. На каждом баре 4ч даёт вероятность для гипотетического лонга и шорта, фильтр входит в автомат как условие: пропущенный вход меняет следующие сделки.
Цели: long = «сделка дольше 3 дней против до суток» (то, что спрашивал Мак), pos = «сделка в плюс». Порог — доля худших по прогнозу на обучении: 20, 33, 50%.
Запуск: python -X utf8 g3_meta.py"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

import lab_core as lc
import lab_feat as lf
import w3_trader as w3

OUT = Path(__file__).parent / "out"
pd.set_option("display.width", 240, "display.max_columns", 40, "display.max_rows", 200)
DROP = {"hour", "wday"}


def side_matrix(S, s):
    F = lf.feats(S)
    n = len(S.h4["c"])
    cols = {}
    for k, v in F.items():
        if k in DROP or k.startswith("newlo"):
            continue
        if k.startswith("newhi"):
            cols[k] = F[("newhi" if s == 1 else "newlo") + k[5:]]
        elif k in lf.SIGNED:
            cols[k] = s * v
        elif k in ("rsi14", "clv", "pos30", "pos90", "pos180", "pos540", "taker", "taker6"):
            cols[k] = (v - (50 if k == "rsi14" else 0.5)) * s
        else:
            cols[k] = v
    X = pd.DataFrame(cols)
    X["side"] = float(s)
    return X


def make_model():
    import lightgbm as lgb
    return lgb.LGBMClassifier(n_estimators=120, learning_rate=0.03, max_depth=3, num_leaves=7, min_child_samples=12, subsample=0.8, subsample_freq=1, colsample_bytree=0.5, verbose=-1, n_jobs=2, random_state=7)


def wf_probs(S, target, start_year=2020):
    """Вероятности по барам 4ч: модель года Y обучена только на сделках, закрытых до начала Y."""
    legs = lc.run(S)
    d = w3.frame(S, legs)
    XL, XS = side_matrix(S, 1), side_matrix(S, -1)
    jt = S.j[d["i0"].to_numpy()]
    Xt = np.stack([XL.iloc[a].to_numpy(float) if s == 1 else XS.iloc[a].to_numpy(float) for a, s in zip(jt, d["s"])])
    t1 = S.t[d["i1"].to_numpy()]
    n = len(S.h4["c"])
    PL, PS = np.full(n, np.nan), np.full(n, np.nan)
    th = {}
    known = S.h4["known"]
    years = sorted(set(pd.to_datetime(known, unit="s").year))
    y4 = pd.to_datetime(known, unit="s").year.to_numpy()
    for yr in years:
        if yr < start_year:
            continue
        cut = lc.T(f"{yr}-01-01")
        tr = t1 < cut
        if target == "long":
            m = tr & ((d["ч"] > 72) | (d["ч"] <= 24)).to_numpy()
            y = (d["ч"] > 72).to_numpy()[m].astype(int)
        else:
            m = tr
            y = (d["r"] > 0).to_numpy()[m].astype(int)
        if m.sum() < 60 or len(set(y)) < 2:
            continue
        M = make_model().fit(Xt[m], y)
        q = M.predict_proba(Xt[m])[:, 1]
        k = np.flatnonzero(y4 == yr)
        PL[k] = M.predict_proba(XL.iloc[k].to_numpy(float))[:, 1]
        PS[k] = M.predict_proba(XS.iloc[k].to_numpy(float))[:, 1]
        for p in (20, 33, 50):
            th[(yr, p)] = float(np.quantile(q, p / 100))
    return PL, PS, th, y4


def run_filter(S, PL, PS, th, y4, pct, sides="обе"):
    n = len(PL)
    L, Sh = np.ones(n, bool), np.ones(n, bool)
    for yr in set(y4):
        if (yr, pct) not in th:
            continue
        k = y4 == yr
        if sides in ("обе", "лонг"):
            L[k] = PL[k] >= th[(yr, pct)]
        if sides in ("обе", "шорт"):
            Sh[k] = PS[k] >= th[(yr, pct)]
    return lc.run(S, Lok=L, Sok=Sh)


def main():
    names = sys.argv[1:] or ["BTC", "ETH", "XRP"]
    for name in names:
        S = lc.load(name)
        base = lc.run(S)
        start = 2020 if name != "XRP" else 2023
        cut = lc.T(f"{start}-01-01")

        def oos(legs):
            tt = S.t[[x[0] for x in legs]]
            r = lc.nets(S, legs)
            kk = tt >= cut
            eq = lc.equity(S, [x for x, q in zip(legs, kk) if q])
            return {"сделок": int(kk.sum()), "итог": round(float(r[kk].sum()), 1), "просадка": round(lc.max_dd(eq[S.i0:]), 1), "с2025": round(float(r[tt >= lc.CUT25].sum()), 1)}
        print(f"\n===== {name}: вне выборки с {start}, база {oos(base)}")
        rows = []
        for target in ("long", "pos"):
            PL, PS, th, y4 = wf_probs(S, target, start)
            for pct in (20, 33, 50):
                for sd in ("обе", "лонг", "шорт"):
                    rows.append({"цель": target, "отброшено_на_обучении_%": pct, "сторона": sd, **oos(run_filter(S, PL, PS, th, y4, pct, sd))})
        d = pd.DataFrame(rows)
        print(d.to_string(index=False))
        d.to_csv(OUT / f"g3_meta_{name}.csv", index=False)


if __name__ == "__main__":
    main()
