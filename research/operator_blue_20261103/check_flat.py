"""Флет-правило оператора до конца: ворота PREREG.md (дописка до запуска check_flat.py).
Две сетки 0.6/1.4 ($100, по $3 000 на сторону); сторона включается на закрытии 4ч, где голубая 4ч горизонтальна
(|наклон за 24 ч| ≤ θ) и |close − B4| ≤ X; шорт закрывается по рынку на закрытии 4ч выше B4·(1+X), лонг — ниже B4·(1−X).
Запуск: check_flat.py --pk-btc=<pkl>   (nice 20)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from study import TS, S, gridk  # noqa: E402

RNG = np.random.default_rng(20261103)
PER = {"A 2018–21": ("2018-01-01", "2022-01-01"), "B 2022–07.24": ("2022-01-01", "2024-08-01"),
       "C 08.24–11.26": ("2024-08-01", "2026-11-03")}
MAIN = (0.004, 0.02, 0.6, 1.4)
DAY = 86400


def main():
    pk = Path(next(a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--pk-btc=")))
    m, h1, h4, d1, fund = pd.read_pickle(pk)
    mk = gridk.Market(m["ts"].to_numpy(), m["open"].to_numpy(), m["high"].to_numpy(), m["low"].to_numpy(),
                      m["close"].to_numpy(), fund)
    c4, k4 = h4["close"].to_numpy(), h4["known"].to_numpy()
    B4 = S.ema(c4, 200)
    sl = B4 / np.r_[np.full(6, np.nan), B4[:-6]] - 1
    T0, TE = TS("2018-01-01"), min(TS("2026-11-03"), int(m["ts"].iloc[-1]) + 60)
    print(f"минуты {len(m)} до {pd.to_datetime(TE, unit='s')}", flush=True)

    def eps_rule(th, X):
        with np.errstate(invalid="ignore"):
            arm = (np.abs(sl) <= th) & (np.abs(c4 / B4 - 1) <= X)
            kill = {1: c4 < B4 * (1 - X), -1: c4 > B4 * (1 + X)}
        out = {}
        for side in (1, -1):
            on, start, ep = False, 0, []
            for i in range(400, len(c4)):
                if on and kill[side][i]:
                    ep.append((start, int(k4[i])))
                    on = False
                elif not on and arm[i]:
                    on, start = True, int(k4[i])
            if on:
                ep.append((start, TE))
            out[side] = [(max(x, T0), min(y, TE)) for x, y in ep if y > T0 and x < TE]
        return out

    def clip(eps, ta, tb):
        return [(max(x, ta), min(y, tb)) for x, y in eps if y > ta and x < tb]

    def run(eps, side, step=0.6, tgt=1.4, cap=3000.0):
        if not eps:
            return np.zeros((0, gridk.K))
        return mk.run(mk.idx([x for x, _ in eps]), mk.idx([y for _, y in eps]), side, step=step, tgt=tgt, cap=cap)

    def per_period(E, step=0.6, tgt=1.4):
        res, nets = {}, []
        for p, (a, b) in PER.items():
            ta, tb = TS(a), min(TS(b), TE)
            r = {s: run(clip(E[s], ta, tb), s, step, tgt) for s in (1, -1)}
            res[p] = {"long": float(r[1][:, 0].sum()), "short": float(r[-1][:, 0].sum()),
                      "total": float(r[1][:, 0].sum() + r[-1][:, 0].sum()), "eps": len(r[1]) + len(r[-1])}
            nets += list(r[1][:, 0]) + list(r[-1][:, 0])
        res["A+B+C"] = sum(res[p]["total"] for p in PER)
        return res, np.array(nets)

    out = {}
    E = eps_rule(*MAIN[:2])
    main_res, nets = per_period(E)
    out["main"] = main_res
    print("\n== Правило θ 0.4% · X 2% · сетка 0.6/1.4: итог $ по периодам (с нуля в каждом)")
    for p in PER:
        r = main_res[p]
        print(f"{p}: лонг {r['long']:+.0f}, шорт {r['short']:+.0f}, вместе **{r['total']:+.0f}** ({r['eps']} эп.)")
    print(f"A+B+C: {main_res['A+B+C']:+.0f}", flush=True)

    # базы по тем же периодам
    sma, s0 = [], None
    reg = d1["reg0"]
    for d_, o_ in zip(reg.index.to_numpy(), (reg == 1).to_numpy()):
        if o_ and s0 is None:
            s0 = int(d_)
        elif not o_ and s0 is not None:
            sma.append((s0, int(d_)))
            s0 = None
    if s0 is not None:
        sma.append((s0, TE))
    sma = clip(sma, T0, TE)
    base = {}
    for p, (a, b) in PER.items():
        ta, tb = TS(a), min(TS(b), TE)
        both = float(run([(ta, tb)], 1)[:, 0].sum() + run([(ta, tb)], -1)[:, 0].sum())
        base[p] = {"обе всегда": both, "лонг по SMA100": float(run(clip(sma, ta, tb), 1, cap=6000.0)[:, 0].sum())}
    out["base"] = base
    print("базы: " + json.dumps(base, ensure_ascii=False))

    # ворота 4: ДИ среднего на эпизод
    bs = RNG.choice(nets, (5000, len(nets))).mean(axis=1)
    ci = (float(np.quantile(bs, 0.025)), float(np.quantile(bs, 0.975)))
    out["ci_episode"] = {"n": len(nets), "mean": float(nets.mean()), "ci": ci}
    print(f"\nэпизодов {len(nets)}, среднее {nets.mean():+.2f} $, 95% ДИ [{ci[0]:+.2f}; {ci[1]:+.2f}]", flush=True)

    # ворота 3: соседи
    print("\n== Соседи: итог $ A / B / C / A+B+C")
    nb = {}
    for th in (0.002, 0.004, 0.008):
        for X in (0.015, 0.02, 0.025):
            if (th, X) == MAIN[:2]:
                continue
            r, _ = per_period(eps_rule(th, X))
            nb[f"θ {100 * th:g}% X {100 * X:g}%"] = r
    for st, tg in ((0.4, 1.0), (0.8, 1.65), (0.6, 1.0), (0.6, 2.0)):
        r, _ = per_period(E, st, tg)
        nb[f"сетка {st:g}/{tg:g}"] = r
    for nm, r in nb.items():
        print(f"{nm}: " + " / ".join(f"{r[p]['total']:+.0f}" for p in PER) + f" / **{r['A+B+C']:+.0f}**", flush=True)
    out["neighbors"] = nb
    nb_ok = all(r["A+B+C"] > 0 and r["C 08.24–11.26"]["total"] > 0 for r in nb.values())

    # описательно: дополнение
    comp = {}
    for s in (1, -1):
        cur, iv = T0, []
        for x, y in sorted(E[s]):
            if x > cur:
                iv.append((cur, x))
            cur = max(cur, y)
        if cur < TE:
            iv.append((cur, TE))
        comp[s] = iv
    cres, _ = per_period(comp)
    out["complement"] = cres
    print("\nдополнение (сторона включена, когда правило её выключило): " +
          " / ".join(f"{cres[p]['total']:+.0f}" for p in PER) + f" / {cres['A+B+C']:+.0f}", flush=True)

    # ворота 2: контроль — те же эпизоды в случайные моменты того же периода
    real_p = {p: main_res[p]["total"] for p in PER}
    plan = []
    for p, (a, b) in PER.items():
        ta, tb = TS(a), min(TS(b), TE)
        for s in (1, -1):
            for x, y in clip(E[s], ta, tb):
                plan.append((p, s, ta, tb, y - x))
    REPS = 999
    ctl = {p: np.zeros(REPS) for p in PER}
    sides = np.array([s for _p, s, *_r in plan])
    pidx = np.array([list(PER).index(p) for p, *_r in plan])
    for q in range(REPS):
        st = np.array([RNG.integers(ta, tb - L) if tb - L > ta else ta for _p, _s, ta, tb, L in plan])
        en = st + np.array([L for *_r, L in plan])
        r = mk.run(mk.idx(st), mk.idx(en), sides, cap=3000.0)
        for k_, p in enumerate(PER):
            ctl[p][q] = r[pidx == k_, 0].sum()
        if (q + 1) % 200 == 0:
            print(f"контроль {q + 1}/{REPS}", flush=True)
    tot_ctl = sum(ctl.values())
    ranks = {p: float((1 + (ctl[p] >= real_p[p]).sum()) / (REPS + 1)) for p in PER}
    ranks["A+B+C"] = float((1 + (tot_ctl >= main_res["A+B+C"]).sum()) / (REPS + 1))
    out["control"] = {"ranks": ranks, "ctl_median": {p: float(np.median(ctl[p])) for p in PER},
                      "ctl_median_total": float(np.median(tot_ctl))}
    print("\nконтроль: ранги " + json.dumps(ranks, ensure_ascii=False) + ", медианы случайных " +
          json.dumps(out["control"]["ctl_median"], ensure_ascii=False) + f", всего {np.median(tot_ctl):+.0f}", flush=True)

    # ворота 5: дневная кривая ликвидационной стоимости, «всё» непрерывно
    days = np.arange(((T0 // DAY) + 1) * DAY, TE, DAY)

    def curve(epsd, cap):
        """Открытый эпизод на конце дня d — его прогон до d с закрытием по рынку; закрытый — итог с дня закрытия."""
        rows = []
        for s, eps in epsd.items():
            for x, y in eps:
                rows += [(x, int(d), s, False) for d in days[(days > x) & (days < y)]]
                rows.append((x, y, s, True))
        val = mk.run(mk.idx([r[0] for r in rows]), mk.idx([r[1] for r in rows]), np.array([r[2] for r in rows]),
                     cap=cap)[:, 0]
        eq = np.zeros(len(days))
        for (x, y, s, final), v in zip(rows, val):
            if final:
                eq[days >= y] += v
            else:
                eq[days == y] += v
        return eq

    eq_rule = curve(E, 3000.0)
    eq_sma = curve({1: sma}, 6000.0)
    res5 = {}
    for nm, eq in (("правило", eq_rule), ("лонг по SMA100", eq_sma)):
        dd = float(np.max(np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]))
        res5[nm] = {"total": float(eq[-1]), "dd": dd, "ratio": float(eq[-1]) / dd if dd > 0 else None,
                    "worst_day": str(pd.to_datetime(days[int(np.argmax(np.maximum.accumulate(eq) - eq))], unit="s").date())}
    both_all = float(run([(T0, TE)], 1)[:, 0].sum() + run([(T0, TE)], -1)[:, 0].sum())
    res5["обе всегда (непрерывно)"] = {"total": both_all}
    out["dd"] = res5
    print("\n== Просадка по дневной кривой (ликвидационная стоимость), 2018 – 02.11.2026 непрерывно")
    for nm, r in res5.items():
        print(f"{nm}: " + json.dumps(r, ensure_ascii=False))

    gates = {
        "1 время (A, B, C > 0)": all(main_res[p]["total"] > 0 for p in PER),
        "2 контроль (ранг A+B+C ≤ 0.05)": ranks["A+B+C"] <= 0.05,
        "3 соседи (12 > 0 на A+B+C и в C)": nb_ok,
        "4 ДИ на эпизод без 0": ci[0] > 0 and len(nets) >= 100,
        "5 итог/просадка лучше лонга по SMA100": (res5["правило"]["ratio"] or -1) > (res5["лонг по SMA100"]["ratio"] or -1),
    }
    out["gates"] = gates
    print("\n== Ворота: " + json.dumps(gates, ensure_ascii=False, indent=1))
    (HERE / "out_check_flat.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float))


if __name__ == "__main__":
    main()
