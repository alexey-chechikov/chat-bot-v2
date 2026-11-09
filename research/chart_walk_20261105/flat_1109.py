"""PREREG_flat_1109.md: флет — правила F, модель баллов M, ручные баллы H. Запуск: python flat_1109.py"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
import btc_lab as bl  # noqa: E402
import plus as pl  # noqa: E402
import rules_1108 as ru  # noqa: E402
import state_map as sm  # noqa: E402
from services.btc_signals import engine as en  # noqa: E402

pd.set_option("display.width", 250, "display.max_columns", 30, "display.max_rows", 200)
OUT = Path(__file__).parent / "out"
CUT, CUT25 = sm.T("2023-01-01"), sm.T("2025-01-01")
RNG = np.random.default_rng(1109)
NPL = 999


def align(a, win=24):
    G, Y, R = a["f_G"], a["f_Y"], a["f_R"]

    def lag(x):
        return np.r_[np.full(win, np.nan), x[:-win]]
    with np.errstate(invalid="ignore"):
        up = (G > Y) & (Y > R) & (G > lag(G)) & (Y > lag(Y)) & (R > lag(R))
        dn = (G < Y) & (Y < R) & (G < lag(G)) & (Y < lag(Y)) & (R < lag(R))
    st = np.where(up, 1, np.where(dn, -1, 0))
    last = pd.Series(np.where(st != 0, st, np.nan)).ffill().fillna(0).to_numpy().astype(int)
    return st, last


def sim(a, lay, mode=None, win=24, far_thr=None, far_line="Y"):
    """Копия engine.simulate (сделки как в rules_1108.sim) + ворота флета. far_thr: лонг, вошедший выше красной больше чем на
    far_thr ATR, закрывается 2 закрытиями под far_line (Y/G) вместо красной (exit_cond_1109)."""
    rFar = a["f_run_Y"] if far_line == "Y" else a["f_run_G"]
    t, c, h, l, o, j = a["t"], a["c"], a["h"], a["l"], a["o"], a["j"]
    F, B, atr4, Bp = a["f_close"], a["f_B"], a["atr4"], a["B4p"]
    rG0, rY0, rR0 = a["f_run_G"], a["f_run_Y"], a["f_run_R"]
    rk, W = lay
    st, last = align(a, win)
    n = len(t)
    new = np.r_[True, j[1:] != j[:-1]]
    legs, pos, block = [], None, {1: False, -1: False}

    def close(i, px, why):
        s, w, tg = pos["side"], pos["w"], pos["tag"]
        if tg in en.MAIN:
            legs.append((pos["i"], i, pos["entry"], float(px), s, tg, why, w * en.FIRST))
            if pos["add_i"] is not None:
                legs.append((pos["add_i"], i, pos["add_px"], float(px), s, tg + " добор", why, w * en.ADD))
        else:
            legs.append((pos["i"], i, pos["entry"], float(px), s, tg, why, w))
        if mode == "F5" and pos["flat"]:
            if s * (px / pos["entry"] - 1) < 0:
                block[s] = True

    for i in range(int(a["i0"]), n):
        new4 = bool(new[i])
        rG, rY, rR = rG0[i], rY0[i], rR0[i]
        if st[i] != 0:
            block[1] = block[-1] = False
        hit, px, why = False, 0.0, ""
        if pos and pos["tag"] == en.CS:
            lv = float(Bp[i]) * en.CS_TOL
            if l[i] <= lv < pos["entry"]:
                hit, px, why = True, min(lv, float(o[i])), "цель"
        if new4 and not hit and pos:
            if pos["side"] == 1 and (rR <= -en.K4 or (pos.get("far") and rFar[i] <= -en.K4)):
                hit, px, why = True, float(c[i]), "выход"
            elif pos["tag"] == en.CS and rY >= en.K4:
                hit, px, why = True, float(c[i]), "отмена"
            elif pos["tag"] == "под синей" and rG >= en.K4:
                hit, px, why = True, float(c[i]), "выход"
        if pos and pos["tag"] in en.MAIN and not hit and pos["add_i"] is None and not (mode == "F6" and pos["flat"]):
            lv = pos["add_lv"]
            if (pos["side"] == 1 and h[i] >= lv) or (pos["side"] == -1 and l[i] <= lv):
                pos["add_i"] = i
                pos["add_px"] = max(lv, float(o[i])) if pos["side"] == 1 else min(lv, float(o[i]))
        if hit:
            close(i, px, why)
            pos = None
        if new4 and pos is None:
            s, tg = 0, ""
            if F[i] > B[i]:
                if rG >= en.K4 and rR > -en.K4:
                    s, tg = 1, "над синей"
                elif rY == -en.K4 and c[i] > B[i] * en.CS_TOL:
                    s, tg = -1, en.CS
            elif rG <= -en.K4 and not rk[i] > en.RANK_TH:
                s, tg = -1, "под синей"
            if s:
                flat, against = st[i] == 0, st[i] == 0 and last[i] != 0 and s != last[i]
                mult = 1.0
                if mode == "F1" and against:
                    s = 0
                elif mode == "F2" and against and tg != en.CS:
                    s = 0
                elif mode == "F3" and flat:
                    s = 0
                elif mode == "F4" and against:
                    mult = 0.5
                elif mode == "F5" and flat and block[s]:
                    s = 0
                if s:
                    far = far_thr is not None and s == 1 and (F[i] - a["f_R"][i]) / atr4[i] > far_thr
                    pos = {"side": s, "tag": tg, "entry": float(c[i]), "i": i, "w": float(W[i]) / en.DIV * mult, "flat": bool(flat),
                           "add_lv": float(c[i]) + s * en.X_ATR * float(atr4[i]), "add_i": None, "add_px": None, "far": far}
    if pos:
        close(n - 1, float(c[n - 1]), "конец")
    return legs


def row(lab, A, legs, legsb):
    (a, f, _), (b, fb, _) = A
    st, stb = pl.stats(a, f, legs), pl.stats(b, fb, legsb)
    p1, p2 = ru.part(a, f, legs)
    return {"вариант": lab, "сделок": st["n"], "итог": st["итог"], "просадка": st["просадка"], "отн": st["отн"], "2018–22": round(p1, 1), "2023–26": round(p2, 1),
            "с 2025": st["с2025"], "Bitstamp": stb["итог"], "Bitstamp просадка": stb["просадка"]}


def diag(a, f, legs, lab):
    st, last = align(a)
    r, w = pl.unit(f, legs)
    v = r * w
    i0 = np.array([x[0] for x in legs])
    s = np.array([x[4] for x in legs])
    tg = np.array([x[5] for x in legs])
    pos_start = np.array([not x[5].endswith("добор") for x in legs])
    where = np.where(st[i0] == 1, "выстроены вверх", np.where(st[i0] == -1, "выстроены вниз", np.where(last[i0] == 1, "флет после верха", "флет после низа")))
    d = pd.DataFrame({"где": where, "сторона": np.where(s == 1, "лонг", "шорт"), "тип": [x.replace(" добор", "") for x in tg], "v": v, "start": pos_start})
    g = d.groupby(["где", "сторона"]).agg(ног=("v", "size"), итог=("v", "sum"), на_ногу=("v", "mean"), в_плюсе=("v", lambda x: round(float((x > 0).mean() * 100)))).round(2)
    print(f"\n== {lab}: где входит база ==\n{g.to_string()}", flush=True)
    g2 = d.groupby(["где", "тип"]).agg(ног=("v", "size"), итог=("v", "sum")).round(1)
    print(g2.to_string(), flush=True)
    return d


# ---------- модель баллов ----------
FEATS = ["до зелёной", "до жёлтой", "до красной", "до синей", "до синей 1ч", "до красной 1ч", "наклон зелёной", "наклон жёлтой", "наклон красной", "наклон синей 5д",
         "порядок линий", "ч после G/Y", "ч после Y/R", "ч после синей", "пересечений", "ADX", "ранг ширины", "эффективность 24ч", "ранг ATR", "вес", "шорт под жёлтой",
         "сторона", "по прошлому направлению", "флет", "прошлая сделка в плюсе"]


def positions(a, lay):
    ev, _ = en.simulate(a, lay)
    X = [e for e in ev if e["kind"] == "выход"]
    st, last = align(a)
    rk, W = lay
    rows, prev = [], 0.0
    for e in X:
        i, s = e["pos"]["entry_i"], e["side"]
        m = a["st"][i]
        x = list(s * m[:11]) + list(m[11:15]) + [a["f_adx"][i], a["f_width_rank"][i], a["er24"][i], rk[i], W[i], float(e["tag"] == en.CS), float(s), float(s == last[i]), float(st[i] == 0), float(prev > 0)]
        rows.append({"i": i, "t": int(a["t"][i]), "t1": int(e["t"]), "s": s, "tag": e["tag"], "res": e["res"], "x": np.nan_to_num(np.array(x, float))})
        prev = e["res"]
    return pd.DataFrame(rows)


def hand(a, P):
    out = []
    for i, s in zip(P["i"], P["s"]):
        m = a["st"][i]
        out.append(s * m[10] + sum(s * m[k] > 0 for k in (6, 7, 8, 9)) + int(all(s * m[k] > 0 for k in (0, 1, 2, 3))))
    return np.array(out)


def fit(Xtr, ytr):
    sc = StandardScaler().fit(Xtr)
    md = LogisticRegression(C=0.1, max_iter=2000).fit(sc.transform(Xtr), ytr)
    return sc, md


def walk(P, Pb):
    """Прогноз вне выборки: Binance по годам (обучение Bitstamp + Binance до года), Bitstamp — модель на всём Binance."""
    Xb, yb = np.vstack(Pb["x"]), (Pb["res"] > 0).to_numpy().astype(int)
    yr = pd.to_datetime(P["t"], unit="s").dt.year.to_numpy()
    p, thr, mean_tr = np.full(len(P), np.nan), np.full(len(P), np.nan), np.full(len(P), np.nan)
    X, y = np.vstack(P["x"]), (P["res"] > 0).to_numpy().astype(int)
    for Y in sorted(set(yr)):
        tr = P["t1"].to_numpy() < sm.T(f"{Y}-01-01")
        Xtr, ytr = np.vstack([Xb, X[tr]]), np.r_[yb, y[tr]]
        sc, md = fit(Xtr, ytr)
        ptr = md.predict_proba(sc.transform(Xtr))[:, 1]
        k = yr == Y
        p[k] = md.predict_proba(sc.transform(X[k]))[:, 1]
        thr[k], mean_tr[k] = np.quantile(ptr, 0.3), ptr.mean()
    sc, md = fit(X, y)
    ptr = md.predict_proba(sc.transform(X))[:, 1]
    pb = md.predict_proba(sc.transform(Xb))[:, 1]
    coef = pd.Series(md.coef_[0], index=FEATS).sort_values()
    return p, thr, mean_tr, pb, np.quantile(ptr, 0.3), ptr.mean(), coef


def placebo_skip(res, keep, yr):
    real = res[keep].sum()
    k_by = {Y: int((~keep[yr == Y]).sum()) for Y in set(yr)}
    idx_by = {Y: np.where(yr == Y)[0] for Y in set(yr)}
    hits = 0
    for _ in range(NPL):
        m = np.ones(len(res), bool)
        for Y, k in k_by.items():
            if k:
                m[RNG.choice(idx_by[Y], k, replace=False)] = False
        hits += res[m].sum() >= real
    return (hits + 1) / (NPL + 1)


def placebo_size(res, mult, yr):
    real = (res * mult).sum()
    hits = 0
    for _ in range(NPL):
        m = mult.copy()
        for Y in set(yr):
            k = np.where(yr == Y)[0]
            m[k] = RNG.permutation(m[k])
        hits += (res * m).sum() >= real
    return (hits + 1) / (NPL + 1)


def halves(P, v):
    t = P["t"].to_numpy()
    return round(float(v[t < CUT].sum()), 1), round(float(v[t >= CUT].sum()), 1), round(float(v[t >= CUT25].sum()), 1)


def model_part(A):
    (a, f, lay), (b, fb, layb) = A
    P, Pb = positions(a, lay), positions(b, layb)
    res, resb = P["res"].to_numpy(), Pb["res"].to_numpy()
    yr = pd.to_datetime(P["t"], unit="s").dt.year.to_numpy()
    yrb = pd.to_datetime(Pb["t"], unit="s").dt.year.to_numpy()
    p, thr, mtr, pb, thrb, mtrb, coef = walk(P, Pb)
    y, ybb = (res > 0).astype(int), (resb > 0).astype(int)
    t = P["t"].to_numpy()
    print(f"\n== модель: позиций Binance {len(P)}, Bitstamp {len(Pb)}; в плюсе {y.mean() * 100:.0f}% / {ybb.mean() * 100:.0f}% ==", flush=True)
    print(f"AUC вне выборки: 2018–22 {roc_auc_score(y[t < CUT], p[t < CUT]):.3f}, 2023–26 {roc_auc_score(y[t >= CUT], p[t >= CUT]):.3f}, Bitstamp {roc_auc_score(ybb, pb):.3f}", flush=True)
    rows = []
    b1, b2, b25 = halves(P, res)
    rows.append({"что": "база (позиции, без фандинга)", "2018–22": b1, "2023–26": b2, "с 2025": b25, "Bitstamp": round(float(resb.sum()), 1), "ранг Binance": "", "ранг Bitstamp": ""})
    keep, keepb = p >= thr, pb >= thrb
    v = np.where(keep, res, 0.0)
    r1, r2, r25 = halves(P, v)
    rows.append({"что": "U1 пропуск 30% худших", "2018–22": r1, "2023–26": r2, "с 2025": r25, "Bitstamp": round(float(resb[keepb].sum()), 1),
                 "ранг Binance": round(placebo_skip(res, keep, yr), 3), "ранг Bitstamp": round(placebo_skip(resb, keepb, yrb), 3)})
    mult, multb = np.clip(p / mtr, 0.5, 1.5), np.clip(pb / mtrb, 0.5, 1.5)
    r1, r2, r25 = halves(P, res * mult)
    rows.append({"что": "U2 размер по баллу 0.5–1.5", "2018–22": r1, "2023–26": r2, "с 2025": r25, "Bitstamp": round(float((resb * multb).sum()), 1),
                 "ранг Binance": round(placebo_size(res, mult, yr), 3), "ранг Bitstamp": round(placebo_size(resb, multb, yrb), 3)})
    H, Hb = hand(a, P), hand(b, Pb)
    for k in (0, 1, 2):
        keep, keepb = H > k, Hb > k
        r1, r2, r25 = halves(P, np.where(keep, res, 0.0))
        rows.append({"что": f"H пропуск при балле ≤ {k} (пропущено {int((~keep).sum())} из {len(keep)})", "2018–22": r1, "2023–26": r2, "с 2025": r25,
                     "Bitstamp": round(float(resb[keepb].sum()), 1), "ранг Binance": round(placebo_skip(res, keep, yr), 3), "ранг Bitstamp": round(placebo_skip(resb, keepb, yrb), 3)})
    d = pd.DataFrame(rows)
    print(d.to_string(index=False), flush=True)
    print("\nвеса признаков модели на всём Binance (стандартизованы, + за плюс сделки):", flush=True)
    print(coef.round(3).to_string(), flush=True)
    hb = pd.DataFrame({"балл": np.r_[H, Hb], "где": ["Binance"] * len(H) + ["Bitstamp"] * len(Hb), "res": np.r_[res, resb]})
    print("\nручной балл → итог и доля в плюсе:", flush=True)
    print(hb.groupby(["где", "балл"]).agg(n=("res", "size"), итог=("res", "sum"), в_плюсе=("res", lambda x: round(float((x > 0).mean() * 100)))).round(1).to_string(), flush=True)
    d.to_csv(OUT / "flat_1109_model.csv", index=False)


def main():
    A = bl.load()
    (a, f, lay), (b, fb, layb) = A
    global FM
    FM = f
    base_ref = ru.sim(a, lay)
    mine = sim(a, lay)
    print("сверка базы с rules_1108.sim:", pl.stats(a, f, base_ref)["итог"], "против", pl.stats(a, f, mine)["итог"], "ног", len(base_ref), len(mine), flush=True)
    diag(a, f, mine, "Binance 2018–26")
    diag(b, fb, sim(b, layb), "Bitstamp 2014–17")
    rows, base = [], None
    for win in (24, 12, 48):
        for mode in ([None] if win == 24 else []) + ["F1", "F2", "F3", "F4", "F5", "F6"]:
            lab = ("база" if mode is None else mode) + ("" if win == 24 else f" окно {win}ч")
            r = row(lab, A, sim(a, lay, mode, win), sim(b, layb, mode, win))
            if base is None:
                base = r
            else:
                r["прошло"] = "да" if r["2018–22"] > base["2018–22"] and r["2023–26"] > base["2023–26"] and r["Bitstamp"] > base["Bitstamp"] else "нет"
            rows.append(r)
            print(r, flush=True)
    d = pd.DataFrame(rows)
    d.to_csv(OUT / "flat_1109_rules.csv", index=False)
    print("\n" + d.to_string(index=False), flush=True)
    model_part(A)


FM = None
if __name__ == "__main__":
    main()
