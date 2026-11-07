"""Кандидат «Простое+» и попытка его сломать: условия раздела 6 задания, соседи точным списком, случайный вход с тем же выходом, сдвиг сделок, портфель, серии.
Правила кандидата в CAND. Запуск: python -X utf8 candidate.py"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import lab_core as lc
import lab_data as ld
import lab_feat as lf

OUT = Path(__file__).parent / "out"
pd.set_option("display.width", 260, "display.max_columns", 50, "display.max_rows", 400, "display.max_colwidth", 44)
CAND = dict(rank_th=0.6, rank_days=365, rank_atr=100, imp_days=None, w_atr=100, w_days=365, lo=0.5, hi=2.0, le=lc.G, se=lc.G, sx=lc.G, lx=lc.R, reg=lc.B, k=2)


def atr_rank(S, days, n):
    key = ("rk", days, n)
    if key not in S.cache:
        S.cache[key] = lf.rank(S.atr4(n) / S.h4["c"], days * 6)
    return S.cache[key]


def weights(S, n, days, lo, hi):
    p = S.atr4(n) / S.h4["c"]
    med = pd.Series(p).rolling(days * 6, min_periods=500).median().shift(1).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        w = np.clip(med / p, lo, hi)
    return np.where(np.isfinite(w), w, 1.0)


def run_cand(S, norm=True, size=True, **over):
    P = {**CAND, **over}
    c = S.h4["c"]
    n = len(c)
    Sok, Lok = np.ones(n, bool), np.ones(n, bool)
    if P["rank_th"] is not None:
        r = atr_rank(S, P["rank_days"], P["rank_atr"])
        with np.errstate(invalid="ignore"):
            Sok = (r <= P["rank_th"]) | ~np.isfinite(r)
    if P["imp_days"] is not None:
        b = P["imp_days"] * 6
        Lok = np.r_[np.ones(b, bool), c[b:] >= c[:-b]]
    kw = dict(Lok=Lok, Sok=Sok, le=P["le"], se=P["se"], sx=P["sx"], lx=P["lx"], reg=P["reg"], k_le=P["k"], k_lx=P["k"], k_se=P["k"], k_sx=P["k"])
    if size:
        kw["w_fn"] = weights(S, P["w_atr"], P["w_days"], P["lo"], P["hi"])
    legs = lc.run(S, **kw)
    if size and norm and legs:
        m = float(np.mean([x[5] for x in legs]))
        legs = [(*x[:5], x[5] / m, *x[6:]) for x in legs]
    return legs


def frozen(S):
    """Замороженный кандидат для резерва: делитель 1.18 постоянный, как в Pine, ничего не приводится по самому ряду."""
    return [(*x[:5], x[5] / 1.18, *x[6:]) for x in run_cand(S, norm=False)]


def shift_control(S, legs, step=6, gap_days=90):
    """Все сделки сдвигаются по кругу на каждый шаг 4ч с сохранением длительности, стороны и веса. Цена и выплаты после конца ряда продолжаются с начала с масштабом."""
    b = S.i0
    c0, f0 = S.c[b:], S.fm[b:]
    sc = c0[-1] / c0[0]
    c2, f2 = np.r_[c0, c0 * sc], np.r_[f0, f0[-1] + (f0 - f0[0]) * sc]
    a = np.array([x[:6] for x in legs], dtype=float)
    i0, i1 = a[:, 0].astype(int) - b, a[:, 1].astype(int) - b
    s, w = a[:, 4], a[:, 5]
    N = len(c0)
    shifts = np.arange(gap_days * 24, N - gap_days * 24, step * 4)

    def tot(k):
        p0, p1 = c2[i0 + k], c2[i1 + k]
        return float((w * (s * (p1 / p0 - 1) - lc.SIDE_COST - lc.SIDE_COST * p1 / p0 - s * (f2[i1 + k] - f2[i0 + k]) / p0)).sum() * 100)

    real = tot(0)
    ctl = np.array([tot(int(k)) for k in shifts])
    return {"итог": round(real, 1), "сдвиги_медиана": round(float(np.median(ctl)), 1), "лучше_%": round(float((ctl < real).mean() * 100), 1), "сдвигов": len(ctl)}


def exit_table(S, rx, k, s):
    """Для каждого бара 4ч: ближайший будущий бар выхода."""
    cond = (rx <= -k) if s == 1 else (rx >= k)
    idx = np.flatnonzero(cond)
    n = len(rx)
    nx = np.full(n, n - 1)
    pos = np.searchsorted(idx, np.arange(n) + 1)
    ok = pos < len(idx)
    nx[ok] = idx[pos[ok]]
    return nx


def random_entry(S, legs, reps=2000, seed=9):
    """Случайный вход на той же стороне синей с тем же выходом, те же число сделок по сторонам и размер по формуле. Кандидат против случайного. Сделки могут перекрываться: сравнение по сумме и среднему."""
    c4 = S.h4["c"]
    Bv = S.line4(CAND["reg"])
    rx_l, rx_s = S.run4(CAND["lx"]), S.run4(CAND["sx"])
    nxL, nxS = exit_table(S, rx_l, 2, 1), exit_table(S, rx_s, 2, -1)
    w = weights(S, CAND["w_atr"], CAND["w_days"], CAND["lo"], CAND["hi"])
    hour_of = np.clip(np.searchsorted(S.t, S.h4["known"], side="left"), 0, len(S.t) - 1)
    j0 = int(np.searchsorted(S.h4["known"], S.t[S.i0]))
    n = len(c4)
    pool_l = np.flatnonzero((np.arange(n) >= j0) & (c4 > Bv) & (nxL < n - 1))
    pool_s = np.flatnonzero((np.arange(n) >= j0) & (c4 <= Bv) & (nxS < n - 1))
    m = float(np.mean([x[5] for x in legs]))

    def unit(pool, nx, s):
        i0, i1 = hour_of[pool], hour_of[nx[pool]]
        p0, p1 = S.c[i0], S.c[i1]
        return w[pool] / m * (s * (p1 / p0 - 1) - lc.SIDE_COST - lc.SIDE_COST * p1 / p0 - s * (S.fm[i1] - S.fm[i0]) / p0) * 100

    uL, uS = unit(pool_l, nxL, 1), unit(pool_s, nxS, -1)
    s_arr = np.array([x[4] for x in legs])
    nL, nS = int((s_arr == 1).sum()), int((s_arr == -1).sum())
    r = lc.nets(S, legs)
    rng = np.random.default_rng(seed)
    ctl = uL[rng.integers(0, len(uL), size=(reps, nL))].sum(axis=1) + uS[rng.integers(0, len(uS), size=(reps, nS))].sum(axis=1)
    real = float(r.sum())
    ctl_l = uL[rng.integers(0, len(uL), size=(reps, nL))].sum(axis=1)
    ctl_s = uS[rng.integers(0, len(uS), size=(reps, nS))].sum(axis=1)
    return {"итог": round(real, 1), "случайный_медиана": round(float(np.median(ctl)), 1), "лучше_%": round(float((ctl < real).mean() * 100), 1), "лонг": round(float(r[s_arr == 1].sum()), 1), "случ_лонг": round(float(np.median(ctl_l)), 1), "лонг_лучше_%": round(float((ctl_l < r[s_arr == 1].sum()).mean() * 100), 1), "шорт": round(float(r[s_arr == -1].sum()), 1), "случ_шорт": round(float(np.median(ctl_s)), 1), "шорт_лучше_%": round(float((ctl_s < r[s_arr == -1].sum()).mean() * 100), 1)}


def ci(S, legs):
    r = lc.nets(S, legs)
    se = r.std(ddof=1) / np.sqrt(len(r))
    return {"n": len(r), "среднее": round(float(r.mean()), 3), "ди_низ": round(float(r.mean() - 1.96 * se), 3), "ди_верх": round(float(r.mean() + 1.96 * se), 3)}


def row(S, legs):
    st = lc.stats(S, legs)
    return {k: st[k] for k in ("n", "итог", "просадка", "отн", "лонг", "шорт", "с2025", "p1", "p2", "p3", "плюс%")}


def neighbours():
    V = [("кандидат", {})]
    for x in (0.4, 0.5, 0.7, 0.8):
        V.append((f"порог ранга {x}", dict(rank_th=x)))
    V.append(("без фильтра шорта", dict(rank_th=None)))
    for x in (180, 730):
        V.append((f"окно ранга {x}д", dict(rank_days=x)))
    for x in (14, 50, 200):
        V.append((f"ATR ранга {x}", dict(rank_atr=x)))
    for x in (10, 15, 20, 30, 45, 60, 90):
        V.append((f"отклонено: лонг с импульсом {x}д", dict(imp_days=x)))
    for x in (50, 200):
        V.append((f"ATR веса {x}", dict(w_atr=x)))
    V.append(("ATR веса 14", dict(w_atr=14)))
    for x in (180, 730):
        V.append((f"окно медианы {x}д", dict(w_days=x)))
    for lo, hi in ((0.33, 3.0), (0.25, 3.0), (0.67, 1.5), (0.75, 1.33)):
        V.append((f"пределы веса {lo}-{hi}", dict(lo=lo, hi=hi)))
    V.append(("размер постоянный", dict(size=False)))
    for x in (1, 3):
        V.append((f"закрытий {x}", dict(k=x)))
    for n in (40, 60):
        V.append((f"зелёная TEMA{n}", dict(le=("T", n), se=("T", n), sx=("T", n))))
    for n in (150, 250):
        V.append((f"красная TEMA{n}", dict(lx=("T", n))))
    for n in (150, 250):
        V.append((f"синяя EMA{n}", dict(reg=("E", n))))
    V.append(("выход лонга Y", dict(lx=lc.Y)))
    V.append(("выход лонга G", dict(lx=lc.G)))
    return V


def cd_raw(S):
    """Средний вес до приведения к 1: столько надо учесть, если применять формулу как есть."""
    legs = run_cand(S, norm=False)
    return round(float(np.mean([x[5] for x in legs])), 3)


def main():
    names = ["BTC", "ETH", "XRP", "Bitstamp"]
    SS = {n: lc.load(n) for n in names}
    print("===== Кандидат против базы")
    rows = []
    for n, S in SS.items():
        rows.append({"ряд": n, "что": "база R", **row(S, lc.run(S))})
        rows.append({"ряд": n, "что": "только размер", **row(S, run_cand(S, rank_th=None))})
        rows.append({"ряд": n, "что": "только фильтр шорта", **row(S, run_cand(S, size=False))})
        rows.append({"ряд": n, "что": "кандидат: размер и фильтр", **row(S, run_cand(S))})
        raw = cd_raw(S)
        rows[-1]["вес_до_нормировки"] = raw
    print(pd.DataFrame(rows).to_string(index=False))

    print("\n===== Условие 5: соседи точным списком")
    rows = []
    for lab, over in neighbours():
        r = {"сосед": lab}
        for n, S in SS.items():
            st = lc.stats(S, run_cand(S, **over))
            r.update({f"{n}": st["итог"], f"{n}_д": st["просадка"]})
            if n != "Bitstamp":
                r[f"{n}_с25"] = st["с2025"]
            if n == "BTC":
                r.update({"p1": st["p1"], "p2": st["p2"], "p3": st["p3"], "BTC_n": st["n"]})
        rows.append(r)
    nb = pd.DataFrame(rows)
    nb.to_csv(OUT / "candidate_neighbours.csv", index=False)
    print(nb.to_string(index=False))

    print("\n===== Условие 6 и 7: интервал, сдвиг, случайный вход")
    for n, S in SS.items():
        legs = run_cand(S)
        print(n, ci(S, legs), "\n  сдвиг:", shift_control(S, legs), "\n  случайный вход:", random_entry(S, legs))
    print("\nбаза для сравнения:")
    for n, S in SS.items():
        base = lc.run(S)
        print(n, ci(S, base), "\n  сдвиг:", shift_control(S, base))

    print("\n===== Годы")
    for n, S in SS.items():
        a, b = lc.run(S), run_cand(S)
        ya = pd.Series(lc.nets(S, a)).groupby(pd.to_datetime(S.t[[x[0] for x in a]], unit="s").year).sum().round(1)
        yb = pd.Series(lc.nets(S, b)).groupby(pd.to_datetime(S.t[[x[0] for x in b]], unit="s").year).sum().round(1)
        wy = pd.Series([x[5] for x in b]).groupby(pd.to_datetime(S.t[[x[0] for x in b]], unit="s").year).mean().round(2)
        t = pd.DataFrame({"база": ya, "кандидат": yb, "средний_вес": wy, "кандидат_на_вес_1": (yb / wy).round(1)})
        print(n, "\n", t.T.to_string(), "\n  лучше базы лет:", int((t["кандидат"] > t["база"]).sum()), "из", len(t), "; с поправкой на вес:", int((t["кандидат_на_вес_1"] > t["база"]).sum()))

    print("\n===== Монеты (контроль, в отборе не участвовали)")
    rows = []
    for c in ld.COINS20:
        S = lc.load(c)
        a, b = lc.stats(S, lc.run(S)), lc.stats(S, run_cand(S))
        rows.append({"монета": c, "база": a["итог"], "база_д": a["просадка"], "канд": b["итог"], "канд_д": b["просадка"], "база25": a["с2025"], "канд25": b["с2025"]})
    m = pd.DataFrame(rows)
    print(m.to_string(index=False))
    print("сумма база", m["база"].sum(), "кандидат", m["канд"].sum(), "лучше на", int((m["канд"] > m["база"]).sum()), "из 20; медианная просадка", m["база_д"].median(), m["канд_д"].median(), "; с 2025", m["база25"].sum(), m["канд25"].sum(), "; меньше просадка на", int((m["канд_д"] > m["база_д"]).sum()))

    print("\n===== Портфель BTC + ETH + XRP с 07.2020, $1000 на сделку на каждой монете")
    frm = pd.Timestamp("2020-07-01")
    cur = {}
    for lab, fn in (("база", lc.run), ("кандидат", run_cand)):
        parts = {}
        for n in ("BTC", "ETH", "XRP"):
            S = SS[n]
            d = lc.daily_returns(S, fn(S))
            parts[n] = d[d.index >= frm]
        f = pd.DataFrame(parts).fillna(0.0)
        cur[lab] = f
        total = f.sum(axis=1)
        eq = total.cumsum().to_numpy()
        print(lab, {n: (round(float(f[n].sum()), 1), round(lc.max_dd(f[n].cumsum().to_numpy()), 1)) for n in f}, "портфель итог", round(float(total.sum()), 1), "просадка", round(lc.max_dd(eq), 1), "Sharpe год", round(float(total.mean() / total.std() * np.sqrt(365)), 2), "BTC один Sharpe", round(float(f["BTC"].mean() / f["BTC"].std() * np.sqrt(365)), 2))
    print("корреляция дней кандидата:\n", cur["кандидат"].corr().round(2).to_string())

    print("\n===== Серии убытков и размер кандидата, BTC")
    S = SS["BTC"]
    legs = run_cand(S)
    r = lc.nets(S, legs)
    cur_, ser = 0, []
    s_ = 0.0
    for v in r:
        if v <= 0:
            cur_ += 1
            s_ += v
        else:
            if cur_:
                ser.append((cur_, round(s_, 1)))
            cur_, s_ = 0, 0.0
    a = np.array([x[0] for x in ser])
    print("длина max", a.max(), "средняя", round(a.mean(), 2), "≥5:", int((a >= 5).sum()), "≥8:", int((a >= 8).sum()), "худшие:", sorted(ser, key=lambda z: z[1])[:5])
    rng = np.random.default_rng(1)
    sim = np.array([(lambda e: (e - np.maximum.accumulate(np.r_[0.0, e])[1:]).min())(np.cumsum(rng.choice(r, size=len(r), replace=True))) for _ in range(3000)])
    print("бутстрап просадки закрытых: медиана", round(float(np.median(sim)), 1), "5%", round(float(np.quantile(sim, .05)), 1), "1%", round(float(np.quantile(sim, .01)), 1))
    pk = np.zeros(len(S.t) + 1)
    for x in legs:
        pk[x[0]] += x[5]
        pk[x[1]] -= x[5]
    print("пик номинала ×$1000:", round(float(np.cumsum(pk).max()), 2), "; средний вес", round(float(np.mean([x[5] for x in legs])), 3), "; сделок в год", round(len(legs) / ((S.t[-1] - S.t[S.i0]) / 31557600), 1))
    print("время в позиции %:", round(float(sum(x[1] - x[0] for x in legs) / (len(S.t) - S.i0) * 100), 1))
    legs0 = lc.run(S)
    print("база: время в позиции %:", round(float(sum(x[1] - x[0] for x in legs0) / (len(S.t) - S.i0) * 100), 1))
    # записать сделки кандидата
    pd.DataFrame([{"вход": pd.Timestamp(int(S.t[x[0]]), unit="s"), "выход": pd.Timestamp(int(S.t[x[1]]), unit="s"), "сторона": x[4], "p0": x[2], "p1": x[3], "вес": round(x[5], 3), "итог_%": round(float(v), 3), "причина": x[7]} for x, v in zip(legs, r)]).to_csv(OUT / "candidate_trades_BTC.csv", index=False)


if __name__ == "__main__":
    main()
