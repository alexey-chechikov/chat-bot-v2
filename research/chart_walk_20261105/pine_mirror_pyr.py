"""Копия ветки индикатора: Простое+, шорт под жёлтой и добор, те же переменные и порядок проверок. Сверка итога с btc_next.pyramid на часе; на 4ч показывает, сколько сделок отличается из-за того, что внутри свечи выхода час касания не виден. Ожидаемые числа на графике: закрытые с 01.01.2025, без фандинга."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import btc_lab as bl  # noqa: E402
import btc_next as bn  # noqa: E402
import bybit_check as bc  # noqa: E402
import plus as pl  # noqa: E402
import state_map as sm  # noqa: E402

K4 = 2
SC = 0.068


def run(a, lay, pyrOn=True, first=0.5, add=0.5, X=2.0, h4=False, cut=None):
    t, c, h, l, o, j = a["t"], a["c"], a["h"], a["l"], a["o"], a["j"]
    F, B, atr4 = a["f_close"], a["f_B"], a["atr4"]
    rG0, rY0, rR0 = a["f_run_G"], a["f_run_Y"], a["f_run_R"]
    rk, W = lay
    n = len(t) if cut is None else int(np.searchsorted(t, cut, side="right"))
    new = np.r_[True, j[1:] != j[:-1]]
    idx = np.flatnonzero(new[:n]) if h4 else np.arange(n)
    idx = idx[idx >= a["i0"]]
    out, side, tag, entry, entryI, size, eAtr, addDone, addPx = [], 0, "", 0.0, -1, 1.0, 0.0, False, np.nan
    prev = -1
    for i in idx:
        new4 = bool(new[i])
        if h4:
            a0 = prev + 1 if prev >= 0 else i
            bo, bh, bl_ = o[a0], h[a0:i + 1].max(), l[a0:i + 1].min()
            lvCs = a["B4p"][a0] * 1.005
            prev = i
        else:
            bo, bh, bl_ = o[i], h[i], l[i]
            lvCs = a["B4p"][i] * 1.005
        rG, rY, rR = rG0[i], rY0[i], rR0[i]
        closeNow, xPx, oSide, oTag = False, 0.0, 0, ""
        if side == -1 and tag == "под жёлтой" and bl_ <= lvCs and lvCs < entry:
            closeNow, xPx = True, min(lvCs, bo)
        if new4 and not closeNow:
            if side == 1 and rR <= -K4:
                closeNow, xPx = True, float(c[i])
            elif side == -1 and tag == "под жёлтой" and rY >= K4:
                closeNow, xPx = True, float(c[i])
            elif side == -1 and tag == "под синей" and rG >= K4:
                closeNow, xPx = True, float(c[i])
        pyrMain = pyrOn and tag in ("над синей", "под синей")
        if pyrMain and side != 0 and not closeNow and not addDone:
            lv = entry + side * X * eAtr
            if (side == 1 and bh >= lv) or (side == -1 and bl_ <= lv):
                addDone, addPx = True, (max(lv, bo) if side == 1 else min(lv, bo))
        if closeNow:
            net = side * (xPx / entry - 1) * 100 - SC - SC * (xPx / entry)
            w = size * (first if pyrMain else 1.0)
            tot = net * w + ((side * (xPx / addPx - 1) * 100 - SC - SC * (xPx / addPx)) * size * add if pyrMain and addDone else 0.0)
            out.append((entryI, i, side, tot, addDone and pyrMain))
            side, tag = 0, ""
        if new4 and side == 0:
            if F[i] > B[i]:
                if rG >= K4 and rR > -K4:
                    oSide, oTag = 1, "над синей"
                elif rY == -K4 and c[i] > B[i] * 1.005:
                    oSide, oTag = -1, "под жёлтой"
            elif rG <= -K4 and not rk[i] > 0.6:
                oSide, oTag = -1, "под синей"
        if oSide != 0:
            side, tag, entry, entryI, eAtr = oSide, oTag, float(c[i]), i, float(atr4[i])
            size = W[i] / pl.DIV
            addDone, addPx = False, np.nan
    return out


def nofund(legs):
    return float(sum(x[7] * (x[4] * (x[3] / x[2] - 1) * 100 - SC - SC * x[3] / x[2]) for x in legs if x[6] != "конец"))


def expect(a, out, frm):
    q = [x for x in out if a["t"][x[0]] >= frm]
    v = np.array([x[3] for x in q])
    s = np.array([x[2] for x in q])
    return len(q), round(float(v.sum()), 1), round(float(v[s == 1].sum()), 1), round(float(v[s == -1].sum()), 1), "доборов", int(sum(x[4] for x in q))


def main():
    (a, f, lay), (b, fb, layb) = bl.load()
    for lab, A, L in (("BTC", a, lay), ("Bitstamp", b, layb)):
        ref = bn.pyramid(A, bl.run(A, L, rules={"cs": 1.0}), 2, 2, 0.5, 0.5)
        m1, m4 = run(A, L), run(A, L, h4=True)
        print(lab, "итог без фандинга: эталон", round(nofund(ref), 1), "копия час", round(sum(x[3] for x in m1), 1), "копия 4ч", round(sum(x[3] for x in m4), 1), "сделок", len(m1), len(m4), "доборов час/4ч", sum(x[4] for x in m1), sum(x[4] for x in m4), flush=True)
    by = bc.load_bybit()
    lby = pl.layer(by)
    frm = sm.T("2025-01-01")
    for lab, A, L in (("BYBIT:BTCUSDT.P", by, lby), ("BINANCE:BTCUSDT", a, lay)):
        print(lab, "4ч:", expect(A, run(A, L, h4=True), frm), "1ч:", expect(A, run(A, L), frm), "| добор выключен 4ч:", expect(A, run(A, L, pyrOn=False, h4=True), frm), flush=True)


if __name__ == "__main__":
    main()
