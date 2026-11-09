"""Те же правила на других таймфреймах (задание оператора 07.11): линии, закрепление и ATR считаются на барах самого таймфрейма, те же длины, те же 2 закрытия. Издержка та же 0.068% на сторону, фандинг по цене выплаты. Судья BTC; ETH, Bitstamp, XRP и монеты показаны как справка, не как запрет.
Варианты: простое R, Простое+ (ранг и вес от ATR100 за год баров этого таймфрейма), Простое+ и шорт под жёлтой полным весом (cs)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import entry_rules as er  # noqa: E402
import ledger as lg  # noqa: E402
import state_map as sm  # noqa: E402
import words3_sweep as ws  # noqa: E402

pd.set_option("display.width", 220, "display.max_columns", 30, "display.max_rows", 200)
OUT = Path(__file__).parent / "out"
SC = lg.SIDE_COST
PER = (("18–21", "2018-01-01", "2022-01-01"), ("22–07.24", "2022-01-01", "2024-08-01"), ("08.24–26", "2024-08-01", "2027-01-01"))
CUT25 = sm.T("2025-01-01")


def ema(x, n):
    return pd.Series(x).ewm(alpha=2 / (n + 1), adjust=False).mean().to_numpy()


def tema(x, n):
    a = ema(x, n)
    b = ema(a, n)
    return 3 * a - 3 * b + ema(b, n)


def runlen(d):
    s = np.sign(d).astype(int)
    out = np.zeros(len(s), dtype=int)
    cur = 0
    for i, v in enumerate(s):
        cur = cur + v if (v != 0 and np.sign(cur) == v) else v
        out[i] = cur
    return out


def resample(ts, o, h, l, c, tf):
    k = ts // tf
    u, first = np.unique(k, return_index=True)
    last = np.r_[first[1:], len(k)] - 1
    return (u + 1) * tf, o[first], np.maximum.reduceat(h, first), np.minimum.reduceat(l, first), c[last]


def prep(t, o, h, l, c, fm, start, tf):
    G, Y, R, B = tema(c, 50), tema(c, 100), tema(c, 200), ema(c, 200)
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr = np.full(len(c), np.nan)
    atr[99] = tr[:100].mean()
    for i in range(100, len(c)):
        atr[i] = (atr[i - 1] * 99 + tr[i]) / 100
    V = pd.Series(atr / c)
    N = int(365 * 86400 / tf)
    rk = V.rolling(N + 1, min_periods=N // 2).rank(pct=True).to_numpy()
    med = V.rolling(N, min_periods=min(500, N // 4)).median().shift(1).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        W = np.clip(med / V.to_numpy(), 0.5, 2.0)
    W = np.where(np.isfinite(W), W, 1.0)
    return dict(t=t, o=o, h=h, l=l, c=c, fm=fm, B=B, rG=runlen(c - G), rY=runlen(c - Y), rR=runlen(c - R), rk=rk, W=W, i0=int(np.searchsorted(t, start)))


def run(S, plus=False, cs=None):
    t, o, h, l, c, B = S["t"], S["o"], S["h"], S["l"], S["c"], S["B"]
    rG, rY, rR, rk, W = S["rG"], S["rY"], S["rR"], S["rk"], S["W"]
    legs, side, ie, pe, we, tag = [], 0, 0, 0.0, 1.0, ""
    for i in range(S["i0"], len(t)):
        if side == -1 and tag == "cs":
            lv = B[i - 1] * 1.005
            if l[i] <= lv < pe:
                legs.append((ie, i, pe, float(min(lv, o[i])), -1, we))
                side = 0
        if side == 1 and rR[i] <= -2:
            legs.append((ie, i, pe, float(c[i]), 1, we))
            side = 0
        elif side == -1 and ((tag == "S" and rG[i] >= 2) or (tag == "cs" and rY[i] >= 2)):
            legs.append((ie, i, pe, float(c[i]), -1, we))
            side = 0
        if side != 0:
            continue
        w0 = W[i] / 1.18 if plus else 1.0
        if c[i] > B[i]:
            if rG[i] >= 2 and rR[i] > -2:
                side, ie, pe, we, tag = 1, i, float(c[i]), w0, "L"
            elif cs is not None and rY[i] == -2 and c[i] > B[i] * 1.005:
                side, ie, pe, we, tag = -1, i, float(c[i]), w0 * cs, "cs"
        elif rG[i] <= -2 and rG[i] < 0 and (not plus or not rk[i] > 0.6):
            side, ie, pe, we, tag = -1, i, float(c[i]), w0, "S"
    if side != 0:
        legs.append((ie, len(t) - 1, pe, float(c[-1]), side, we))
    return legs


def stats(S, legs):
    t, c, fm = S["t"], S["c"], S["fm"]
    a = np.array(legs, dtype=float)
    i0, i1, p0, p1, s, w = a[:, 0].astype(int), a[:, 1].astype(int), a[:, 2], a[:, 3], a[:, 4], a[:, 5]
    v = w * (s * (p1 / p0 - 1) - SC - SC * p1 / p0 - s * (fm[i1] - fm[i0]) / p0) * 100
    n = len(t)
    closed, op = np.zeros(n), np.zeros(n)
    np.add.at(closed, i1, v)
    for x0, x1, q0, sg, wv in zip(i0, i1, p0, s, w):
        if x1 > x0:
            k = np.arange(x0, x1)
            op[k] += wv * (sg * (c[k] / q0 - 1) - SC - SC * c[k] / q0 - sg * (fm[k] - fm[x0]) / q0) * 100
    eq = (np.cumsum(closed) + op)[S["i0"]:]
    dd = float((eq - np.maximum.accumulate(np.r_[0.0, eq])[1:]).min())
    t0 = t[i0]
    out = {"n": len(v), "в_год": round(len(v) / ((t[-1] - t[S["i0"]]) / 31557600)), "итог": round(float(v.sum()), 1), "просадка": round(dd, 1), "отн": round(float(v.sum()) / max(abs(dd), 1.0), 2), "лонг": round(float(v[s == 1].sum())), "шорт": round(float(v[s == -1].sum())), "с2025": round(float(v[t0 >= CUT25].sum()), 1), "плюс_%": round(float((v > 0).mean() * 100)), "издержки": round(float((w * (SC + SC * p1 / p0)).sum() * 100))}
    for lab, x, z in PER:
        out[lab] = round(float(v[(t0 >= sm.T(x)) & (t0 < sm.T(z))].sum()))
    return out


VARS = (("простое R", dict()), ("Простое+", dict(plus=True)), ("Простое+ и cs вес 1", dict(plus=True, cs=1.0)))


def minutes_block(name, m, fund, rows):
    ts = m["ts"].to_numpy(np.int64)
    o, h, l, c = m["open"].to_numpy(float), m["high"].to_numpy(float), m["low"].to_numpy(float), m["close"].to_numpy(float)
    for tf, nm in ((14400, "4ч"), (3600, "1ч"), (900, "15м")):
        t, oo, hh, ll, cc = resample(ts, o, h, l, c, tf)
        fm = lg.funding_marks({"t": t, "c": cc}, fund)
        S = prep(t, oo, hh, ll, cc, fm, sm.T("2018-01-01"), tf)
        for lab, kw in VARS:
            rows.append({"ряд": name, "ТФ": nm, "вариант": lab, **stats(S, run(S, **kw))})
        print(name, nm, "готово", flush=True)


def main():
    rows = []
    m, _, _, _, fund = cw.load()
    minutes_block("BTC", m, fund, rows)
    del m
    m2, _, _, _, fund2 = pd.read_pickle(er.ETH_PKL)
    minutes_block("ETH", m2, fund2, rows)
    del m2
    d = pd.DataFrame(rows)
    show = ["ряд", "ТФ", "вариант", "n", "в_год", "итог", "просадка", "отн", "лонг", "шорт", "с2025", "плюс_%", "издержки", "18–21", "22–07.24", "08.24–26"]
    print(d[show].to_string(index=False), flush=True)
    r2 = []
    for k, grp, a, f in ws.series():
        if k in ("BTC", "ETH"):
            continue
        for tf, nm in ((3600, "1ч"), (14400, "4ч")):
            if tf == 3600:
                t, oo, hh, ll, cc, fm = a["t"], a["o"], a["h"], a["l"], a["c"], f
            else:
                t, oo, hh, ll, cc = resample(a["t"] - 3600, a["o"], a["h"], a["l"], a["c"], tf)
                idx = np.clip(np.searchsorted(a["t"], t, side="right") - 1, 0, len(f) - 1)
                fm = f[idx]
            S = prep(t, oo, hh, ll, cc, fm, int(a["t"][a["i0"]]), tf)
            for lab, kw in VARS:
                r2.append({"ряд": k, "группа": grp, "ТФ": nm, "вариант": lab, **stats(S, run(S, **kw))})
    e = pd.DataFrame(r2)
    pd.concat([d, e]).to_csv(OUT / "btc_tf.csv", index=False)
    print(e[e["группа"] == "основные"][["ряд", "ТФ", "вариант", "n", "итог", "просадка", "с2025"]].to_string(index=False), flush=True)
    mm = e[e["группа"] == "монеты"]
    s = mm.groupby(["ТФ", "вариант"], sort=False).agg(итог=("итог", "sum"), в_плюсе=("итог", lambda x: int((x > 0).sum())), просадка_мед=("просадка", "median"), с2025=("с2025", "sum"), сделок=("n", "sum")).round(0)
    print(s.to_string(), flush=True)


if __name__ == "__main__":
    main()
