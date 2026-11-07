"""Построчная копия логики bot7_operator_strategy_A.pine на Python: те же переменные и тот же порядок веток. Сверка с words2.run на всех рядах и настройках. Время 4ч в TradingView здесь не проверяется: его показывает сверка на графике."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import entry_common as ec  # noqa: E402
import state_map as sm  # noqa: E402
import words2 as w2  # noqa: E402

FAR_G, FAR_B, NEAR_G, TOL, K4, K1 = -5.0, -10.0, -1.0, 0.5, 2, 3


def run(a, optGate=True, optAtr=True, sStop=2.0, sTp=6.0, optX01=False, by_clock=False):
    n = len(a["c"])
    t, close, high, low, open_ = a["t"], a["c"], a["h"], a["l"], a["o"]
    side, tag, entry, entryI, entryAtr = 0, "", np.nan, -1, np.nan
    covered, awaitBlue = False, False
    legs = []
    jp = -1
    for i in range(a["i0"], n):
        new4 = t[i] % 14400 == 0 if by_clock else a["j"][i] != jp
        jp = a["j"][i]
        fc, fG, fY, fR, fB, fB1, atr4 = a["f_close"][i], a["f_G"][i], a["f_Y"][i], a["f_R"][i], a["f_B"][i], a["f_B1"][i], a["atr4"][i]
        rG, rY, rR, runR, runB1 = a["f_run_G"][i], a["f_run_Y"][i], a["f_run_R"][i], a["run_R"][i], a["run_B1"][i]
        rising = fB > a["f_B"][max(i - 120, 0)]
        stack = 1 if fG > fY > fR else (-1 if fG < fY < fR else 0)
        dG, dB, aB = (fc / fG - 1) * 100, (fc / fB - 1) * 100, (fc - fB) / atr4
        closeNow, xPx, xWhy, oSide, oTag = False, np.nan, "", 0, ""
        overGY, underGY = fc > fG and fc > fY, fc < fG and fc < fY
        rOver, rUnder = runR >= K1, runR <= -K1
        overBL, underBL = fc > fB and fc > fB1, fc < fB and fc < fB1
        gUnder = rG <= -K4 and rUnder
        inDesc = stack == 0 or (stack == 1 and underBL and not rising)
        allowS = not optGate or inDesc
        skip = False

        if side == 1:
            if tag == "к голубой":
                lvl = a["B4p"][i] * (1 - TOL / 100)
                if high[i] >= lvl and entry < lvl:
                    closeNow, xPx, xWhy, awaitBlue, skip = True, max(lvl, open_[i]), "цель", True, True
                elif (gUnder if optX01 else (underGY and rUnder)):
                    closeNow, xPx, xWhy, skip = True, close[i], "выход", True
                    if allowS:
                        oSide, oTag = -1, "перекладка"
            else:
                if optX01 and gUnder:
                    closeNow, xPx, xWhy, skip = True, close[i], "X01", True
                elif tag == "над голубыми" and new4 and rY <= -K4:
                    closeNow, xPx, xWhy = True, close[i], "жёлтая"
                elif tag == "снова над жёлтой" and new4 and rR <= -K4:
                    closeNow, xPx, xWhy = True, close[i], "красная"
        elif side == -1:
            if optAtr and (high[i] >= entry + sStop * entryAtr or low[i] <= entry - sTp * entryAtr):
                closeNow = True
                xPx = max(entry + sStop * entryAtr, open_[i]) if high[i] >= entry + sStop * entryAtr else min(entry - sTp * entryAtr, open_[i])
                xWhy = "стоп ATR" if high[i] >= entry + sStop * entryAtr else "тейк ATR"
                covered, skip = True, True
            elif tag == "от голубой" and new4 and fc > fB:
                closeNow, xPx, xWhy, awaitBlue, skip = True, close[i], "стоп над голубой", True, True
            else:
                if tag == "от голубой" and fc < fG:
                    tag = "от голубой, под зелёной"
                if tag.startswith("от голубой") and new4 and (dG <= FAR_G or dB <= FAR_B):
                    closeNow, xPx, xWhy, covered, skip = True, close[i], "далеко", True, True
                elif tag in ("под голубой", "перекладка", "снова шорт", "от голубой, под зелёной"):
                    if new4 and dG <= FAR_G:
                        closeNow, xPx, xWhy, covered, skip = True, close[i], "далеко", True, True
                    elif overGY and rOver:
                        closeNow, xPx, xWhy, skip = True, close[i], "над G+Y", True
                        oSide, oTag = 1, ("к голубой" if fc < fB else "над голубыми")
                if not closeNow and tag == "над голубыми" and new4 and rG >= 1 and runB1 >= K1:
                    closeNow, xPx, xWhy = True, close[i], "над зелёной"

        if closeNow:
            legs.append((entryI, i, entry, float(xPx), side, tag))
            side, tag = 0, ""

        if not skip and side == 0:
            go = True
            if awaitBlue:
                if new4 and fc < fB:
                    awaitBlue, go = False, False
                    if allowS:
                        oSide, oTag = -1, "от голубой"
                elif new4 and (aB > 1 or (overBL and stack == 1 and overGY)):
                    awaitBlue = False
                else:
                    go = False
            if go:
                if fc < fB:
                    if overGY and rOver:
                        oSide, oTag, covered = 1, "к голубой", False
                    elif new4 and covered and fc < fG and dG > NEAR_G:
                        covered = False
                        if allowS:
                            oSide, oTag = -1, "снова шорт"
                    elif new4 and covered and fc > fG:
                        covered = False
                    elif new4 and not covered and underGY and underBL:
                        if allowS:
                            oSide, oTag = -1, "под голубой"
                elif new4 and rY == 1 and overBL:
                    oSide, oTag = 1, "снова над жёлтой"
                elif new4 and overBL and stack == 1 and overGY:
                    oSide, oTag = 1, "над голубыми"
                elif new4 and rR == -K4:
                    if allowS:
                        oSide, oTag = -1, "над голубыми"

        if oSide != 0:
            side, tag, entry, entryI, entryAtr = oSide, oTag, float(close[i]), i, atr4
    return legs


def compare(ref, new):
    ref5 = [(x[0], x[1], x[4]) for x in ref if x[6] != "конец"]
    new5 = [(x[0], x[1], x[4]) for x in new]
    same = ref5 == new5
    px = all(abs(a[3] - b[3]) < 1e-9 and a[5] == b[5] for a, b in zip([x for x in ref if x[6] != "конец"], new))
    return same and px, len(ref5), len(new5)


def main():
    cfgs = (("A + 2/6", dict(optAtr=True), w2.MAIN26), ("только A", dict(optAtr=False), w2.MAIN), ("A + 2/6 + X01", dict(optAtr=True, optX01=True), {**w2.MAIN26, "xl": True, "x01_all": "add"}), ("без отбора", dict(optGate=False, optAtr=False), {}))
    for k, a, _ in ec.load_all():
        sm.add_state(a)
        for lab, pk, wk in cfgs:
            print(k, lab, compare(w2.run(a, **wk), run(a, **pk)), flush=True)
        m = run(a, by_clock=True)
        r = w2.run(a, **w2.MAIN26)
        rs = {(x[0], x[1], x[4]) for x in r}
        ms = {(x[0], x[1], x[4]) for x in m}
        print(k, "новая 4ч по часам вместо индекса: сделок", len(m), "против", len(r), "разных", len(rs ^ ms), flush=True)


if __name__ == "__main__":
    main()
