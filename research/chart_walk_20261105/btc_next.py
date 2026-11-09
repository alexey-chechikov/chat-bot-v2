"""Только биткоин, основа Простое+ и шорт под жёлтой вес 1 (+563 / −41). Судья: три периода Binance и Bitstamp 2014–17.
1. Добор на подтверждении: входы и выходы те же, первый лот a, при ходе X ATR от входа добавляется лот b по уровню или открытию часа, выход общий. ATR — ATR14 4ч на входе. Шорт под жёлтой не трогается.
2. Шорт под жёлтой отдельным потоком: открывается и при открытом лонге; основной поток как Простое+.
3. Те же правила на 6, 8, 12 часах и дне.
4. Основной шорт только при ранге среднего фандинга за 3 дня не ниже порога. На Bitstamp фандинга нет, фильтра там нет."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import btc_lab as bl  # noqa: E402
import btc_tf as tf  # noqa: E402
import cw_data as cw  # noqa: E402
import ledger as lg  # noqa: E402
import plus as pl  # noqa: E402
import state_map as sm  # noqa: E402

pd.set_option("display.width", 220, "display.max_columns", 30, "display.max_rows", 150, "display.max_colwidth", 50)
OUT = bl.OUT


def pyramid(a, legs, xl, xs, first, add):
    """Разложить основные сделки на два лота. Вход и выход те же. Уровень проверяется с часа после входа до часа перед выходом."""
    h, l, o, atr = a["h"], a["l"], a["o"], a["atr4"]
    out = []
    for x in legs:
        i0, i1, p0, p1, s, tag, why, w = x
        if tag == "S cs":
            out.append(x)
            continue
        out.append((i0, i1, p0, p1, s, tag, why, w * first))
        X = xl if s == 1 else xs
        if X is None:
            continue
        lv = p0 + s * X * atr[i0]
        rng = np.arange(i0 + 1, i1)
        if len(rng) == 0:
            continue
        hit = (h[rng] >= lv) if s == 1 else (l[rng] <= lv)
        if hit.any():
            k = int(rng[int(np.argmax(hit))])
            px = float(max(lv, o[k]) if s == 1 else min(lv, o[k]))
            out.append((k, i1, px, p1, s, tag + " добор", why, w * add))
    return out


def peak(legs, n):
    d = np.zeros(n + 1)
    for x in legs:
        d[x[0]] += x[7]
        d[x[1]] -= x[7]
    return round(float(np.cumsum(d).max()), 2)


def cs_stream(a, lay, wt, cut=None, tol=0.005):
    t, c, l, o, j, B = a["t"], a["c"], a["l"], a["o"], a["j"], a["f_B"]
    Bp, rY, F = a["B4p"], a["f_run_Y"], a["f_close"]
    _, W = lay
    n = len(t) if cut is None else int(np.searchsorted(t, cut, side="right"))
    legs, on, ie, pe, we, jp = [], False, 0, 0.0, 1.0, -1
    for i in range(a["i0"], n):
        new4 = j[i] != jp
        jp = j[i]
        if on:
            lv = Bp[i] * (1 + tol)
            if l[i] <= lv < pe:
                legs.append((ie, i, pe, float(min(lv, o[i])), -1, "S cs поток", "цель", we))
                on = False
            elif new4 and rY[i] >= 2:
                legs.append((ie, i, pe, float(c[i]), -1, "S cs поток", "отмена", we))
                on = False
        if not on and new4 and F[i] > B[i] and rY[i] == -2 and c[i] > B[i] * (1 + tol):
            on, ie, pe, we = True, i, float(c[i]), W[i] / pl.DIV * wt
    if on:
        legs.append((ie, n - 1, pe, float(c[n - 1]), -1, "S cs поток", "конец", we))
    return legs


def line(lab, a, f, b, fb, la, lb, extra=None):
    s = bl.row(a, f, la)
    sb = pl.stats(b, fb, lb)
    return {"вариант": lab, **s, "Bitstamp": sb["итог"], "Bs_пр": sb["просадка"], "пик": peak(la, len(a["t"])), **(extra or {})}


def main():
    (a, f, lay), (b, fb, layb) = bl.load()
    C = {"cs": 1.0}
    la0, lb0 = bl.run(a, lay, cut=bl.CUT, rules=C), bl.run(b, layb, rules=C)
    rows = [line("база: Простое+ и шорт под жёлтой", a, f, b, fb, la0, lb0)]
    for first, add in ((1.0, 0.5), (1.0, 1.0), (0.75, 0.5), (0.75, 1.0), (0.5, 0.5), (0.5, 1.0), (0.5, 1.5)):
        for xl, xs in ((2, 2), (3, 2), (3, 3), (4, 2), (4, 3), (5, 3), (6, 3), (4, None), (None, 3)):
            lab = f"первый {first}, добор {add}, лонг +{xl}, шорт +{xs}"
            rows.append(line(lab, a, f, b, fb, pyramid(a, la0, xl, xs, first, add), pyramid(b, lb0, xl, xs, first, add)))
    d = pd.DataFrame(rows)
    d.to_csv(OUT / "btc_next_pyramid.csv", index=False)
    show = ["вариант", "n", "итог", "просадка", "отн", "с2025", "18–21", "22–07.24", "08.24–26", "Bitstamp", "Bs_пр", "пик"]
    print(f"== 1. добор на подтверждении, вариантов {len(d) - 1}, база и лучшие 10 по итог/просадка", flush=True)
    print(pd.concat([d.head(1), d.iloc[1:].sort_values("отн", ascending=False).head(10)])[show].to_string(index=False), flush=True)
    print("доля вариантов лучше базы по итог/просадка:", round(float((d["отн"].iloc[1:] > d["отн"].iloc[0]).mean() * 100)), "%; и Bitstamp не хуже:", round(float(((d["отн"].iloc[1:] > d["отн"].iloc[0]) & (d["Bitstamp"].iloc[1:] / d["Bs_пр"].iloc[1:].abs() >= d["Bitstamp"].iloc[0] / abs(d["Bs_пр"].iloc[0]))).mean() * 100)), "%", flush=True)

    print("== 2. шорт под жёлтой отдельным потоком, может идти вместе с лонгом", flush=True)
    la1, lb1 = bl.run(a, lay, cut=bl.CUT), bl.run(b, layb)
    rows = [line("Простое+ без него", a, f, b, fb, la1, lb1), line("в общем слоте, вес 1", a, f, b, fb, la0, lb0)]
    for wt in (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0):
        rows.append(line(f"отдельный поток, вес {wt}", a, f, b, fb, la1 + cs_stream(a, lay, wt, bl.CUT), lb1 + cs_stream(b, layb, wt)))
    for wt in (1.5, 2.0, 3.0):
        rows.append(line(f"в общем слоте, вес {wt}", a, f, b, fb, bl.run(a, lay, cut=bl.CUT, rules={"cs": wt}), bl.run(b, layb, rules={"cs": wt})))
    q = pd.DataFrame(rows)
    q.to_csv(OUT / "btc_next_stream.csv", index=False)
    print(q[show].to_string(index=False), flush=True)

    print("== 4. основной шорт по фандингу, поверх базы", flush=True)
    _, _, _, _, fund = cw.load()
    fs = pd.Series(fund.to_numpy(float))
    avg = fs.rolling(9, min_periods=3).mean()
    rk = avg.rolling(1096, min_periods=270).rank(pct=True).to_numpy()
    idx = np.searchsorted(fund.index.to_numpy(np.int64), a["t"], side="right") - 1
    hr = np.where(idx >= 0, rk[np.clip(idx, 0, None)], np.nan)
    rows = [line("база", a, f, b, fb, la0, lb0)]
    for th in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7):
        sok = ~(hr < th)
        rows.append(line(f"шорт при ранге фандинга от {th}", a, f, b, fb, bl.run(a, lay, cut=bl.CUT, rules=C, sok=sok), lb0))
    q = pd.DataFrame(rows)
    q.to_csv(OUT / "btc_next_funding.csv", index=False)
    print(q[["вариант", "n", "итог", "просадка", "отн", "с2025", "18–21", "22–07.24", "08.24–26"]].to_string(index=False), flush=True)

    print("== 3. те же правила на старших таймфреймах, BTC и Bitstamp", flush=True)
    m, _, _, _, fund = cw.load()
    ts = m["ts"].to_numpy(np.int64)
    o, h, l, c = m["open"].to_numpy(float), m["high"].to_numpy(float), m["low"].to_numpy(float), m["close"].to_numpy(float)
    del m
    rows = []
    TF = ((14400, "4ч"), (21600, "6ч"), (28800, "8ч"), (43200, "12ч"), (86400, "1д"))
    for sec, nm in TF:
        t, oo, hh, ll, cc = tf.resample(ts, o, h, l, c, sec)
        fm = lg.funding_marks({"t": t, "c": cc}, fund)
        S = tf.prep(t, oo, hh, ll, cc, fm, sm.T("2018-01-01"), sec)
        for lab, kw in tf.VARS:
            rows.append({"ряд": "BTC", "ТФ": nm, "вариант": lab, **tf.stats(S, tf.run(S, **kw))})
        t, oo, hh, ll, cc = tf.resample(b["t"] - 3600, b["o"], b["h"], b["l"], b["c"], sec)
        ix = np.clip(np.searchsorted(b["t"], t, side="right") - 1, 0, len(fb) - 1)
        S = tf.prep(t, oo, hh, ll, cc, fb[ix], int(b["t"][b["i0"]]), sec)
        for lab, kw in tf.VARS:
            rows.append({"ряд": "Bitstamp", "ТФ": nm, "вариант": lab, **tf.stats(S, tf.run(S, **kw))})
    e = pd.DataFrame(rows)
    e.to_csv(OUT / "btc_next_tf.csv", index=False)
    print(e[e["ряд"] == "BTC"][["ТФ", "вариант", "n", "в_год", "итог", "просадка", "отн", "с2025", "издержки", "18–21", "22–07.24", "08.24–26"]].to_string(index=False), flush=True)
    print(e[e["ряд"] == "Bitstamp"][["ТФ", "вариант", "n", "итог", "просадка", "отн"]].to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
