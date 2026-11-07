"""W1: вариант A (настоящий words2.run) и начало истории графика. Заглушки только у зависимостей, которые run не читает. Запуск: python -X utf8 w1_variant_a.py"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd

import lab_core as lc

CW = Path(__file__).parents[1] / "chart_walk_20261105"


def stub(name, **kw):
    m = types.ModuleType(name)
    m.__dict__.update(kw)
    sys.modules[name] = m
    return m


def import_w2():
    stub("cw_data", T=lc.T)
    stub("ledger")
    stub("pos")
    stub("words", DEF=dict(k4=2, k1=3, far_g=-5.0, far_b=-10.0, near_g=-1.0, tol=0.5, knot=None, event_short=True))
    sys.path.insert(0, str(CW))
    import words2 as w2
    return w2


def arrays(S):
    j = S.j
    c4 = S.h4["c"]
    G, Y, R, B = S.line4(lc.G), S.line4(lc.Y), S.line4(lc.R), S.line4(lc.B)
    b1, r1 = S.line1(lc.B), S.line1(lc.R)
    idx = np.searchsorted(S.t, S.h4["known"], side="left")
    idx = np.clip(idx, 0, len(S.t) - 1)
    b1at4 = b1[idx]
    jp = np.clip(np.searchsorted(S.h4["known"], S.t - 3600, side="right") - 1, 0, None)
    A = S.atr4()
    st = np.where((G > Y) & (Y > R), 1, np.where((G < Y) & (Y < R), -1, 0))
    a = {"t": S.t, "o": S.o, "h": S.h, "l": S.l, "c": S.c, "j": j, "i0": S.i0, "atr4": A[j], "f_close": c4[j], "f_G": G[j], "f_Y": Y[j], "f_R": R[j], "f_B": B[j], "f_B1": b1at4[j], "B4p": B[jp], "B1h": b1,
         "run_R": lc.run_len(S.c - r1), "run_B1": lc.run_len(S.c - b1), "f_d_G": ((c4 / G - 1) * 100)[j], "f_d_B": ((c4 / B - 1) * 100)[j], "f_a_B": ((c4 - B) / A)[j], "f_stack": st[j]}
    for k, v in (("G", G), ("Y", Y), ("R", R), ("B", B)):
        a["f_run_" + k] = lc.run_len(c4 - v)[j]
    return a


def key(S, legs, frm):
    return {(int(S.t[x[0]]), int(S.t[x[1]]), x[4]) for x in legs if S.t[x[0]] >= frm and x[6] != "конец"}


def main():
    w2 = import_w2()
    frm = lc.T("2025-01-01")
    for name, src in (("BTC", "spot_BTCUSDT_1h.csv"), ("BybitBTC", "bybit_BTCUSDT_1h.csv")):
        S = lc.load(name)
        full = w2.run(arrays(S), **w2.MAIN26)
        rf = key(S, full, frm)
        legs5 = [(x[0], x[1], x[2], x[3], x[4], 1.0, x[5], x[6]) for x in full]
        print(name, "вариант A+2/6: сделок", len(full), "итог", round(float(lc.nets(S, legs5).sum()), 1), "просадка", round(lc.max_dd(lc.equity(S, legs5)[S.i0:]), 1), "с 2025 закрытых", len(rf))
        raw = pd.read_csv(lc.ld.DATA / src)
        raw["ts"] = raw["ms"].to_numpy(np.int64) // 1000
        rows = []
        for st, warm in (("2024-12-01", "1 мес"), ("2024-10-01", "3 мес"), ("2024-07-01", "6 мес"), ("2024-01-01", "1 год"), ("2023-01-01", "2 года"), ("2022-01-01", "3 года")):
            X = lc.build(name, raw[raw["ts"] >= lc.T(st)], S.fund_rate, st)
            leg = w2.run(arrays(X), **w2.MAIN26)
            rx = key(X, leg, frm)
            dif = sorted(rx ^ rf)
            rows.append({"история с": st, "разгон": warm, "сделок": len(rx), "совпало": len(rx & rf), "лишних": len(rx - rf), "потеряно": len(rf - rx), "последнее расхождение": pd.Timestamp(dif[-1][0], unit="s").strftime("%d.%m.%Y") if dif else "—"})
        print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
