"""Замер до постройки: помогает ли «подставить похожий участок» по расстоянию, направлению и пересечениям средних. Идём вперёд по времени, похожие только из прошлого, их будущее уже закончилось к моменту оценки.
Сравнение: случайные 30 точек прошлого того же ряда. Сделки автомата: оценка входа средним итогом похожих прошлых сделок той же стороны."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import entry_common as ec  # noqa: E402
import pos  # noqa: E402
import state_map as sm  # noqa: E402
import words as wd  # noqa: E402
import words2 as w2  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 30, "display.max_rows", 200)
K = 30
PERIODS = (("до 2022", 0, 2022), ("2022–24", 2022, 2025), ("2025–26", 2025, 2100))


def auc(score, y):
    r = pd.Series(score).rank().to_numpy()
    n1, n0 = int(y.sum()), int((~y).sum())
    return (r[y].sum() - n1 * (n1 + 1) / 2) / max(n1 * n0, 1)


def pinball(y, q, tau):
    e = y - q
    return np.where(e >= 0, tau * e, (tau - 1) * e).mean()


def walk(coin, a):
    sm.add_state(a)
    fw = sm.forward(a)
    n, b = len(a["c"]), a["i0"]
    lib = np.arange(b, n - sm.H5D, 4)
    lib = lib[np.isfinite(a["st"][lib]).all(axis=1)]
    first = b + 365 * 24 * 2
    q = np.arange(first, n - sm.H5D, 24)
    q = q[np.isfinite(a["st"][q]).all(axis=1)]
    sc = sm.scales(a, first)
    rng = np.random.default_rng(20261105)
    rows = []
    for i in q:
        past = lib[lib + sm.H5D <= i]
        near, _ = sm.nearest(a["st"], past, a["st"][i], K, 72, sc)
        rnd = rng.choice(past, K, replace=False)
        rows.append({"i": i, "год": pd.Timestamp(int(a["t"][i]), unit="s").year, "ret": fw["ret"][i], "up": fw["up"][i], "dn": fw["dn"][i], "er": fw["er"][i],
                     "доля_вверх": (fw["ret"][near] > 0).mean(), "доля_вверх_сл": (fw["ret"][rnd] > 0).mean(), "up80": np.quantile(fw["up"][near], .8), "dn80": np.quantile(fw["dn"][near], .8), "up80_база": np.quantile(fw["up"][past], .8), "dn80_база": np.quantile(fw["dn"][past], .8),
                     "er_м": np.median(fw["er"][near]), "er_м_сл": np.median(fw["er"][rnd]), "er_база": np.median(fw["er"][past])})
    d = pd.DataFrame(rows).dropna()
    out = []
    for lab, lo, hi in (("всё", 0, 2100),) + PERIODS:
        g = d[(d["год"] >= lo) & (d["год"] < hi)]
        if len(g) < 100:
            continue
        y = (g["ret"] > 0).to_numpy()
        er_top = (g["er"] > g["er"].quantile(2 / 3)).to_numpy()
        out.append({"ряд": coin, "период": lab, "точек": len(g), "вверх_база_%": round(y.mean() * 100, 1), "AUC_направление": round(auc(g["доля_вверх"].to_numpy(), y), 3), "AUC_случайные": round(auc(g["доля_вверх_сл"].to_numpy(), y), 3),
                    "вниз80_покрытие_%": round((g["dn"] <= g["dn80"]).mean() * 100, 1), "вверх80_покрытие_%": round((g["up"] <= g["up80"]).mean() * 100, 1), "вниз80_база_покрытие_%": round((g["dn"] <= g["dn80_база"]).mean() * 100, 1),
                    "польза_вниз_%": round((1 - pinball(g["dn"], g["dn80"], .8) / pinball(g["dn"], g["dn80_база"], .8)) * 100, 1), "польза_вверх_%": round((1 - pinball(g["up"], g["up80"], .8) / pinball(g["up"], g["up80_база"], .8)) * 100, 1),
                    "AUC_ход_или_пила": round(auc(g["er_м"].to_numpy(), er_top), 3), "AUC_ход_случайные": round(auc(g["er_м_сл"].to_numpy(), er_top), 3)})
    return out


def trades(coin, a, fm):
    sm.add_state(a)
    legs = w2.run(a, **w2.MAIN)
    sc = sm.scales(a, a["i0"] + 365 * 24 * 2)
    i0 = np.array([x[0] for x in legs])
    i1 = np.array([x[1] for x in legs])
    side = np.array([x[4] for x in legs])
    r = np.array([w2.net(fm, x) for x in legs])
    pred = np.full(len(legs), np.nan)
    for j in range(len(legs)):
        cand = np.where((side == side[j]) & (i1 < i0[j]) & np.isfinite(a["st"][i0]).all(axis=1))[0]
        if len(cand) < 50 or not np.isfinite(a["st"][i0[j]]).all():
            continue
        d = np.sqrt((((np.clip(a["st"][i0[cand]], -30, 30) - np.clip(a["st"][i0[j]], -30, 30)) / sc) ** 2).sum(axis=1))
        pred[j] = r[cand[np.argsort(d)[:15]]].mean()
    out = []
    yr = np.array([pd.Timestamp(int(a["t"][x]), unit="s").year for x in i0])
    for s, nm in ((1, "лонг"), (-1, "шорт")):
        for lab, lo, hi in (("всё", 0, 2100),) + PERIODS:
            m = (side == s) & np.isfinite(pred) & (yr >= lo) & (yr < hi)
            if m.sum() < 20:
                continue
            good = m & (pred > 0)
            bad = m & (pred <= 0)
            out.append({"ряд": coin, "сторона": nm, "период": lab, "сделок": int(m.sum()), "ранг_корр": round(pd.Series(pred[m]).rank().corr(pd.Series(r[m]).rank()), 3), "похожие_плюс_n": int(good.sum()), "похожие_плюс_сумма": round(r[good].sum(), 1), "похожие_плюс_на_сделку": round(r[good].mean(), 2) if good.any() else 0, "похожие_минус_n": int(bad.sum()), "похожие_минус_сумма": round(r[bad].sum(), 1), "похожие_минус_на_сделку": round(r[bad].mean(), 2) if bad.any() else 0})
    return out


def phases(coin, a, fm):
    """Что было потом в каждой фазе и как торговал автомат A."""
    sm.add_state(a)
    fw = sm.forward(a)
    b = a["i0"]
    t = a["t"]
    yr = pd.to_datetime(t, unit="s").year.to_numpy()
    legs = w2.run(a, **w2.MAIN)
    d = pd.DataFrame({"i": [x[0] for x in legs], "s": [x[4] for x in legs], "r": [w2.net(fm, x) for x in legs]})
    d["фаза"] = a["phase"][d["i"]]
    rows = []
    for ph in sorted(set(a["phase"][b:])):
        m = (a["phase"] == ph) & (np.arange(len(t)) >= b) & np.isfinite(fw["ret"])
        row = {"ряд": coin, "фаза": ph, "доля_времени_%": round(m.sum() / (len(t) - b) * 100, 1), "итог_5д_медиана": round(np.median(fw["ret"][m]), 2), "вверх_%": round((fw["ret"][m] > 0).mean() * 100), "вверх_медиана": round(np.median(fw["up"][m]), 2), "вниз_медиана": round(np.median(fw["dn"][m]), 2), "вниз_80": round(np.quantile(fw["dn"][m], .8), 2), "вверх_80": round(np.quantile(fw["up"][m], .8), 2), "er_медиана": round(np.median(fw["er"][m]), 2)}
        for lab, lo, hi in PERIODS:
            mm = m & (yr >= lo) & (yr < hi)
            row[f"вверх_{lab}"] = round((fw["ret"][mm] > 0).mean() * 100) if mm.sum() > 100 else -1
        g = d[d["фаза"] == ph]
        for s, nm in ((1, "лонг"), (-1, "шорт")):
            gg = g[g["s"] == s]
            row[f"{nm}_n"], row[f"{nm}_сумма"] = len(gg), round(gg["r"].sum(), 1)
        rows.append(row)
    return rows


def flat_forward(coin, a):
    """Флет сейчас — флет потом? Ход следующих 5 дней в ATR и эффективность по метке."""
    sm.add_state(a)
    fw = sm.forward(a)
    b = a["i0"]
    ok = (np.arange(len(a["c"])) >= b) & np.isfinite(fw["ret"])
    rows = []
    for v, nm in ((0, "нет сжатия"), (3, "переход"), (2, "локальный диапазон")):
        m = ok & (a["flat"] == v)
        rng_ = fw["up"][m] + fw["dn"][m]
        rows.append({"ряд": coin, "метка": nm, "доля_%": round(m.sum() / ok.sum() * 100, 1), "размах_5д_ATR": round(np.median(rng_), 2), "er_5д": round(np.median(fw["er"][m]), 3), "|итог|_ATR": round(np.median(np.abs(fw["ret"][m])), 2)})
    return rows


def marks_lowo(a):
    """Его действия: можно ли узнать действие по состоянию линий из ДРУГИХ разобранных окон. Ближайший сосед против перестановок."""
    sm.add_state(a)
    t = a["t"]
    rows = []
    for ts, act, _ in list(wd.MARKS) + list(w2.MARKS2):
        i = int(np.searchsorted(t, sm.T(ts)))
        win = next((k for k, (x, z, _) in enumerate(sm.WINDOWS) if sm.T(x) <= t[i] < sm.T(z)), -1)
        rows.append({"i": i, "act": act, "win": win})
    d = pd.DataFrame(rows)
    sc = sm.scales(a, a["i0"] + 365 * 24 * 2)
    X = np.clip(a["st"][d["i"].to_numpy()], -30, 30) / sc

    def acc(lab):
        ok = 0
        for j in range(len(d)):
            cand = np.where(d["win"].to_numpy() != d["win"].iloc[j])[0]
            nn = cand[np.argmin(np.sqrt(((X[cand] - X[j]) ** 2).sum(axis=1)))]
            ok += lab[nn] == lab[j]
        return ok / len(d)

    lab = d["act"].to_numpy()
    real = acc(lab)
    rng = np.random.default_rng(20261105)
    ctl = np.array([acc(rng.permutation(lab)) for _ in range(2000)])
    return {"действий": len(d), "угадано_%": round(real * 100, 1), "перестановки_медиана_%": round(float(np.median(ctl)) * 100, 1), "лучше_случайного_%": round(float((ctl < real).mean() * 100), 1)}


def main():
    series = ec.load_all()
    r1, r2, r3, r4 = [], [], [], []
    for k, a, f in series:
        r1 += walk(k, a)
        r2 += trades(k, a, f)
        r3 += phases(k, a, f)
        r4 += flat_forward(k, a)
        print(k, "готово", flush=True)
    for nm, rows in (("state_eval_walk", r1), ("state_eval_trades", r2), ("state_eval_phases", r3), ("state_eval_flat", r4)):
        d = pd.DataFrame(rows)
        d.to_csv(pos.OUT / f"{nm}.csv", index=False)
        print("==", nm, flush=True)
        print(d.to_string(index=False), flush=True)
    print("== его действия по состоянию из других окон", marks_lowo(series[0][1]), flush=True)


if __name__ == "__main__":
    main()
