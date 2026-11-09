"""PREREG_instrument_1108.md, часть A: как совмещать систему (Простое+, шорт под жёлтой, добор) и 432 на BTC.
Пропущенный сигнал 432 не ускоряет следующий: его автомат считается отдельно, как в btc_vs_432.py."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import btc_vs_432 as bv  # noqa: E402  (ставит пути к коду Вина)
import btc_combo as bcm  # noqa: E402
import lab_core as lc  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 30)
SYS = dict(reg=("E", 200), klx=2, sx=lc.G, ksx=2, cs=True, fund=None)


def side_by_hour(S, legs):
    p = np.zeros(len(S.t), int)
    for x in legs:
        p[x[0]:x[1]] = x[4]
    return p


def variants(S):
    sysl = bcm.pyramid(S, bcm.run(S, **SYS))
    l432 = bv.s432(S)
    p = side_by_hour(S, sysl)
    at = np.array([p[x[0]] for x in l432])
    half = [x[:5] + (x[5] * 0.5,) + x[6:] if s == 1 else x for x, s in zip(l432, at)]
    mains = [x for x in sysl if x[6] == "L"]

    def sys_exit(x0):
        return next(((m[1], m[3]) for m in mains if m[0] <= x0 < m[1]), None)

    held, later = [], []
    for x in l432:
        e = sys_exit(x[0])
        if e is None:
            held.append(x)
            later.append(x)
            continue
        held.append((x[0], e[0], x[2], e[1]) + tuple(x[4:]))
        later.append(x if x[1] >= e[0] else (x[0], e[0], x[2], e[1]) + tuple(x[4:]))
    return {
        "A5 432 держать до выхода системы": sysl + held,
        "A6 432 до своего выхода или выхода системы, что позже": sysl + later,
        "A0 обе независимо": sysl + l432,
        "A1 432 не входит, когда система в шорте": sysl + [x for x, s in zip(l432, at) if s != -1],
        "A2 432 только когда система в лонге": sysl + [x for x, s in zip(l432, at) if s == 1],
        "A3 432 половиной, когда система в лонге": sysl + half,
        "A4 432 только когда система не в лонге": sysl + [x for x, s in zip(l432, at) if s != 1],
        "только система": sysl,
    }, {"в лонге": int((at == 1).sum()), "в шорте": int((at == -1).sum()), "вне": int((at == 0).sum())}


def main():
    S, Bs = lc.load("BTC"), lc.load("Bitstamp")
    V, where = variants(S)
    VB, _ = variants(Bs)
    print("входы 432 по положению системы:", where, flush=True)
    rows = []
    for lab in V:
        r, _ = bv.report(S, V[lab], lab)
        rb, _ = bv.report(Bs, VB[lab], lab)
        r["Bitstamp"] = f"{rb['итог']:+.0f} / {rb['просадка']:.0f}"
        rows.append(r)
    print(pd.DataFrame(rows).drop(columns=["лет в плюсе", "в рынке %", "на сделку"]).to_string(index=False), flush=True)
    s432 = bv.s432(S)
    p = side_by_hour(S, bcm.pyramid(S, bcm.run(S, **SYS)))
    r = lc.nets(S, s432)
    at = np.array([p[x[0]] for x in s432])
    for lab, m in (("система в лонге", at == 1), ("система в шорте", at == -1), ("системы нет", at == 0)):
        print(f"сделки 432, когда {lab}: {int(m.sum())}, итог {r[m].sum():+.1f}, на сделку {r[m].mean() if m.any() else 0:+.2f}", flush=True)


if __name__ == "__main__":
    main()
