"""Прогон правил режимов из PREREG.md (записаны и закоммичены ДО прогона, f24a9b7). Ничего не подбирается.

Что делает: строит эпизоды каждого правила по закрытым 4H/1H барам, гоняет сетку ядром gridk (сверено с
regime_grid.run) по полному капиталу (тейки + выход остатка − комиссии ± фандинг), сравнивает с контролем — те же
сетки в случайные моменты той же длительности (999 повторов, ранг (k+1)/(n+1)), по периодам A (2018–05.2024, новый),
B (05.2024–04.2026), C (05–11.2026, в выборке), половины A и B, 5 соседних настроек, перевёрнутые правила.

ПЕРЕВЁРНУТЫЕ ПРАВИЛА: правило, которое проигрывает из-за комиссий (до комиссий ≈ 0), перевёрнутым в плюс не станет —
комиссия платится в обе стороны. Переворот может помочь только там, где минус — от направленного мешка; поэтому у
каждого правила печатается разложение: тейки, выход остатка, комиссии, фандинг.

Запуск: nice -n 20 .venv/bin/python3 research/market_regimes_20261102/regime_rules.py [--ctl=999] [--only=D1,U1]
Итог: out/regime_rules_result.json + таблица в stdout."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import gridk  # noqa: E402
import mr_data as md  # noqa: E402

N_CTL = int(next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--ctl=")), "999"))
ONLY = next((a.split("=", 1)[1].split(",") for a in sys.argv[1:] if a.startswith("--only=")), None)
DAY = 86400
T = lambda s: int(pd.Timestamp(s, tz="UTC").timestamp())  # noqa: E731
PERIODS = {"A": (T("2018-01-01"), T("2024-05-15")), "B": (T("2024-05-15"), T("2026-05-01")),
           "C": (T("2026-05-01"), None)}
HALF = {"A": T("2021-03-01"), "B": T("2025-05-08")}
NEIGH = [(0.6, 1.4), (0.4, 1.0), (0.8, 1.65), (0.6, 1.0), (0.6, 2.0)]
CAP1, CAP2 = 6000.0, 3000.0


def runs(times: np.ndarray, state: np.ndarray, t_end: int):
    """Состояние state[j] действует с times[j] до times[j+1] → список (начало, конец) отрезков True."""
    st = np.asarray(state, bool)
    d = np.diff(np.r_[0, st.astype(int), 0])
    s, e = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    tt = np.r_[times, t_end]
    return [(int(tt[a]), int(tt[b])) for a, b in zip(s, e)]


def build_episodes(h1, h4, d1, t_end):
    k4, k1 = h4["known"].to_numpy(), h1["known"].to_numpy()
    Z4, C4, B4, Y4, R4 = (h4[c].to_numpy() for c in ("zone", "close", "B", "Y", "R"))
    sp4, atr4 = h4["spread"].to_numpy(), h4["atr"].to_numpy()
    j4 = np.searchsorted(k4, k1, side="right") - 1              # последний закрытый 4H на закрытии 1H
    z4_on1 = np.where(j4 >= 0, Z4[np.maximum(j4, 0)], 0)
    Z1 = h1["zone"].to_numpy()
    E = {}
    E["D1"] = [(a, b, -1) for a, b in runs(k4, Z4 == -1, t_end)]
    E["D2"] = [(a, b, -1) for a, b in runs(k4, (Z4 == -1) & (C4 < B4), t_end)]
    E["D3"] = [(a, b, -1) for a, b in runs(k1, (z4_on1 == -1) & (Z1 != 1), t_end)]
    E["U1"] = [(a, b, 1) for a, b in runs(k4, Z4 == 1, t_end)]
    E["U2"] = [(a, b, 1) for a, b in runs(k4, (Z4 == 1) & (C4 > B4), t_end)]
    E["U3"] = [(a, b, 1) for a, b in runs(k1, (z4_on1 == 1) & (Z1 != -1), t_end)]
    f1 = (Z4 == 0) & (sp4 < 0.6)
    f1b = f1 & (np.abs(C4 - B4) <= 2 * atr4)
    for nm, st in (("F1", f1), ("F1b", f1b)):
        E[nm] = [(a, b, s) for a, b in runs(k4, st, t_end) for s in (1, -1)]
    E["F1-inv"] = [(a, b, s) for a, b in runs(k4, ~f1, t_end) for s in (1, -1)]
    for nm in ("D1", "D2", "D3", "U1", "U2", "U3"):
        E[nm + "-inv"] = [(a, b, -s) for a, b, s in E[nm]]
    E["F2"], f2lim = range_v0(h1, h4, t_end)
    E["F2-inv"] = []
    on = sorted({(a, b) for a, b, _ in E["F2"]})
    prev = int(k4[0])
    for a, b in on:                                             # дополнение к F2 — две сетки всё остальное время
        if a > prev:
            E["F2-inv"] += [(prev, a, 1), (prev, a, -1)]
        prev = max(prev, b)
    E["F2-inv"] += [(prev, t_end, 1), (prev, t_end, -1)]
    E["T1"] = touch_blue(h4, d1, t_end)
    E["T1-inv"] = [(a, b, -s) for a, b, s in E["T1"]]
    return E, f2lim


def range_v0(h1, h4, t_end):
    """RANGE v0 GPT (§8.2) ровно как в PREREG: старт на закрытии 4H, отмена по 1H, лимиты третей."""
    G, Y, R, B, A4, C4 = (h4[c].to_numpy() for c in ("G", "Y", "R", "B", "atr", "close"))
    k4 = h4["known"].to_numpy()
    width = (np.maximum(np.maximum(G, Y), R) - np.minimum(np.minimum(G, Y), R)) / A4
    slope = np.abs(B - np.r_[np.full(6, np.nan), B[:-6]]) / A4
    dC = np.abs(np.diff(C4, prepend=np.nan))
    path12 = pd.Series(dC).rolling(12).sum().to_numpy()
    er = np.abs(C4 - np.r_[np.full(12, np.nan), C4[:-12]]) / path12
    ok1 = (width <= 1) & (slope <= 0.5) & (er <= 0.25)
    ok = ok1 & np.r_[False, ok1[:-1]]
    k1 = h1["known"].to_numpy()
    H1h, H1l, H1c, A1 = (h1[c].to_numpy() for c in ("high", "low", "close", "atr"))
    eps, lims = [], {}
    j = 0
    next_ok = 0
    while j < len(k4):
        if not ok[j] or k4[j] < next_ok:
            j += 1
            continue
        t0 = int(k4[j])
        e1 = np.searchsorted(k1, t0, side="right")              # 1H бары с known ≤ t0
        if e1 < 72:
            j += 1
            continue
        lo, hi = H1l[e1 - 72:e1], H1h[e1 - 72:e1]
        L, U = lo.min(), hi.max()
        rng = U - L
        bot, top = lo <= L + 0.1 * rng, hi >= U - 0.1 * rng
        seq, last_t = [], {}
        for q in range(72):
            typ = "B" if (bot[q] and not top[q]) else ("T" if (top[q] and not bot[q]) else None)
            if typ is None:
                continue
            tq = int(k1[e1 - 72 + q])
            if seq and seq[-1] == typ and tq - last_t.get(typ, -10 ** 12) <= 6 * 3600:
                last_t[typ] = tq
                continue
            seq.append(typ)
            last_t[typ] = tq
        changes = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
        if changes < 3:
            j += 1
            continue
        end, out_cnt = t_end, 0                                  # отмена по закрытым 1H после старта
        for q in range(e1, len(k1)):
            b = 0.25 * A1[q]
            far = H1c[q] > U + A1[q] or H1c[q] < L - A1[q]
            out = H1c[q] > U + b or H1c[q] < L - b
            out_cnt = out_cnt + 1 if out else 0
            if far or out_cnt >= 2:
                end = int(k1[q])
                break
        eps += [(t0, end, 1), (t0, end, -1)]
        lims[(t0, 1)] = L + rng / 3
        lims[(t0, -1)] = U - rng / 3
        next_ok = end + 2 * 3600
        j = np.searchsorted(k4, next_ok, side="left")
    return eps, lims


def touch_blue(h4, d1, t_end):
    """T1: 4H low ≤ EMA200, прошлый close выше, дневной режим SMA100 (полоса 0) вверх; шорт до перехода Z4 в +1
    (уточнение до прогона: «становится +1», иначе эпизод вырождается при уже бычьей зоне) или 14 суток."""
    k4, L4, C4, B4, Z4 = (h4[c].to_numpy() for c in ("known", "low", "close", "B", "zone"))
    reg = d1["reg0"]
    eps, j, busy = [], 1, 0
    while j < len(k4):
        t0 = int(k4[j])
        day = t0 // DAY * DAY
        up = reg.get(day, np.nan) == 1.0
        if t0 >= busy and up and L4[j] <= B4[j] and C4[j - 1] > B4[j - 1]:
            end = min(t0 + 14 * DAY, t_end)
            for q in range(j + 1, len(k4)):
                if k4[q] > end:
                    break
                if Z4[q] == 1 and Z4[q - 1] != 1:
                    end = int(k4[q])
                    break
            eps.append((t0, end, -1))
            busy = end
        j += 1
    return eps


def plus_variant(E, h4, t_end):
    """Схема «выключать в плюсе»: входы до конца эпизода, затем крайний срок — противоположная зона Z4 или 14 сут."""
    k4, Z4 = h4["known"].to_numpy(), h4["zone"].to_numpy()
    out = {}
    for nm in ("D1", "U1", "F1"):
        lst = []
        for a, b, s in E[nm]:
            hard = min(b + 14 * DAY, t_end)
            q = np.searchsorted(k4, b, side="left")
            opp = np.flatnonzero(Z4[q:] == -s)
            if len(opp):
                hard = min(hard, int(k4[q + opp[0]]))
            lst.append((a, b, max(hard, b), s))
        out[nm + "+"] = lst
    return out


def period_of(t):
    for p, (a, b) in PERIODS.items():
        if t >= a and (b is None or t < b):
            return p
    return None


def evaluate(mk, eps, cap, lims=None, plus=False, step=0.6, tgt=1.4):
    if plus:
        a = np.array([e[0] for e in eps]); off = np.array([e[1] for e in eps]); b = np.array([e[2] for e in eps])
        s = np.array([e[3] for e in eps])
    else:
        a = np.array([e[0] for e in eps]); b = np.array([e[1] for e in eps]); s = np.array([e[2] for e in eps])
        off = b
    lim = None
    if lims is not None:
        lim = np.array([lims.get((int(x), int(y)), np.nan) for x, y in zip(a, s)])
    res = mk.run(mk.idx(a), mk.idx(b), s, i_off=mk.idx(off), step=step, tgt=tgt, cap=cap, plus=plus, lim=lim)
    return a, off - a, b - a, s, res


def control(mk, a, on_d, tot_d, s, cap, plus, lims_rel, rng, n_ctl, t_end):
    """Случайные начала в пределах периода исходного эпизода; та же длина, сторона, (для F2) та же относительная
    граница входа. → матрица итогов [n_ctl, периоды]."""
    per = np.array([period_of(x) for x in a])
    totals = {p: np.zeros(n_ctl) for p in PERIODS}
    for p in PERIODS:
        msk = per == p
        if not msk.any():
            continue
        lo, hi = PERIODS[p][0], PERIODS[p][1] or t_end
        dd, od, sd = tot_d[msk], on_d[msk], s[msk]
        lr = lims_rel[msk] if lims_rel is not None else None
        for r0 in range(0, n_ctl, 100):
            r1 = min(n_ctl, r0 + 100)
            nr = r1 - r0
            span = np.maximum(hi - dd, lo + 1) - lo
            st = lo + (rng.random((nr, len(dd))) * span).astype(np.int64)
            st, d2, o2, s2 = st.ravel(), np.tile(dd, nr), np.tile(od, nr), np.tile(sd, nr)
            i0, i1, io = mk.idx(st), mk.idx(st + d2), mk.idx(st + o2)
            lim = None
            if lr is not None:
                px0 = mk.o[np.minimum(i0, mk.n - 1)]
                lim = px0 * np.tile(lr, nr)
            res = mk.run(i0, i1, s2, i_off=io, cap=cap, plus=plus, lim=lim)
            totals[p][r0:r1] = res[:, 0].reshape(nr, len(dd)).sum(1)
    return totals


def summarize(nm, a, s, res, ctl, t_end, neigh=None):
    per = np.array([period_of(x) for x in a])
    row = {"rule": nm, "n": int(len(a))}
    net = res[:, 0]
    for p in PERIODS:
        m = per == p
        row[p] = round(float(net[m].sum()), 1)
        row[f"n{p}"] = int(m.sum())
        if ctl is not None:
            c = ctl[p]
            row[f"rank{p}"] = round((int((c >= net[m].sum()).sum()) + 1) / (len(c) + 1), 3)
            row[f"ctl{p}"] = round(float(np.median(c)), 1)
    for p, cut in HALF.items():
        m = per == p
        row[f"{p}1"] = round(float(net[m & (a < cut)].sum()), 1)
        row[f"{p}2"] = round(float(net[m & (a >= cut)].sum()), 1)
    ab = (per == "A") | (per == "B")
    row["AB"] = round(float(net[ab].sum()), 1)
    if ctl is not None:
        c = ctl["A"] + ctl["B"]
        row["rankAB"] = round((int((c >= net[ab].sum()).sum()) + 1) / (len(c) + 1), 3)
        row["ctlAB_med"] = round(float(np.median(c)), 1)
        row["ctlAB_10_90"] = [round(float(np.quantile(c, .1)), 1), round(float(np.quantile(c, .9)), 1)]
    x = net[ab]
    if len(x) > 1:
        se = x.std(ddof=1) / np.sqrt(len(x))
        row["ci95_ep_AB"] = [round(float(x.mean() - 1.96 * se), 2), round(float(x.mean() + 1.96 * se), 2)]
    parts = {"tp": res[:, 1], "exit": res[:, 4], "fees": -res[:, 2], "fund": -res[:, 3]}
    row["parts_AB"] = {k: round(float(v[ab].sum()), 1) for k, v in parts.items()}
    row["worst_ep"] = round(float(net.min()), 1)
    row["min_dd_ep"] = round(float(res[:, 6].min()), 1)
    if neigh is not None:
        row["neigh_AB"] = neigh
    gates = [all(row[p] > 0 for p in PERIODS), all(row[k] > 0 for k in ("A1", "A2", "B1", "B2")),
             row.get("rankAB", 1) <= 0.05, neigh is not None and all(v > 0 for v in neigh.values()),
             "ci95_ep_AB" in row and row["ci95_ep_AB"][0] > 0]
    row["gates"] = gates
    row["verdict"] = "КАНДИДАТ" if all(gates) else "не квалифицировано"
    return row


def main():
    t_start = time.time()
    m, h1, h4, d1, fund = md.build()
    t_end = int(m["ts"].iloc[-1]) + 60
    mk = gridk.Market(m["ts"].to_numpy(), m["open"].to_numpy(), m["high"].to_numpy(), m["low"].to_numpy(),
                      m["close"].to_numpy(), fund)
    E, f2lim = build_episodes(h1, h4, d1, t_end)
    P = plus_variant(E, h4, t_end)
    lo = PERIODS["A"][0]
    for k in list(E):
        E[k] = [e for e in E[k] if e[0] >= lo and e[1] > e[0]]
    for k in list(P):
        P[k] = [e for e in P[k] if e[0] >= lo and e[1] > e[0]]
    rng = np.random.default_rng(20261102)
    rows = []
    names = [k for k in E if ONLY is None or k in ONLY] + [k for k in P if ONLY is None or k in ONLY]
    for nm in names:
        plus = nm.endswith("+")
        eps = P[nm] if plus else E[nm]
        two = nm.startswith("F")
        cap = CAP2 if two else CAP1
        lims = f2lim if nm == "F2" else None
        a, on_d, tot_d, s, res = evaluate(mk, eps, cap, lims, plus)
        lims_rel = None
        if lims is not None:
            px0 = mk.o[np.minimum(mk.idx(a), mk.n - 1)]
            lims_rel = np.array([f2lim[(int(x), int(y))] for x, y in zip(a, s)]) / px0
        ctl = control(mk, a, on_d, tot_d, s, cap, plus, lims_rel, rng, N_CTL, t_end) if N_CTL > 0 else None
        neigh = {}
        per = np.array([period_of(x) for x in a])
        ab = (per == "A") | (per == "B")
        for st, tg in NEIGH:
            _, _, _, _, r2 = evaluate(mk, eps, cap, lims, plus, st, tg)
            neigh[f"{st:g}/{tg:g}"] = round(float(r2[ab, 0].sum()), 1)
        row = summarize(nm, a, s, res, ctl, t_end, neigh)
        row["days_on"] = round(float(on_d.sum() / DAY / (2 if two else 1)), 0)
        rows.append(row)
        print(f"{nm:7s} n={row['n']:4d} A {row['A']:+9.1f} (r{row.get('rankA', '-')}) B {row['B']:+9.1f} "
              f"(r{row.get('rankB', '-')}) C {row['C']:+8.1f} (r{row.get('rankC', '-')}) | A∪B {row['AB']:+9.1f} "
              f"ранг {row.get('rankAB', '-')} контроль {row.get('ctlAB_med', '-')} | половины {row['A1']:+.0f}/"
              f"{row['A2']:+.0f}/{row['B1']:+.0f}/{row['B2']:+.0f} | {row['parts_AB']} | соседи {list(neigh.values())}"
              f" | {row['verdict']}  [{time.time() - t_start:.0f}s]", flush=True)
    base = baselines(mk, d1, t_end)
    out = HERE / "out"
    out.mkdir(exist_ok=True)
    tag = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--tag=")), None)
    tag = ("_" + tag) if tag else ("" if ONLY is None else "_" + "_".join(ONLY))
    (out / f"regime_rules_result{tag}.json").write_text(json.dumps({"rules": rows, "baselines": base,
                                                                     "n_ctl": N_CTL}, ensure_ascii=False, indent=1))


def baselines(mk, d1, t_end):
    """Постоянные варианты по периодам (один эпизод на период, остаток закрыт в конце периода) и SMA100 ±2%."""
    out = {}
    for p, (a, b) in PERIODS.items():
        b = b or t_end
        i0, i1 = mk.idx([a]), mk.idx([b])
        L = mk.run(i0, i1, 1, cap=CAP1)[0]
        S = mk.run(i0, i1, -1, cap=CAP1)[0]
        L2 = mk.run(i0, i1, 1, cap=CAP2)[0]
        S2 = mk.run(i0, i1, -1, cap=CAP2)[0]
        reg = d1["reg2"]
        rr = reg[(reg.index >= a) & (reg.index < b)].fillna(0).to_numpy() == 1.0
        days = reg[(reg.index >= a) & (reg.index < b)].index.to_numpy()
        seg = runs(days, rr, b)
        if seg:
            sm = mk.run(mk.idx([x for x, _ in seg]), mk.idx([y for _, y in seg]), 1, cap=CAP1)
            smv = float(sm[:, 0].sum())
        else:
            smv = 0.0
        out[p] = {"всегда лонг": round(float(L[0]), 1), "всегда шорт": round(float(S[0]), 1),
                  "всегда две ($3k+$3k)": round(float(L2[0] + S2[0]), 1), "лонг по SMA100 ±2%": round(smv, 1),
                  "мешок лонга в конце": round(float(L[5]), 1), "просадка лонга": round(float(L[6]), 1)}
        print(f"база {p}: {out[p]}", flush=True)
    return out


if __name__ == "__main__":
    main()
