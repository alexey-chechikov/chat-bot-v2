"""PREREG_trade_ext_1109.md: общая модель на всех признаках с полной историей — видит ли она вместе то, чего не видно
по одному. По типу: обучение — открытие 2018–22 + Bitstamp, проверка — 2023–26. Ridge / логистическая и градиентный
бустинг (глубина 2, 150 деревьев, шаг 0.05). Мера — Спирмен прогноза с итогом на проверке и итог лучшей половины
против худшей; плацебо — перестановки меток обучения. Запуск: python trade_model.py"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).parent))
import trade_scan as ts  # noqa: E402

RNG = np.random.default_rng(11092)
NPL = {"линейная": 200, "бустинг": 100}
pd.set_option("display.width", 240, "display.max_columns", 30)


def fit_predict(kind, tg, Xtr, ytr, Xte):
    med = np.nanmedian(Xtr, axis=0)
    med = np.where(np.isfinite(med), med, 0.0)
    if kind == "линейная":
        A, B = np.where(np.isfinite(Xtr), Xtr, med), np.where(np.isfinite(Xte), Xte, med)
        sc = StandardScaler().fit(A)
        if tg == "в лучших 20%":
            m = LogisticRegression(C=0.05, max_iter=3000).fit(sc.transform(A), ytr)
            return m.predict_proba(sc.transform(B))[:, 1]
        lo, hi = np.quantile(ytr, [0.05, 0.95])
        return Ridge(alpha=10.0).fit(sc.transform(A), np.clip(ytr, lo, hi)).predict(sc.transform(B))
    kw = dict(max_depth=2, max_iter=150, learning_rate=0.05, min_samples_leaf=20, random_state=0)
    if tg == "в лучших 20%":
        return HistGradientBoostingClassifier(**kw).fit(Xtr, ytr).predict_proba(Xte)[:, 1]
    lo, hi = np.quantile(ytr, [0.05, 0.95])
    return HistGradientBoostingRegressor(**kw).fit(Xtr, np.clip(ytr, lo, hi)).predict(Xte)


def main():
    D = ts.add_best(pd.read_pickle(ts.OUT / "trade_table_btc.pkl"))
    feats_all = [c for c in D.columns if c not in ts.OUTCOME and not c.startswith("_") and pd.api.types.is_numeric_dtype(D[c])]
    late = set(ts.late_feats(D, feats_all))
    feats = [f for f in feats_all if f not in late and not f.startswith("CoinGlass")]
    print(f"признаков в модели {len(feats)} (без поздних и CoinGlass)", flush=True)
    rows = []
    for typ in ts.TYPES:
        P = ts.periods(D, typ)
        tr = pd.concat([P["открытие 2018–22"], P["Bitstamp 2014–17"]])
        te = P["проверка 2023–26"]
        Xtr, Xte = tr[feats].to_numpy(float), te[feats].to_numpy(float)
        res_te = te["итог, % базы"].to_numpy(float)
        for tg in ("итог, % базы", "в лучших 20%"):
            ytr = tr[tg].to_numpy(float)
            for kind in ("линейная", "бустинг"):
                p = fit_predict(kind, tg, Xtr, ytr, Xte)
                r = stats.spearmanr(p, res_te)[0]
                top = p >= np.median(p)
                null = []
                for _ in range(NPL[kind]):
                    pp = fit_predict(kind, tg, Xtr, RNG.permutation(ytr), Xte)
                    null.append(stats.spearmanr(pp, res_te)[0])
                null = np.nan_to_num(np.array(null))
                row = {"тип": typ, "цель обучения": tg, "модель": kind, "сделок обучения": len(tr), "сделок проверки": len(te),
                       "Спирмен на 2023–26": round(float(r), 3), "ранг против плацебо": round(float((np.sum(null >= r) + 1) / (len(null) + 1)), 3),
                       "итог лучшей половины": round(float(res_te[top].sum()), 1), "итог худшей половины": round(float(res_te[~top].sum()), 1)}
                row["прошло"] = "да" if row["ранг против плацебо"] <= 0.05 and row["итог лучшей половины"] > row["итог худшей половины"] else "нет"
                rows.append(row)
                print(row, flush=True)
    R = pd.DataFrame(rows)
    R.to_csv(ts.OUT / "trade_model.csv", index=False)
    print(R.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
