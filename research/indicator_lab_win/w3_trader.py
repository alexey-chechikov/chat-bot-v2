"""W3 и G3: взгляд на сделки простого правила (выход R). MAE/MFE, шорты, размер, серии убытков, разделимость коротких убытков и длинных плюсовых сделок.
Запуск: python -X utf8 w3_trader.py [BTC ETH XRP]"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

import lab_core as lc
import lab_feat as lf

OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)
pd.set_option("display.width", 220, "display.max_columns", 40, "display.max_rows", 300)


def frame(S, legs):
    t, h, l = S.t, S.h, S.l
    A = S.atr4()
    rows = []
    r = lc.nets(S, legs)
    for x, v in zip(legs, r):
        i0, i1, p0, p1, s = x[:5]
        a = float(A[S.j[i0]])
        if i1 > i0:
            hi, lo = h[i0 + 1:i1 + 1].max(), l[i0 + 1:i1 + 1].min()
        else:
            hi, lo = p0, p0
        mfe = (hi - p0) if s == 1 else (p0 - lo)
        mae = (p0 - lo) if s == 1 else (hi - p0)
        rows.append({"i0": i0, "i1": i1, "t0": t[i0], "год": pd.Timestamp(int(t[i0]), unit="s").year, "s": s, "p0": p0, "p1": p1, "r": v, "ч": i1 - i0, "atrp": a / p0 * 100, "mfe_atr": mfe / a, "mae_atr": mae / a, "mfe": mfe / p0 * 100, "mae": mae / p0 * 100, "why": x[7]})
    return pd.DataFrame(rows)


def block(d, title):
    print(f"\n=== {title}: n={len(d)} итог {d['r'].sum():+.1f} плюс {(d['r'] > 0).mean() * 100:.0f}%")
    dur = pd.cut(d["ч"], [-1, 24, 72, 168, 10 ** 6], labels=["до суток", "1-3д", "3-7д", ">7д"])
    print(d.groupby([d["s"], dur], observed=True)["r"].agg(["count", "sum", "mean"]).round(2).to_string())
    print("годы:", d.groupby("год")["r"].sum().round(1).to_dict())
    print("лонг годы:", d[d["s"] == 1].groupby("год")["r"].sum().round(1).to_dict())
    print("шорт годы:", d[d["s"] == -1].groupby("год")["r"].sum().round(1).to_dict())


def mae_mfe(d):
    """Где защита экономит и где режет: для каждой отсечки MAE в ATR — что стало со сделками, которые туда дошли."""
    rows = []
    for th in (0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 6, 8):
        q = d[d["mae_atr"] >= th]
        rows.append({"MAE≥ATR": th, "дошло": len(q), "доля": round(len(q) / len(d) * 100, 1), "их_итог": round(q["r"].sum(), 1), "плюсовых": int((q["r"] > 0).sum()), "итог_плюсовых": round(q.loc[q["r"] > 0, "r"].sum(), 1), "итог_минусовых": round(q.loc[q["r"] <= 0, "r"].sum(), 1)})
    print("\nMAE: сделки, ушедшие против нас хотя бы на X ATR\n", pd.DataFrame(rows).to_string(index=False))
    rows = []
    for th in (0.5, 1, 1.5, 2, 3, 4, 5, 6, 8, 10, 15):
        q = d[d["mfe_atr"] >= th]
        rows.append({"MFE≥ATR": th, "дошло": len(q), "доля": round(len(q) / len(d) * 100, 1), "итог": round(q["r"].sum(), 1), "в_минус": int((q["r"] <= 0).sum()), "итог_в_минус": round(q.loc[q["r"] <= 0, "r"].sum(), 1), "средн_отдано_ATR": round(float((q["mfe_atr"] - q["r"] / q["atrp"]).mean()), 1)})
    print("\nMFE: сделки, давшие хотя бы X ATR в плюс\n", pd.DataFrame(rows).to_string(index=False))


def streaks(S, legs):
    r = lc.nets(S, legs)
    cur, best = 0, []
    s = 0.0
    for v in r:
        if v <= 0:
            cur += 1
            s += v
        else:
            if cur:
                best.append((cur, round(s, 1)))
            cur, s = 0, 0.0
    if cur:
        best.append((cur, round(s, 1)))
    a = np.array([x[0] for x in best])
    print("\nсерии убытков: длина max", a.max(), "средняя", round(a.mean(), 2), "≥5:", int((a >= 5).sum()), "≥8:", int((a >= 8).sum()), "худшие по сумме:", sorted(best, key=lambda z: z[1])[:5])
    rng = np.random.default_rng(1)
    eq = np.cumsum(r)
    dd = (eq - np.maximum.accumulate(np.r_[0.0, eq])[1:]).min()
    sim = []
    for _ in range(2000):
        q = rng.choice(r, size=len(r), replace=True)
        e = np.cumsum(q)
        sim.append((e - np.maximum.accumulate(np.r_[0.0, e])[1:]).min())
    sim = np.array(sim)
    print(f"просадка закрытых {dd:.1f}; бутстрап сделок: медиана {np.median(sim):.1f}, 5% худших {np.quantile(sim, .05):.1f}, 1% худших {np.quantile(sim, .01):.1f}")
    print("размер: при допустимой просадке 20% счёта и 1% худшем бутстрапе номинал сделки =", round(20 / abs(np.quantile(sim, .01)) * 100, 1), "% счёта")


def auc(y, p):
    from sklearn.metrics import roc_auc_score
    return float(roc_auc_score(y, p)) if len(set(y)) == 2 else np.nan


def wf_auc(X, y, year, make, min_train=60):
    """Скользящая проверка по годам: учим на всех прошлых годах, предсказываем следующий."""
    pred = np.full(len(y), np.nan)
    for yr in sorted(set(year)):
        tr, te = year < yr, year == yr
        if tr.sum() < min_train or len(set(y[tr])) < 2 or te.sum() == 0:
            continue
        m = make()
        m.fit(X[tr], y[tr])
        pred[te] = m.predict_proba(X[te])[:, 1]
    ok = np.isfinite(pred)
    return auc(y[ok], pred[ok]), int(ok.sum()), pred


def separability(S, legs, name):
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    import lightgbm as lgb
    F = lf.feats(S)
    d = frame(S, legs)
    rows = [lf.signed_row(F, S.j[i], s) for i, s in zip(d["i0"], d["s"])]
    X = pd.DataFrame(rows)
    X = X.drop(columns=[c for c in X.columns if c in ("hour", "wday")], errors="ignore")
    X["side"] = d["s"].to_numpy()
    yr = d["год"].to_numpy()
    long_win = (d["ч"] > 72).to_numpy()
    short_loss = (d["ч"] <= 24).to_numpy()
    mask = long_win | short_loss
    print(f"\n=== G3 {name}: коротких до суток {short_loss.sum()} итог {d.loc[short_loss, 'r'].sum():+.1f}; дольше 3 дней {long_win.sum()} итог {d.loc[long_win, 'r'].sum():+.1f}")
    makes = {"логит": lambda: make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(C=0.05, max_iter=500)),
             "GBM": lambda: lgb.LGBMClassifier(n_estimators=120, learning_rate=0.03, max_depth=3, num_leaves=7, min_child_samples=12, subsample=0.8, subsample_freq=1, colsample_bytree=0.5, verbose=-1, n_jobs=2, random_state=7)}
    Xa = X.to_numpy(float)
    res = {}
    for lab, mk in makes.items():
        a, n, pred = wf_auc(Xa[mask], long_win[mask].astype(int), yr[mask], mk)
        rng = np.random.default_rng(3)
        ctl = []
        ym = long_win[mask].astype(int)
        for _ in range(30):
            y2 = ym.copy()
            for q in set(yr[mask]):
                k = np.flatnonzero(yr[mask] == q)
                y2[k] = rng.permutation(y2[k])
            ctl.append(wf_auc(Xa[mask], y2, yr[mask], mk)[0])
        ctl = np.array(ctl)
        a2, n2, _ = wf_auc(Xa, (d["r"] > 0).to_numpy().astype(int), yr, mk)
        print(f"{lab}: AUC вне выборки «короткий убыток или длинная» {a:.3f} (n={n}), сдвиг меток {np.nanmean(ctl):.3f}±{np.nanstd(ctl):.3f}, лучше сдвига в {(ctl < a).mean() * 100:.0f}%; все сделки r>0: {a2:.3f} (n={n2})")
        res[lab] = a
    uni = []
    ym = long_win[mask].astype(int)
    for col in X.columns:
        v = X[col].to_numpy(float)[mask]
        ok = np.isfinite(v)
        if ok.sum() < 50 or len(set(v[ok])) < 3:
            continue
        a = auc(ym[ok], v[ok])
        h1 = yr[mask] <= 2021
        a1 = auc(ym[ok & h1], v[ok & h1])
        a2 = auc(ym[ok & ~h1], v[ok & ~h1])
        uni.append({"признак": col, "AUC": round(a, 3), "до2022": round(a1, 3), "с2022": round(a2, 3), "мин_откл": round(min(abs(a1 - .5), abs(a2 - .5)) * (1 if (a1 - .5) * (a2 - .5) > 0 else -1), 3)})
    u = pd.DataFrame(uni).sort_values("мин_откл", ascending=False)
    print("Одиночные признаки: лучшие по устойчивости в обеих половинах\n", u.head(16).to_string(index=False))
    u.to_csv(OUT / f"g3_univariate_{name}.csv", index=False)
    # в первые часы сделки: только сделки, ещё открытые к этому часу
    early = []
    for hrs in (4, 8, 12, 16, 24, 36, 48):
        al = d[d["ч"] > hrs]
        cur, mfe, ok = [], [], []
        for _, x in al.iterrows():
            i0, s, p0 = int(x["i0"]), x["s"], x["p0"]
            a = float(S.atr4()[S.j[i0]])
            cur.append(s * (S.c[i0 + hrs] - p0) / a)
            hh = S.h[i0 + 1:i0 + hrs + 1].max() if s == 1 else p0 * 2 - S.l[i0 + 1:i0 + hrs + 1].min()
            mfe.append((hh - p0) / a)
        y = (al["ч"] > 72).to_numpy().astype(int)
        y2 = (al["r"] > 0).to_numpy().astype(int)
        cur, mfe = np.array(cur), np.array(mfe)
        h1 = al["год"].to_numpy() <= 2021
        early.append({"час": hrs, "открыто": len(al), "итог_этих": round(al["r"].sum(), 1), "AUC_текущий→>3д": round(auc(y, cur), 3), "до2022": round(auc(y[h1], cur[h1]), 3), "с2022": round(auc(y[~h1], cur[~h1]), 3), "AUC_пик→>3д": round(auc(y, mfe), 3), "AUC_текущий→плюс": round(auc(y2, cur), 3),
                      "в_минусе_итог": round(al.loc[cur <= 0, "r"].sum(), 1), "в_минусе_n": int((cur <= 0).sum()), "в_плюсе_итог": round(al.loc[cur > 0, "r"].sum(), 1), "в_плюсе_n": int((cur > 0).sum())})
    print("В первые часы сделки (выжившие к этому часу):\n", pd.DataFrame(early).to_string(index=False))
    return d


def vol_sizing(S, name):
    A = S.atr4()
    p = A / S.h4["c"]
    med = pd.Series(p).expanding(min_periods=500).median().shift(1).to_numpy()
    w = np.clip(med / p, 0.25, 2.0)
    w = np.where(np.isfinite(w), w, 1.0)
    base = lc.stats(S, lc.run(S))
    vs = lc.stats(S, lc.run(S, w_fn=w))
    k = 1 / vs["вес"]
    print(f"\n=== размер {name}: постоянный номинал итог {base['итог']} просадка {base['просадка']} отн {base['отн']}; постоянный риск (средний вес {vs['вес']}) итог {vs['итог']} просадка {vs['просадка']} отн {vs['отн']}; приведённо к весу 1: итог {vs['итог'] * k:.1f} просадка {vs['просадка'] * k:.1f}")


def bench(S, name):
    """Эталоны: держать всё время; лонг над синей без выходов по зелёной и красной; только лонги простого правила."""
    i0 = S.i0
    bh = (S.c[-1] / S.c[i0] - 1) * 100
    eq_bh = (S.c[i0:] / S.c[i0] - 1) * 100
    print(f"\n=== эталоны {name}: держать {bh:+.0f} просадка {lc.max_dd(eq_bh):.0f}")
    for lab, kw in (("база R", {}), ("только лонг R", dict(short=False)), ("только шорт", dict(long=False)), ("лонг от G, выход под B", dict(lx=lc.B, short=False)), ("лонг от Y выход под B, шорт нет", dict(le=lc.Y, lx=lc.B, short=False))):
        st = lc.stats(S, lc.run(S, **kw))
        print(lab, {k: st[k] for k in ("n", "итог", "просадка", "отн", "с2025", "p1", "p2", "p3", "плюс%")})


def main():
    names = sys.argv[1:] or ["BTC", "ETH", "XRP"]
    for name in names:
        S = lc.load(name)
        legs = lc.run(S)
        d = frame(S, legs)
        block(d, f"{name} база R")
        block(d[d["год"] >= 2025], f"{name} с 2025")
        mae_mfe(d)
        streaks(S, legs)
        vol_sizing(S, name)
        bench(S, name)
        separability(S, legs, name)
        d.to_csv(OUT / f"w3_trades_{name}.csv", index=False)


if __name__ == "__main__":
    main()
