"""Его новые сетапы из записок 4–6 сами по себе, со своими целями и отменами, без автомата: сколько раз случались на истории и что дали. По одной сделке одного сетапа за раз.
S1 — первое закрепление под зелёной после роста, 1ч под красной, зелёная далеко от жёлтой и красной. Под голубой 4ч цель красная 4ч, над ней голубая 1ч. Отмена: 2 закрытия над зелёной, если она над жёлтой, иначе над жёлтой.
M1 — зеркало S1 вверх: он его не называл, считается для сравнения.
S2 — шорт от голубой 4ч: касание снизу, первое закрытие 4ч под ней. Красная ниже входа: цель красная, отмена над жёлтой. Красная выше входа: отмена 2 закрытия над красной.
L1 — лонг к голубой 4ч: те же входы, что в автомате; разбивка по цветным и расстоянию до цели."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import entry_common as ec  # noqa: E402
import ledger as lg  # noqa: E402
import pos  # noqa: E402
import words2 as w2  # noqa: E402

pd.set_option("display.width", 260, "display.max_columns", 40, "display.max_rows", 300)
TOL = 0.5


def place(a, i):
    fc, b, b1 = a["f_close"][i], a["f_B"][i], a["f_B1"][i]
    return "над обеими" if fc > b and fc > b1 else ("под обеими" if fc < b and fc < b1 else "между")


def s1_events(a, k, m=6, mirror=False):
    """Часы, где впервые выполнилось: k4 закрытия за зелёной, k1 закрытий 1ч за красной, до этого m закрытий по другую сторону, веер шире k ATR."""
    sg = -1 if mirror else 1
    c, j, atr = a["c"], a["j"], a["atr4"]
    G, Y, R = a["f_G"], a["f_Y"], a["f_R"]
    rg, r1 = a["f_run_G"] * sg, a["run_R"] * sg
    out, armed, jp, side_run = [], False, -1, 0
    for i in range(a["i0"], len(c)):
        if j[i] != jp:
            jp = j[i]
            if rg[i] >= m:
                armed = True
        if armed and rg[i] <= -2 and r1[i] <= -3:
            armed = False
            if sg * (G[i] - Y[i]) >= k * atr[i] and sg * (G[i] - R[i]) >= k * atr[i]:
                out.append(i)
    return out


def manage_s1(a, i, mirror=False, tgt_mode="его"):
    s = 1 if mirror else -1
    c, h, l, o, j = a["c"], a["h"], a["l"], a["o"], a["j"]
    G, Y, R, B = a["f_G"], a["f_Y"], a["f_R"], a["f_B"]
    rg, ry = a["f_run_G"], a["f_run_Y"]
    Rp = np.r_[R[0], R[:-1]]
    B1p = np.r_[a["B1h"][0], a["B1h"][:-1]]
    p0, jp = c[i], j[i]
    use_b1 = tgt_mode == "его" and (a["f_close"][i] > B[i] if not mirror else a["f_close"][i] < B[i])
    for e in range(i + 1, len(c)):
        new4 = j[e] != jp
        jp = j[e]
        lv = (B1p[e] if use_b1 else Rp[e]) * (1 - s * TOL / 100)
        if s == -1 and l[e] <= lv < p0:
            return e, min(lv, o[e]), "цель"
        if s == 1 and h[e] >= lv > p0:
            return e, max(lv, o[e]), "цель"
        if new4:
            if s == -1 and rg[e] >= 2 and ry[e] >= 2:
                return e, c[e], "отмена"
            if s == 1 and rg[e] <= -2 and ry[e] <= -2:
                return e, c[e], "отмена"
    return len(c) - 1, c[-1], "конец"


def s2_events(a, m=6):
    """Шорт от голубой: цена k закрытий 4ч была под голубой, касание снизу (хай ≥ голубая −0.5%), затем первое закрытие 4ч под голубой не позже 8 баров 4ч после касания."""
    c, h, j = a["c"], a["h"], a["j"]
    Bp = a["B4p"]
    rb = a["f_run_B"]
    out, jp, armed, touched = [], -1, False, None
    for i in range(a["i0"], len(c)):
        if j[i] != jp:
            jp = j[i]
            if touched is not None:
                if a["f_close"][i] < a["f_B"][i]:
                    out.append(i)
                    touched, armed = None, False
                elif i - touched > 32:
                    touched, armed = None, False
            if rb[i] <= -m:
                armed = True
        if armed and touched is None and h[i] >= Bp[i] * (1 - TOL / 100):
            touched = i
    return out


def manage_s2(a, i):
    c, l, o, j = a["c"], a["l"], a["o"], a["j"]
    R, B = a["f_R"], a["f_B"]
    ry, rr = a["f_run_Y"], a["f_run_R"]
    Rp = np.r_[R[0], R[:-1]]
    p0, jp = c[i], j[i]
    below = Rp[i] < p0
    for e in range(i + 1, len(c)):
        new4 = j[e] != jp
        jp = j[e]
        if below:
            lv = Rp[e] * (1 + TOL / 100)
            if l[e] <= lv < p0:
                return e, min(lv, o[e]), "цель"
        if new4:
            if below and ry[e] == 2:
                return e, c[e], "отмена над жёлтой"
            if not below and rr[e] >= 2:
                return e, c[e], "отмена над красной"
            if a["f_d_G"][e] <= -5.0 or a["f_d_B"][e] <= -10.0:
                return e, c[e], "далеко"
    return len(c) - 1, c[-1], "конец"


def one_at_a_time(events, mgr):
    out, last = [], -1
    for i in events:
        if i <= last:
            continue
        e, px, why = mgr(i)
        out.append((i, e, why, px))
        last = e
    return out


def to_frame(a, fm, coin, name, s, rows):
    res = []
    for i, e, why, px in rows:
        tr = (i, e, a["c"][i], float(px), s)
        m, f, u = lg.trade_cash(fm, tr)
        res.append({"coin": coin, "сетап": name, "год": pd.Timestamp(int(a["t"][i]), unit="s").year, "t0": a["t"][i], "где": place(a, i), "причина": why, "r": (m - f - u) / lg.NOTIONAL * 100, "часов": e - i, "s": s, "i0": i, "i1": e, "p0": a["c"][i], "p1": float(px)})
    return res


def main():
    series = ec.load_all()
    all_rows = []
    for coin, a, fm in series:
        for k in (0.0, 1.0, 2.0, 3.0):
            ev = s1_events(a, k)
            all_rows += to_frame(a, fm, coin, f"S1 веер≥{k:g}", -1, one_at_a_time(ev, lambda i: manage_s1(a, i)))
            ev = s1_events(a, k, mirror=True)
            all_rows += to_frame(a, fm, coin, f"M1 веер≥{k:g}", 1, one_at_a_time(ev, lambda i: manage_s1(a, i, mirror=True)))
        all_rows += to_frame(a, fm, coin, "S2 от голубой", -1, one_at_a_time(s2_events(a), lambda i: manage_s2(a, i)))
    d = pd.DataFrame(all_rows)
    d.to_csv(pos.OUT / "setups_trades.csv", index=False)
    rows = []
    for name, g in d.groupby("сетап"):
        row = {"сетап": name}
        for coin in ("BTC", "ETH", "Bitstamp", "XRP"):
            x = g[g["coin"] == coin]
            row[coin] = round(x["r"].sum())
            row[coin + "_n"] = len(x)
            row[coin + "_цель_%"] = round((x["причина"] == "цель").mean() * 100) if len(x) else 0
        for coin in ("BTC", "ETH"):
            x = g[(g["coin"] == coin) & (g["год"] >= 2025)]
            row[coin + "_25–26"] = round(x["r"].sum())
        rows.append(row)
    print(pd.DataFrame(rows).to_string(index=False), flush=True)
    t = d[d["сетап"].isin(["S1 веер≥1", "S1 веер≥2", "S2 от голубой"])].groupby(["сетап", "где", "coin"])["r"].agg(["size", "sum"]).round(1).unstack("coin")
    print(t.to_string(), flush=True)
    t = d[d["сетап"].isin(["S1 веер≥1", "S1 веер≥2", "S2 от голубой"])].groupby(["сетап", "причина", "coin"])["r"].agg(["size", "sum"]).round(1).unstack("coin")
    print(t.to_string(), flush=True)
    for name in ("S1 веер≥2", "S2 от голубой"):
        x = d[(d["сетап"] == name) & (d["coin"] == "BTC")]
        for coin, a, fm in series[:1]:
            print(name, "BTC сдвиги:", lg.shift_rank(a, fm, [(int(q.i0), int(q.i1), q.p0, q.p1, int(q.s)) for q in x.itertuples()]), flush=True)
    btc = d[(d["coin"] == "BTC") & (d["год"] >= 2025) & (d["сетап"].isin(["S1 веер≥2", "S2 от голубой"]))].copy()
    btc["вход"] = pd.to_datetime(btc["t0"], unit="s")
    print(btc[["сетап", "вход", "где", "причина", "p0", "p1", "r", "часов"]].round(2).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
