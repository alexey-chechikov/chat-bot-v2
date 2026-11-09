"""Копия ветки Простое+ со шортом под жёлтой из bot7_operator_strategy_A.pine: те же переменные и порядок проверок, сверка с btc_lab.run на часе и только по барам 4ч. Ожидаемые числа на графике: закрытые с 01.01.2025, с весом, без фандинга."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import btc_lab as bl  # noqa: E402
import bybit_check as bc  # noqa: E402
import plus as pl  # noqa: E402
import state_card as sc  # noqa: E402
import state_map as sm  # noqa: E402

K4 = 2
SC = 0.068


def run(a, lay, shortExit="над зелёной", csOn=True, csW=1.0, h4=False):
    t, c, h, l, o, j = a["t"], a["c"], a["h"], a["l"], a["o"], a["j"]
    F, B = a["f_close"], a["f_B"]
    rG0, rY0, rR0 = a["f_run_G"], a["f_run_Y"], a["f_run_R"]
    rk, W = lay
    n = len(t)
    new = np.r_[True, j[1:] != j[:-1]]
    legs, side, tag, entry, entryI, size = [], 0, "", 0.0, -1, 1.0
    idx = np.flatnonzero(new) if h4 else np.arange(n)
    idx = idx[idx >= a["i0"]]
    prev_new = -1
    for pos, i in enumerate(idx):
        new4 = bool(new[i])
        if h4:
            a0 = prev_new + 1 if prev_new >= 0 else i
            bo, bh, bl_ = o[a0], h[a0:i + 1].max(), l[a0:i + 1].min()
            prev_new = i
            lvCs = a["B4p"][a0 if a0 <= i else i] * 1.005
        else:
            bo, bh, bl_ = o[i], h[i], l[i]
            lvCs = a["B4p"][i] * 1.005
        rG, rY, rR = rG0[i], rY0[i], rR0[i]
        rExit, rSx = rR, (rY if shortExit == "над жёлтой" else rG)
        closeNow, xPx, oSide, oTag = False, 0.0, 0, ""
        if side == -1 and tag == "под жёлтой" and bl_ <= lvCs and lvCs < entry:
            closeNow, xPx = True, min(lvCs, bo)
        if new4 and not closeNow:
            if side == 1 and rExit <= -K4:
                closeNow, xPx = True, float(c[i])
            elif side == -1 and tag == "под жёлтой" and rY >= K4:
                closeNow, xPx = True, float(c[i])
            elif side == -1 and tag == "под синей" and rSx >= K4:
                closeNow, xPx = True, float(c[i])
        if closeNow:
            legs.append((entryI, i, entry, float(xPx), side, size))
            side, tag = 0, ""
        if new4 and side == 0:
            if F[i] > B[i]:
                if rG >= K4 and rExit > -K4:
                    oSide, oTag = 1, "над синей"
                elif csOn and rY == -K4 and c[i] > B[i] * 1.005:
                    oSide, oTag = -1, "под жёлтой"
            elif rG <= -K4 and rSx < K4 and not rk[i] > 0.6:
                oSide, oTag = -1, "под синей"
        if oSide != 0:
            side, tag, entry, entryI = oSide, oTag, float(c[i]), i
            size = W[i] / pl.DIV * (csW if oTag == "под жёлтой" else 1.0)
    return legs


def same(x, y):
    a_ = [q for q in x if q[6] != "конец"]
    n_same = sum(1 for p, q in zip(a_, y) if p[0] == q[0] and p[1] == q[1] and p[4] == q[4] and abs(p[3] - q[3]) < 1e-6 and abs(p[7] - q[5]) < 1e-9)
    return len(a_), len(y), n_same


def expect(a, lay, frm, **kw):
    legs = [x for x in run(a, lay, **kw) if a["t"][x[0]] >= frm]
    v = np.array([x[5] * (x[4] * (x[3] / x[2] - 1) * 100 - SC - SC * x[3] / x[2]) for x in legs])
    s = np.array([x[4] for x in legs])
    return len(v), round(float(v.sum()), 1), round(float(v[s == 1].sum()), 1), round(float(v[s == -1].sum()), 1)


def main():
    (a, f, lay), (b, fb, layb) = bl.load()
    for lab, A, L in (("BTC", a, lay), ("Bitstamp", b, layb)):
        for ex, kw in (("над зелёной", {}), ("над жёлтой", {"sx": "Y"})):
            ref = bl.run(A, L, rules={"cs": 1.0}, **kw)
            print(lab, ex, "час:", same(ref, run(A, L, shortExit=ex)), "4ч:", same(ref, run(A, L, shortExit=ex, h4=True)), flush=True)
    by = bc.load_bybit()
    lby = pl.layer(by)
    frm = sm.T("2025-01-01")
    for lab, A, L in (("BYBIT:BTCUSDT.P", by, lby), ("BINANCE:BTCUSDT", a, lay)):
        print(lab, "шорт под жёлтой вес 1:", expect(A, L, frm), "| и выход над жёлтой:", expect(A, L, frm, shortExit="над жёлтой"), "| выключен:", expect(A, L, frm, csOn=False), flush=True)


if __name__ == "__main__":
    main()
