"""Простое+ Вина (docs/WIN_INDICATOR_LAB_2026-11-07.md, коммит 2449d0b): своя реализация по его словам, его код не запускается.
Правила: простое правило R; шорт только при ранге V не выше 60%, V = ATR100 / цена на 4ч, ранг за прошлые 2190 баров 4ч; вес = медиана V за прошлые 2190 баров / V, в пределах 0.5–2, делитель 1.18, фиксируется на входе.
Противовес (второй кандидат): нет позиции, цена над синей больше чем на 0.5%, второе закрытие 4ч подряд под жёлтой: шорт половиной веса, цель синяя с допуском 0.5% по уровню или открытию часа, отмена 2 закрытиями над жёлтой, ранг не действует.
Сделка: (i0, i1, p0, p1, сторона, тип, причина, вес)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import ledger as lg  # noqa: E402
import state_card as sc  # noqa: E402
import state_map as sm  # noqa: E402
import words2 as w2  # noqa: E402
import words3_sweep as ws  # noqa: E402

pd.set_option("display.width", 260, "display.max_columns", 40, "display.max_rows", 300)
H4 = 14400
YEAR = 2190
DIV = 1.18
CUT25 = sm.T("2025-01-01")


def layer(a, n=100, end=None):
    """Ранг и вес на каждом часе: значение последней закрытой свечи 4ч. end: посчитать только по данным до этого индекса часа, для проверки заглядывания."""
    t, h, l, c = a["t"], a["h"], a["l"], a["c"]
    if end is not None:
        t, h, l, c = t[:end], h[:end], l[:end], c[:end]
    b = (t - 1) // H4
    ub, first = np.unique(b, return_index=True)
    last = np.r_[first[1:], len(t)] - 1
    Hb, Lb, Cb = np.maximum.reduceat(h, first), np.minimum.reduceat(l, first), c[last]
    pc = np.r_[Cb[0], Cb[:-1]]
    tr = np.maximum(Hb - Lb, np.maximum(np.abs(Hb - pc), np.abs(Lb - pc)))
    atr = np.full(len(tr), np.nan)
    if len(tr) >= n:
        x = tr[:n].mean()
        atr[n - 1] = x
        for i in range(n, len(tr)):
            x = (x * (n - 1) + tr[i]) / n
            atr[i] = x
    V = atr / Cb
    s = pd.Series(V)
    rk = s.rolling(YEAR + 1, min_periods=YEAR // 2).apply(lambda w: np.mean(w[:-1] < w[-1]) if np.isfinite(w[-1]) else np.nan, raw=True).to_numpy()
    med = s.rolling(YEAR, min_periods=500).median().shift(1).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        w = np.clip(med / V, 0.5, 2.0)
    w = np.where(np.isfinite(w), w, 1.0)
    idx = np.clip(np.searchsorted((ub + 1) * H4, t, side="right") - 1, 0, None)
    return rk[idx], w[idx]


def run(a, lx="R", sx="G", rank_th=0.6, size=True, counter=False, cs_w=0.5, cut=None, lay=None):
    t, c, h, l, o, j = a["t"], a["c"], a["h"], a["l"], a["o"], a["j"]
    F, B = a["f_close"], a["f_B"]
    Bp = a["B4p"]
    runs = {"G": a["f_run_G"], "Y": a["f_run_Y"], "R": a["f_run_R"]}
    rG, rY = runs["G"], runs["Y"]
    rex, rsx = runs[lx], runs[sx]
    rk, W = lay if lay is not None else layer(a)
    n = len(t) if cut is None else int(np.searchsorted(t, cut, side="right"))
    legs, side, i_e, p_e, w_e, tag, jp = [], 0, -1, 0.0, 1.0, "", -1

    def close(i, px, why):
        nonlocal side, tag
        legs.append((i_e, i, p_e, float(px), side, tag, why, w_e))
        side, tag = 0, ""

    def opn(i, s, tg, frac=1.0):
        nonlocal side, i_e, p_e, w_e, tag
        side, i_e, p_e, tag = s, i, float(c[i]), tg
        w_e = (W[i] / DIV if size else 1.0) * frac

    for i in range(a["i0"], n):
        new4 = j[i] != jp
        jp = j[i]
        if side == -1 and tag == "противовес":
            lv = Bp[i] * 1.005
            if l[i] <= lv < p_e:
                close(i, min(lv, o[i]), "цель")
                if not new4:
                    continue
        if not new4:
            continue
        if side == 1 and rex[i] <= -2:
            close(i, c[i], "под " + lx)
        elif side == -1:
            if tag == "под синей" and rsx[i] >= 2:
                close(i, c[i], "над " + sx)
            elif tag == "противовес" and rY[i] >= 2:
                close(i, c[i], "над Y")
        if side != 0:
            continue
        if F[i] > B[i]:
            if rG[i] >= 2 and rex[i] > -2:
                opn(i, 1, "над синей")
            elif counter and rY[i] == -2 and c[i] > B[i] * 1.005:
                opn(i, -1, "противовес", cs_w)
        elif rG[i] <= -2 and rsx[i] < 2 and (rank_th is None or not rk[i] > rank_th):
            opn(i, -1, "под синей")
    if side != 0:
        close(n - 1, c[n - 1], "конец")
    return legs


def curve(a, fm, legs):
    """Кривая по часам в % от $1000 с весом, как ledger.equity по закрытию часа."""
    c = a["c"]
    n = len(c)
    closed, op = np.zeros(n), np.zeros(n)
    for x in legs:
        i0, i1, p0, p1, s = x[:5]
        wv = x[7] if len(x) > 7 else 1.0
        q = lg.NOTIONAL / p0
        move, fee, fund = lg.trade_cash(fm, x[:5])
        closed[i1] += wv * (move - fee - fund)
        if i1 > i0:
            k = np.arange(i0, i1)
            op[k] += wv * (s * q * (c[k] - p0) - q * c[k] * lg.SIDE_COST - lg.NOTIONAL * lg.SIDE_COST - s * q * (fm[k] - fm[i0]))
    return (np.cumsum(closed) + op) / lg.NOTIONAL * 100


def unit(fm, legs):
    return np.array([w2.net(fm, x) for x in legs]), np.array([x[7] if len(x) > 7 else 1.0 for x in legs])


def stats(a, fm, legs):
    r, w = unit(fm, legs)
    v = r * w
    s = np.array([x[4] for x in legs])
    t0 = a["t"][np.array([x[0] for x in legs])]
    b = a["i0"]
    eq = curve(a, fm, legs)[b:]
    dd = float((eq - np.maximum.accumulate(np.r_[0.0, eq])[1:]).min())
    se = v.std(ddof=1) / np.sqrt(len(v))
    return {"n": len(v), "итог": round(float(v.sum()), 1), "просадка": round(dd, 1), "лонг": round(float(v[s == 1].sum()), 1), "шорт": round(float(v[s == -1].sum()), 1), "с2025": round(float(v[t0 >= CUT25].sum()), 1), "ди_низ": round(float(v.mean() - 1.96 * se), 2), "вес": round(float(w.mean()), 2), "отн": round(float(v.sum()) / max(abs(dd), 1.0), 2)}


VARS = {"база R": dict(rank_th=None, size=False), "только размер": dict(rank_th=None), "только фильтр": dict(size=False), "Простое+": {}, "Простое+ и противовес": dict(counter=True), "и выход шорта над Y": dict(counter=True, sx="Y"), "Простое+ выход шорта Y": dict(sx="Y")}


def main():
    cut = sm.T("2026-11-07")
    S = []
    for k in ("BTC", "ETH"):
        a, f, _ = sc.load_coin(k)
        S.append((k, "основные", a, f))
    S += [x for x in ws.series() if x[0] not in ("BTC", "ETH")]
    rows = []
    for k, grp, a, f in S:
        lay = layer(a)
        ok = np.isclose(a["c"][np.flatnonzero(np.r_[True, a["j"][1:] != a["j"][:-1]])], a["f_close"][np.flatnonzero(np.r_[True, a["j"][1:] != a["j"][:-1]])]).mean()
        for lab, kw in VARS.items():
            legs = run(a, cut=cut, lay=lay, **kw)
            rows.append({"ряд": k, "группа": grp, "вариант": lab, **stats(a, f, legs)})
        print(k, "готово, закрытия 4ч совпали", round(float(ok) * 100, 2), flush=True)
    d = pd.DataFrame(rows)
    d.to_csv(Path(__file__).parent / "out" / "plus_check.csv", index=False)
    print(d[d["группа"] == "основные"].drop(columns="группа").to_string(index=False), flush=True)
    m = d[d["группа"] == "монеты"]
    base = m[m["вариант"] == "база R"].set_index("ряд")
    out = []
    for lab, g in m.groupby("вариант", sort=False):
        g = g.set_index("ряд")
        out.append({"вариант": lab, "итог": round(g["итог"].sum()), "лучше_базы": int((g["итог"] > base["итог"].reindex(g.index)).sum()), "просадка_мед": g["просадка"].median(), "отн_мед": round(g["отн"].median(), 2), "с2025": round(g["с2025"].sum()), "вес": round(g["вес"].mean(), 2)})
    print(pd.DataFrame(out).to_string(index=False), flush=True)

    print("== заглядывание: ранг и вес при данных только до точки", flush=True)
    a, f, _ = sc.load_coin("BTC")
    rk, W = layer(a)
    for ts in ("2020-03-12 12:00", "2022-06-15 16:00", "2024-03-05 04:00", "2025-11-20 20:00"):
        i = int(np.searchsorted(a["t"], sm.T(ts)))
        r2, w2_ = layer(a, end=i + 1)
        print(ts, "ранг", round(float(rk[i]), 4), round(float(r2[-1]), 4), "вес", round(float(W[i]), 4), round(float(w2_[-1]), 4), flush=True)

    print("== веса случайно по тем же сделкам: лучше случайного и просадка", flush=True)
    rng = np.random.default_rng(20261107)
    for k, grp, ax, fx in S[:4]:
        legs = run(ax, cut=cut)
        r, w = unit(fx, legs)
        real = float((r * w).sum())
        ctl = np.array([float((r * rng.permutation(w)).sum()) for _ in range(9999)])
        print(k, "настоящие", round(real, 1), "медиана случайных", round(float(np.median(ctl)), 1), "лучше %", round(float((ctl < real).mean() * 100), 2), flush=True)

    print("== годы", flush=True)
    for k, grp, ax, fx in S[:2]:
        rowsy = {}
        for lab in ("база R", "только размер", "только фильтр", "Простое+"):
            legs = run(ax, cut=cut, **VARS[lab])
            r, w = unit(fx, legs)
            y = pd.to_datetime(ax["t"][[x[0] for x in legs]], unit="s").year
            rowsy[lab] = pd.Series(r * w).groupby(y).sum().round(0)
        print(k, flush=True)
        print(pd.DataFrame(rowsy).T.to_string(), flush=True)


if __name__ == "__main__":
    main()
