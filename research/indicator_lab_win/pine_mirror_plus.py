"""Построчная копия ветки runS с isPlus из bot7_operator_strategy_plus.pine. Сверка с candidate.run_cand и ожидаемые числа для графика.
Семантика Pine учтена: percentrank — доля прошлых значений ≤ текущего, median с полным окном. Веса по формуле файла, делитель 1.18. Запуск: python -X utf8 pine_mirror_plus.py"""
from __future__ import annotations

import numpy as np
import pandas as pd

import candidate as cd
import lab_core as lc

K4, SIDE_COST, VOL, LO, HI, NORM, RMAX = 2, 0.068, 2190, 0.5, 2.0, 1.18, 60.0


def percentrank(x, n):
    out = np.full(len(x), np.nan)
    for i in range(n, len(x)):
        if np.isfinite(x[i]) and np.isfinite(x[i - n:i]).all():
            out[i] = (x[i - n:i] <= x[i]).mean() * 100
    return out


def vol_arrays(S):
    p = S.atr4(100) / S.h4["c"]
    rk = percentrank(p, VOL)
    md = pd.Series(p).rolling(VOL, min_periods=VOL).median().to_numpy()
    return rk, np.r_[np.nan, md[:-1]], p


def f_run(prev, x):
    s = 0 if not np.isfinite(x) else int(np.sign(x))
    if s == 0:
        return 0
    return prev + s if prev != 0 and (s > 0) == (prev > 0) else s


def run(S, plus=True):
    t, close = S.t, S.c
    rk, md, pc = vol_arrays(S)
    cf, g, r, b = S.h4["c"], S.line4(lc.G), S.line4(lc.R), S.line4(lc.B)
    side, entry, entryI, entrySize, rG, rR = 0, np.nan, -1, 1.0, 0, 0
    legs = []
    jp = -1
    for i in range(S.i0, len(t)):
        j = S.j[i]
        new4 = j != jp
        jp = j
        if not new4:
            continue
        fc, fG, fR, fB = cf[j], g[j], r[j], b[j]
        rk4, md4, pc4 = rk[j], md[j], pc[j]
        sizeNow = (1.0 if (not np.isfinite(md4) or not np.isfinite(pc4) or pc4 <= 0) else max(min(md4 / pc4, HI), LO)) / NORM
        shortOk = (not np.isfinite(rk4)) or rk4 <= RMAX
        rG, rR = f_run(rG, fc - fG), f_run(rR, fc - fR)
        if (side == 1 and rR <= -K4) or (side == -1 and rG >= K4):
            legs.append((entryI, i, entry, float(close[i]), side, entrySize if plus else 1.0, "", "линия"))
            side = 0
        oSide = 0
        if side == 0:
            if fc > fB:
                if rG >= K4 and rR > -K4:
                    oSide = 1
            elif rG <= -K4 and (not plus or shortOk):
                oSide = -1
        if oSide:
            side, entry, entryI, entrySize = oSide, float(close[i]), i, sizeNow
    return legs


def main():
    frm = lc.T("2020-01-01")
    for name in ("BTC", "ETH", "XRP", "BybitBTC"):
        S = lc.load(name)
        # у XRP и Bybit год разгона показателей кончается позже, сравниваем после него
        f = max(frm, int(S.t[0]) + 400 * 86400)
        a = run(S)
        b = [x for x in cd.run_cand(S, norm=False) if x[7] != "конец"]
        ka = {(x[0], x[1], x[4]) for x in a if S.t[x[0]] >= f}
        kb = {(x[0], x[1], x[4]) for x in b if S.t[x[0]] >= f}
        wa = {(x[0], x[1], x[4]): x[5] for x in a}
        wb = {(x[0], x[1], x[4]): x[5] / NORM for x in b}
        common = ka & kb
        dw = max((abs(wa[k] - wb[k]) for k in common), default=0)
        print(name, "сравнение с", pd.Timestamp(f, unit="s").strftime("%d.%m.%Y"), ": Pine-копия", len(ka), "движок", len(kb), "общих", len(common), "макс. разница веса", round(dw, 5))
    print("\nОжидаемо на графике, закрытые, с 01.01.2025, без фандинга, издержка 0.068% на сторону, с весом")
    for name, lab in (("BybitBTC", "BYBIT:BTCUSDT.P"), ("BTC", "BINANCE:BTCUSDT")):
        S = lc.load(name)
        for plus, nm in ((True, "Простое+"), (False, "Простое правило")):
            legs = [x for x in run(S, plus) if S.t[x[0]] >= lc.T("2025-01-01")]
            rows = []
            for x in legs:
                k = x[3] / x[2]
                rows.append({"вход": pd.Timestamp(int(S.t[x[0]]), unit="s").strftime("%d.%m.%y %H:%M"), "выход": pd.Timestamp(int(S.t[x[1]]), unit="s").strftime("%d.%m.%y %H:%M"), "с": "L" if x[4] == 1 else "S", "p0": round(x[2], 1), "p1": round(x[3], 1), "вес": round(x[5], 2), "net": round((x[4] * (k - 1) * 100 - SIDE_COST - SIDE_COST * k) * x[5], 2)})
            d = pd.DataFrame(rows)
            print(lab, nm, "сделок", len(d), "итог", round(d["net"].sum(), 1), "лонг", round(d.loc[d["с"] == "L", "net"].sum(), 1), "шорт", round(d.loc[d["с"] == "S", "net"].sum(), 1))
            if plus:
                print(d.tail(5).to_string(index=False))


if __name__ == "__main__":
    main()
