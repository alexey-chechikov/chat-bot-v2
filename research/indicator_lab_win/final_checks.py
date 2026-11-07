"""Итоговые числа отчёта: сводная таблица, Deflated Sharpe, парный блочный бутстрап против базы, половины истории, сравнение с моделью, зацепка по фандингу, конец данных Мака.
Запуск: python -X utf8 final_checks.py"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import candidate as cd
import fam_z as fz
import g4_eval as g4
import lab_core as lc
import lab_data as ld
import lab_feat as lf
import lab_stats as ls_

OUT = Path(__file__).parent / "out"
pd.set_option("display.width", 250, "display.max_columns", 40, "display.max_rows", 300, "display.max_colwidth", 50)
SER = ("BTC", "ETH", "XRP")
VARS = (("База R", lambda S: lc.run(S)), ("База G", lambda S: lc.run(S, lx=lc.G)), ("Только размер", lambda S: cd.run_cand(S, rank_th=None)), ("Только фильтр шорта", lambda S: cd.run_cand(S, size=False)), ("Кандидат Простое+", lambda S: cd.run_cand(S)), ("Только лонг, постоянный размер", lambda S: lc.run(S, short=False)), ("Только лонг с размером", lambda S: cd.run_cand(S, short_off=True) if False else lc.run(S, short=False, w_fn=cd.weights(S, 100, 365, 0.5, 2.0))))


def daily(S, legs):
    return lc.daily_returns(S, legs)


def paired(S, a, b, block=90, reps=4000, seed=3):
    d = (daily(S, b) - daily(S, a)).to_numpy()
    n = len(d)
    rng = np.random.default_rng(seed)
    cs = np.r_[0.0, np.cumsum(np.r_[d, d])]
    k = int(np.ceil(n / block))
    st = rng.integers(0, n, size=(reps, k))
    tot = (cs[st + block] - cs[st]).sum(axis=1) * (n / (k * block))
    return {"разница": round(float(d.sum()), 1), "за_год": round(float(d.mean() * 365), 1), "ди95": (round(float(np.quantile(tot, .025)), 1), round(float(np.quantile(tot, .975)), 1)), "P(разница>0)_%": round(float((tot > 0).mean() * 100), 1)}


def main():
    SS = {n: lc.load(n) for n in ("BTC", "ETH", "XRP", "Bitstamp")}
    print("=== Сводная таблица")
    rows = []
    coin_cache = {c: lc.load(c) for c in ld.COINS20}
    base_coin = {c: lc.stats(S, lc.run(S)) for c, S in coin_cache.items()}
    for lab, fn in VARS:
        r = {"вариант": lab}
        for n, S in SS.items():
            st = lc.stats(S, fn(S))
            r[n] = f'{st["итог"]:+.0f}/{st["просадка"]:.0f}'
            if n != "Bitstamp":
                r[n + "_с25"] = round(st["с2025"], 1)
            if n == "BTC":
                r["BTC_сделок"] = st["n"]
                r["BTC_периоды"] = f'{st["p1"]:+.0f}/{st["p2"]:+.0f}/{st["p3"]:+.0f}'
        tot, better, dd, s25 = 0.0, 0, [], 0.0
        for c, S in coin_cache.items():
            st = lc.stats(S, fn(S))
            tot += st["итог"]
            better += st["итог"] > base_coin[c]["итог"]
            dd.append(st["просадка"])
            s25 += st["с2025"]
        r.update({"монеты": round(tot), "лучше_из_20": better, "медиана_дд": round(float(np.median(dd))), "монеты_с25": round(s25)})
        rows.append(r)
    t = pd.DataFrame(rows)
    t.to_csv(OUT / "final_table.csv", index=False)
    print(t.to_string(index=False))

    print("\n=== Парный блочный бутстрап, блок 90 дней: кандидат против базы")
    for n, S in SS.items():
        a = lc.run(S)
        print(n, "кандидат", paired(S, a, cd.run_cand(S)), " | только размер", paired(S, a, cd.run_cand(S, rank_th=None)), " | только фильтр", paired(S, a, cd.run_cand(S, size=False)))

    print("\n=== Deflated Sharpe: все варианты А-Ж и З как попытки")
    for n in SER:
        S = SS[n]
        M1 = np.load(OUT / f"sweep_daily_{n}.npy").astype(np.float64)
        M2 = np.load(OUT / f"fam_z_daily_{n}.npy").astype(np.float64)
        L = min(M1.shape[1], M2.shape[1])
        M = np.r_[M1[:, -L:], M2[:, -L:]]
        M = M[M.std(axis=1) > 0]
        tr = ls_.sharpe(M)
        for lab, fn in (("база", lc.run), ("кандидат", cd.run_cand)):
            print(n, lab, {k: round(v, 3) for k, v in ls_.dsr(daily(S, fn(S)).to_numpy(), tr).items()}, "попыток", len(tr))

    print("\n=== Половины истории внутри семейства З: выбор на 2018–2021, результат 2022–11.2026")
    d = pd.read_csv(OUT / "fam_z.csv")
    for n in ("BTC", "ETH"):
        M = np.load(OUT / f"fam_z_daily_{n}.npy").astype(np.float64)
        S = SS[n]
        days = ls_.days_of(n)[-M.shape[1]:]
        tr = days.year <= 2021
        s1, s2 = ls_.sharpe(M[:, tr]), ls_.sharpe(M[:, ~tr])
        c = pd.Series(s1).corr(pd.Series(s2), method="spearman")
        best = int(np.nanargmax(s1))
        q = d.iloc[best]
        base_k = int(d.index[(d["шорт"] == "без") & (d["лонг"] == "без") & (d["пауза"] == "нет") & (d["размер"] == "постоянный")][0])
        print(n, "ранговая корреляция Sharpe половин", round(float(c), 3), "| лучший на 1-й половине:", q["шорт"], q["лонг"], q["пауза"], q["размер"], "2-я половина итог", round(float(M[best, ~tr].sum()), 1), "просадка", round(lc.max_dd(np.cumsum(M[best, ~tr])), 1), "| база 2-я половина", round(float(M[base_k, ~tr].sum()), 1), round(lc.max_dd(np.cumsum(M[base_k, ~tr])), 1))
        print("  PBO семейства З:", {k: round(v, 3) for k, v in ls_.cscv(M[M.std(axis=1) > 0]).items()})
        g = d.assign(s1=s1, s2=s2).groupby("размер")[["s1", "s2"]].mean().round(4) * np.sqrt(365)
        print("  средний Sharpe по размеру, половины:", g.round(2).to_dict("index"))
        g = d.assign(s1=s1, s2=s2).groupby("шорт")[["s1", "s2"]].mean() * np.sqrt(365)
        print("  средний Sharpe по фильтру шорта, половины:\n", g.round(2).sort_values("s1", ascending=False).to_string())

    print("\n=== Простое правило фильтра шорта против модели, вне выборки с 2020 (XRP с 2023), постоянный размер")
    for n, st in (("BTC", 2020), ("ETH", 2020), ("XRP", 2023)):
        S = SS[n]
        cut = lc.T(f"{st}-01-01")
        for lab, legs in (("база", lc.run(S)), ("простой фильтр", cd.run_cand(S, size=False))):
            tt = S.t[[x[0] for x in legs]]
            r = lc.nets(S, legs)
            k = tt >= cut
            print(n, lab, "сделок", int(k.sum()), "итог", round(float(r[k].sum()), 1), "просадка", round(lc.max_dd(lc.equity(S, [x for x, q in zip(legs, k) if q])[S.i0:]), 1))

    print("\n=== Зацепка: фандинг шорта поверх кандидата. Ранг за год среднего за 3 дня, плюс шорт только при ранге ≥ порога")
    for n in SER:
        S = SS[n]
        F = g4.factors(S, n)
        R = g4.yrank(F["фандинг средний 3д"])
        r6 = cd.atr_rank(S, 365, 100)
        w = cd.weights(S, 100, 365, 0.5, 2.0)
        res = {}
        for th in (None, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7):
            with np.errstate(invalid="ignore"):
                ok = (r6 <= 0.6) | ~np.isfinite(r6)
                if th is not None:
                    ok = ok & ((R >= th) | ~np.isfinite(R))
            legs = lc.run(S, Sok=ok, w_fn=w)
            m = float(np.mean([x[5] for x in legs]))
            legs = [(*x[:5], x[5] / m, *x[6:]) for x in legs]
            st = lc.stats(S, legs)
            res[str(th)] = (st["итог"], st["просадка"], st["с2025"], st["n"])
        print(n, res)
    p = pd.read_csv(OUT / "g4_placebo.csv")
    print("плацебо, лучший Δ на BTC среди фильтров шорта:", p[(p["монета"] == "BTC") & (p["сторона"] == "шорт")]["Δ"].max(), "; на ETH:", p[(p["монета"] == "ETH") & (p["сторона"] == "шорт")]["Δ"].max())
    d4 = pd.read_csv(OUT / "g4_eval.csv")
    print("настоящие, лучший Δ на BTC среди фильтров шорта:", d4[(d4["монета"] == "BTC") & (d4["сторона"] == "шорт")]["Δ"].max(), "; на ETH:", d4[(d4["монета"] == "ETH") & (d4["сторона"] == "шорт")]["Δ"].max())

    print("\n=== Конец данных в таблице Мака: при какой отсечке моё совпадает по числу сделок и итогу")
    for n, ref_n, ref in (("XRP", 433, 534.6), ("ETH", 590, 616.9), ("BTC", 589, 360.9)):
        hits = []
        for day in pd.date_range("2026-09-20", "2026-11-06", freq="12h"):
            X = lc.load(n, cut=int(day.timestamp()))
            st = lc.stats(X, lc.run(X))
            if st["n"] == ref_n:
                hits.append((day.strftime("%d.%m %H:%M"), st["итог"]))
        print(n, "Мак", ref_n, ref, "совпадение числа сделок при отсечках:", hits[:1], "...", hits[-1:], "всего", len(hits))


if __name__ == "__main__":
    main()
