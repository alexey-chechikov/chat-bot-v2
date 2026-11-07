"""Простое правило в индикаторе: построчная копия ветки runS из bot7_operator_strategy_A.pine. Сверка с words3.run на четырёх рядах, час и 4ч должны давать одни сделки. Ожидаемые числа для сверки на графике: Binance и Bybit, без фандинга, только закрытые, с 01.01.2025."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import bybit_check as bc  # noqa: E402
import cw_data as cw  # noqa: E402
import state_card as sc  # noqa: E402
import state_map as sm  # noqa: E402
import words3 as w3  # noqa: E402
import words3_look as wl  # noqa: E402

pd.set_option("display.width", 220, "display.max_columns", 30, "display.max_rows", 100)
K4 = 2
SIDE_COST = 0.068


def run(a, exit_line="под красной", h4_only=False):
    """h4_only: автомат видит только часы закрытия 4ч, как индикатор на графике 4ч."""
    t, close, j = a["t"], a["c"], a["j"]
    side, tag, entry, entryI, jp = 0, "", np.nan, -1, -1
    legs = []
    for i in range(a["i0"], len(t)):
        new4 = j[i] != jp
        jp = j[i]
        if h4_only and not new4:
            continue
        fc, fB = a["f_close"][i], a["f_B"][i]
        rG, rR = a["f_run_G"][i], a["f_run_R"][i]
        rExit = rR if exit_line == "под красной" else rG
        closeNow, oSide, oTag = False, 0, ""
        if new4:
            if side == 1 and rExit <= -K4:
                closeNow = True
            elif side == -1 and rG >= K4:
                closeNow = True
        if closeNow:
            legs.append((entryI, i, entry, float(close[i]), side, tag))
            side, tag = 0, ""
        if new4 and side == 0:
            if fc > fB:
                if rG >= K4 and rExit > -K4:
                    oSide, oTag = 1, "над синей"
            elif rG <= -K4:
                oSide, oTag = -1, "под синей"
        if oSide != 0:
            side, tag, entry, entryI = oSide, oTag, float(close[i]), i
    return legs


def expected(a, frm, exit_line):
    legs = run(a, exit_line)
    t = a["t"]
    rows = []
    for i0, i1, p0, p1, s, tag in legs:
        if t[i0] < frm:
            continue
        net = s * (p1 / p0 - 1) * 100 - SIDE_COST - SIDE_COST * (p1 / p0)
        rows.append({"вход": sm.utc(t[i0]), "выход": sm.utc(t[i1]), "с": "L" if s == 1 else "S", "p0": round(p0, 1), "p1": round(p1, 1), "net": round(net, 2)})
    return pd.DataFrame(rows)


def main():
    for k, a, _ in wl.series():
        for ex, wk in (("под красной", "R"), ("под зелёной", "G")):
            ref = [x[:6] for x in w3.run(a, l_align=False, s_align=False, l_exit=wk) if x[6] != "конец"]
            m1, m4 = run(a, ex), run(a, ex, h4_only=True)
            same1 = [tuple(x) for x in m1] == ref
            same4 = [tuple(x) for x in m4] == ref
            print(k, ex, "час совпал:", same1, "4ч совпал:", same4, "сделок", len(ref), flush=True)
        ju, first = np.unique(a["j"], return_index=True)
        pos4 = first
        print(k, "закрытие часа = закрытие 4ч на часах новой 4ч:", round(float(np.mean(np.isclose(a["c"][pos4], a["f_close"][pos4]))) * 100, 2), "%", flush=True)
    frm = cw.T("2025-01-01")
    by = bc.load_bybit()
    bn, _, _ = sc.load_coin("BTC")
    for lab, a in (("BYBIT:BTCUSDT.P", by), ("BINANCE:BTCUSDT", bn)):
        for ex in ("под красной", "под зелёной"):
            d = expected(a, frm, ex)
            print(lab, ex, "закрытых", len(d), "итог", round(d["net"].sum(), 1), "лонг", round(d.loc[d["с"] == "L", "net"].sum(), 1), "шорт", round(d.loc[d["с"] == "S", "net"].sum(), 1), flush=True)
            print(d.tail(4).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
