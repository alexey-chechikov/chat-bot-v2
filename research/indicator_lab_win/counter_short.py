"""Проверка условия оператора: шорт над синей на закреплении под жёлтой, цель синяя, отмена закреплением над жёлтой. Слой Простое+.
1. Соседи. 2. Сами сделки противовеса: год, период, ряд. 3. Случайный вход с тем же выходом. 4. Парный бутстрап против Простое+. 5. Монеты. Запуск: python -X utf8 counter_short.py"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import candidate as cd
import final_checks as fc
import lab_core as lc
import lab_data as ld
import words4 as w4

OUT = Path(__file__).parent / "out"
pd.set_option("display.width", 250, "display.max_columns", 40, "display.max_rows", 200, "display.max_colwidth", 44)
G, Y, R, B = lc.G, lc.Y, lc.R, lc.B
SER = ("BTC", "ETH", "XRP", "Bitstamp")


def neigh(S):
    r = cd.atr_rank(S, 365, 100)
    with np.errstate(invalid="ignore"):
        r6, r8 = (r <= 0.6) | ~np.isfinite(r), (r <= 0.8) | ~np.isfinite(r)
    C = w4.CS
    out = [("Простое+ без противовеса", {}), ("центр: под жёлтой, половина, отмена над жёлтой", C)]
    for w in (0.25, 0.33, 0.75, 1.0):
        out.append((f"доля {w}", {**C, "cs_w": w}))
    out += [("отмена над зелёной", {**C, "cs_x": G}), ("отмена над красной", {**C, "cs_x": R})]
    for k in (1, 3, 4):
        out.append((f"закрытий под жёлтой {k}", {**C, "cs_k": k}))
    for t in (0.25, 1.0):
        out.append((f"допуск цели {t}%", {**C, "tol": t}))
    for x in (1.0, 2.0, 3.0, 5.0):
        out.append((f"до синей не меньше {x} ATR", {**C, "cs_far": x}))
    out += [("сигнал под зелёной вместо жёлтой", {**C, "cs": "under_g_ev"}), ("сигнал под красной", {**C, "cs": "under_r"}), ("сигнал также сразу после выхода лонга", {**C, "cs": "under_y_exit"}), ("сигнал только сразу после выхода лонга", {**C, "cs": "after_exit"}),
            ("ранг ATR ≤ 0.6 и на противовесе", {**C, "cs_ok": r6}), ("ранг ATR ≤ 0.8 на противовесе", {**C, "cs_ok": r8})]
    return out


def legs_with(S, kw):
    pl = w4.plus_layer(S)
    return w4.run(S, **{**pl, **kw})


def only_cs(legs):
    return [x for x in legs if x[6] == "противовес"]


def random_exit(S):
    """Случайный момент над синей с запасом, тот же выход: цель синяя или 2 закрытия над жёлтой. Размер как в кандидате, половина."""
    c4 = S.h4["c"]
    Bv = S.line4(B)
    rY = S.run4(Y)
    j0 = int(np.searchsorted(S.h4["known"], S.t[S.i0]))
    hour = np.clip(np.searchsorted(S.t, S.h4["known"], side="left"), 0, len(S.t) - 1)
    jp = np.clip(np.searchsorted(S.h4["known"], S.t - 3600, side="right") - 1, 0, None)
    Bp = Bv[jp] * 1.005
    w = cd.weights(S, 100, 365, 0.5, 2.0) / 1.18 * 0.5
    pool = np.flatnonzero((np.arange(len(c4)) >= j0) & (c4 > Bv * 1.005))
    res = np.full(len(pool), np.nan)
    lim = 24 * 120
    for q, j in enumerate(pool):
        i0 = hour[j]
        p0 = S.c[i0]
        end = min(i0 + lim, len(S.t) - 1)
        i, p1 = end, S.c[end]
        for x in range(i0 + 1, end + 1):
            if S.l[x] <= Bp[x] < p0:
                i, p1 = x, min(Bp[x], S.o[x])
                break
            if S.is4[x] and rY[S.j[x]] >= 2:
                i, p1 = x, S.c[x]
                break
        res[q] = w[j] * (-(p1 / p0 - 1) - lc.SIDE_COST - lc.SIDE_COST * p1 / p0 + (S.fm[i] - S.fm[i0]) / p0) * 100
    return res


def main():
    print("=== 1. Соседи на слое Простое+")
    rows = []
    SS = {n: lc.load(n) for n in SER}
    for n, S in SS.items():
        for lab, kw in neigh(S):
            kw = dict(kw)
            if kw.get("cs") == "under_g_ev":
                kw["cs"] = "y_under_r_any"
            st = lc.stats(S, legs_with(S, kw))
            rows.append({"ряд": n, "сосед": lab, "итог": st["итог"], "дд": st["просадка"], "с25": st["с2025"], "n": st["n"], "p1": st["p1"], "p2": st["p2"], "p3": st["p3"]})
    d = pd.DataFrame(rows)
    d.to_csv(OUT / "counter_short_neighbours.csv", index=False)
    w = d.pivot_table(index="сосед", columns="ряд", values=["итог", "дд"], sort=False)
    w.columns = [f"{b}_{'и' if a == 'итог' else 'д'}" for a, b in w.columns]
    w25 = d.pivot_table(index="сосед", columns="ряд", values="с25", sort=False).add_suffix("_25")
    print(pd.concat([w[[f"{n}_{x}" for n in SER for x in "ид"]], w25[["BTC_25", "ETH_25", "XRP_25"]]], axis=1).round(1).to_string())

    print("\n=== 2. Сами сделки противовеса, половина объёма")
    for n, S in SS.items():
        legs = legs_with(S, w4.CS)
        cs = only_cs(legs)
        r = lc.nets(S, cs)
        y = pd.to_datetime(S.t[[x[0] for x in cs]], unit="s").year
        why = pd.Series([x[7] for x in cs]).value_counts().to_dict()
        se = r.std(ddof=1) / np.sqrt(len(r))
        print(n, "сделок", len(cs), "сумма", round(float(r.sum()), 1), "средняя", round(float(r.mean()), 2), "плюс %", round(float((r > 0).mean() * 100)), "ди", round(float(r.mean() - 1.96 * se), 2), round(float(r.mean() + 1.96 * se), 2), "выходы", why)
        print("   годы:", pd.Series(r).groupby(y).sum().round(1).to_dict())
        ctl = random_exit(S)
        ctl = ctl[np.isfinite(ctl)]
        rng = np.random.default_rng(5)
        sims = ctl[rng.integers(0, len(ctl), size=(3000, len(cs)))].sum(axis=1)
        print("   случайный вход над синей с тем же выходом: медиана суммы", round(float(np.median(sims)), 1), "среднее на сделку", round(float(ctl.mean()), 2), "реальный лучше в", round(float((sims < r.sum()).mean() * 100), 1), "%")

    print("\n=== 3. Парный блочный бутстрап, блок 90 дней: с противовесом минус Простое+")
    for n, S in SS.items():
        print(n, fc.paired(S, cd.frozen(S), legs_with(S, w4.CS)))

    print("\n=== 4. Монеты, контроль")
    rows = []
    for c in ld.COINS20:
        S = lc.load(c)
        a, b, e = lc.stats(S, lc.run(S)), lc.stats(S, cd.frozen(S)), lc.stats(S, legs_with(S, w4.CS))
        rows.append({"монета": c, "база": a["итог"], "плюс": b["итог"], "плюс_д": b["просадка"], "новый": e["итог"], "новый_д": e["просадка"], "плюс25": b["с2025"], "новый25": e["с2025"]})
    m = pd.DataFrame(rows)
    print(m.to_string(index=False))
    print("сумма: база", round(m["база"].sum()), "Простое+", round(m["плюс"].sum()), "с противовесом", round(m["новый"].sum()), "; лучше Простое+ на", int((m["новый"] > m["плюс"]).sum()), "из 20; лучше базы на", int((m["новый"] > m["база"]).sum()), "; медианная просадка", m["плюс_д"].median(), m["новый_д"].median(), "; с 2025", round(m["плюс25"].sum()), round(m["новый25"].sum()))


if __name__ == "__main__":
    main()
