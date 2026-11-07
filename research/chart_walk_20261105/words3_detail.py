"""Подробности по кандидатам из просчёта записок 06.11: его окна, годы, контроль сдвигом, сверка с его точками; статистика отрывов от зелёной и локальный шорт от отрыва."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import ledger as lg  # noqa: E402
import pos  # noqa: E402
import state_map as sm  # noqa: E402
import words2 as w2  # noqa: E402
import words3 as w3  # noqa: E402
import words3_look as wl  # noqa: E402

pd.set_option("display.width", 280, "display.max_columns", 40, "display.max_rows", 300)
S0 = dict(l_align=False, s_align=False)
CANDS = {"A+2/6": None, "G: выход под зелёной": {**S0}, "R: выход под красной": {**S0, "l_exit": "R"}, "G+добор 3": {**S0, "add": True, "add_far": 3.0}, "Y+добор 3": {**S0, "l_exit": "Y", "add": True, "add_far": 3.0}}
WINS = (("1 пила 23.02–06.04.26", "2026-02-23", "2026-04-06"), ("2 падение 12.01–23.02.26", "2026-01-12", "2026-02-23"), ("3 стоит 04.08–22.09.25", "2025-08-04", "2025-09-22"), ("4 30.12.24–17.02.25", "2024-12-30", "2025-02-17"), ("5 конец роста 27.10–28.11.25", "2025-10-27", "2025-11-28"), ("6 рост 14.10–25.11.24", "2024-10-14", "2024-11-25"), ("его флет 10–21.07.26", "2026-07-10", "2026-07-21"), ("декабрь 2024", "2024-12-01", "2024-12-31"))
PERIODS = (("2018–21", "2018-01-01", "2022-01-01"), ("2022–07.24", "2022-01-01", "2024-08-01"), ("08.24–26", "2024-08-01", "2027-01-01"))


def legs_of(a, kw):
    return w2.run(a, **w2.MAIN26) if kw is None else w3.run(a, **kw)


def rs(fm, legs):
    return np.array([w2.net(fm, x) * (x[7] if len(x) > 7 else 1.0) for x in legs])


def windows(a, fm):
    t = a["t"]
    rows = []
    for lab, kw in CANDS.items():
        legs = legs_of(a, kw)
        r = rs(fm, legs)
        t0 = t[np.array([x[0] for x in legs])]
        row = {"вариант": lab}
        for nm, x, z in WINS:
            m = (t0 >= sm.T(x)) & (t0 < sm.T(z))
            row[nm.split(" ")[0] + ("" if nm[0].isdigit() else " " + nm.split(" ")[1])] = f"{r[m].sum():+.1f}/{int(m.sum())}"
        rows.append(row)
    return pd.DataFrame(rows)


def years(a, fm):
    t = a["t"]
    rows = []
    for lab, kw in CANDS.items():
        legs = legs_of(a, kw)
        r = rs(fm, legs)
        t0 = pd.to_datetime(t[np.array([x[0] for x in legs])], unit="s").year
        rows.append({"вариант": lab, **{int(y): round(float(r[t0 == y].sum())) for y in sorted(set(t0))}})
    return pd.DataFrame(rows)


def periods(k, a, fm):
    t = a["t"]
    rows = []
    for lab, kw in CANDS.items():
        legs = legs_of(a, kw)
        r = rs(fm, legs)
        t0 = t[np.array([x[0] for x in legs])]
        row = {"ряд": k, "вариант": lab, **w3.stats(a, fm, legs)}
        for nm, x, z in PERIODS:
            row[nm] = round(float(r[(t0 >= sm.T(x)) & (t0 < sm.T(z))].sum()))
        if kw is None or not kw.get("add"):
            sh = lg.shift_rank(a, fm, [x[:5] for x in legs])
            row["лучше_сдвигов_%"] = sh["всё"]["лучше_%"]
            row["лонг_%"], row["шорт_%"] = sh["лонг"]["лучше_%"], sh["шорт"]["лучше_%"]
        rows.append(row)
    return rows


def departures(k, a, fm):
    """Отрыв: цена над синей и закреплена над зелёной, максимум часа ушёл на X ATR над зелёной первый раз после касания зелёной."""
    c, h, l, G, Y, B, atr, rg, F = a["c"], a["h"], a["l"], a["f_G"], a["f_Y"], a["f_B"], a["atr4"], a["f_run_G"], a["f_close"]
    n = len(c)
    rows, shorts = [], []
    yrs = (a["t"][-1] - a["t"][a["i0"]]) / 86400 / 365.25
    for X in (2, 3, 4, 5, 6, 8):
        ok = True
        ev = []
        for i in range(a["i0"], n):
            if l[i] <= G[i]:
                ok = True
            if ok and F[i] > B[i] and rg[i] >= 2 and h[i] >= G[i] + X * atr[i] and c[i] > G[i]:
                ev.append(i)
                ok = False
        back5, back10, back20, under_y, more, days = [], [], [], [], [], []
        sh = []
        for i in ev:
            lim = min(i + 20 * 24, n - 1)
            touch = next((q for q in range(i + 1, lim + 1) if l[q] <= G[q]), None)
            back5.append(touch is not None and touch - i <= 5 * 24)
            back10.append(touch is not None and touch - i <= 10 * 24)
            back20.append(touch is not None)
            top = h[i + 1:(touch or lim) + 1].max() if (touch or lim) > i else h[i]
            more.append((top - c[i]) / atr[i])
            if touch is not None:
                days.append((touch - i) / 24)
            under_y.append(any(F[q] < Y[q] for q in range(i + 1, min(i + 10 * 24, n - 1) + 1)))
            p0 = float(c[i])
            st = p0 + 2 * atr[i]
            for q in range(i + 1, min(i + 20 * 24, n - 1) + 1):
                if h[q] >= st:
                    sh.append((i, q, p0, float(max(st, a["o"][q])), -1))
                    break
                if l[q] <= G[q] + 0.25 * atr[q] and G[q] + 0.25 * atr[q] < p0:
                    sh.append((i, q, p0, float(min(G[q] + 0.25 * atr[q], a["o"][q])), -1))
                    break
            else:
                q = min(i + 20 * 24, n - 1)
                sh.append((i, q, p0, float(c[q]), -1))
        if not ev:
            continue
        rows.append({"ряд": k, "X_ATR": X, "событий": len(ev), "в_год": round(len(ev) / yrs, 1), "к_зелёной_5д_%": round(np.mean(back5) * 100), "10д_%": round(np.mean(back10) * 100), "20д_%": round(np.mean(back20) * 100), "дней_медиана": round(float(np.median(days)), 1) if days else None, "выше_ещё_ATR_медиана": round(float(np.median(more)), 1), "под_жёлтой_10д_%": round(np.mean(under_y) * 100)})
        rr = np.array([w2.net(fm, x) for x in sh])
        t0 = a["t"][np.array([x[0] for x in sh])]
        shorts.append({"ряд": k, "X_ATR": X, "n": len(rr), "итог": round(float(rr.sum()), 1), "на_сделку": round(float(rr.mean()), 2), "плюс_%": round(float((rr > 0).mean() * 100)), "с2025": round(float(rr[t0 >= w3.CUT].sum()), 1)})
    return rows, shorts


def main():
    S = wl.series()
    k, a, f = S[0]
    print(windows(a, f).to_string(index=False), flush=True)
    print(years(a, f).to_string(index=False), flush=True)
    for lab, kw in CANDS.items():
        if kw is not None:
            rc = w3.recall(a, legs_of(a, kw))
            print(lab, "его точки:", int(rc["совпало"].sum()), "из", len(rc), flush=True)
            if lab.startswith("G:"):
                print(rc.drop(columns=["причина"]).to_string(index=False), flush=True)
    rows, drows, srows = [], [], []
    for k, a, f in S:
        rows += periods(k, a, f)
        d, s = departures(k, a, f)
        drows += d
        srows += s
        print(k, "готово", flush=True)
    out = pd.DataFrame(rows)
    out.to_csv(pos.OUT / "w3_cands.csv", index=False)
    print(out.to_string(index=False), flush=True)
    dd, ss = pd.DataFrame(drows), pd.DataFrame(srows)
    dd.to_csv(pos.OUT / "w3_departures.csv", index=False)
    ss.to_csv(pos.OUT / "w3_far_short.csv", index=False)
    print(dd.to_string(index=False), flush=True)
    print(ss.to_string(index=False), flush=True)
    a = S[0][1]
    for ts in ("2025-08-11 12:00", "2026-01-15 00:00", "2024-11-13 00:00", "2024-12-16 00:00"):
        i = int(np.searchsorted(a["t"], sm.T(ts)))
        hi = a["h"][max(i - 36, 0):i + 36]
        print(ts, "максимум рядом", round(float(hi.max())), "над зелёной ATR", round(float((hi.max() - a["f_G"][i]) / a["atr4"][i]), 1), flush=True)


if __name__ == "__main__":
    main()
