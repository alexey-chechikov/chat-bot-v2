"""Какая настройка индикатора даёт его таблицу на Bybit: 222 закрытых, +12.2% с 01.01.2025. Перебор галок на барах Bybit через pine_mirror (копия логики Pine)."""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import bybit_check as bc  # noqa: E402
import pine_mirror as pm  # noqa: E402
import state_map as sm  # noqa: E402
import words2 as w2  # noqa: E402

pd.set_option("display.width", 220, "display.max_columns", 30, "display.max_rows", 120)


def total(a, legs, frm, half):
    n, s, sl, ss = 0, 0.0, 0.0, 0.0
    for i0, i1, p0, p1, side, tag in legs:
        if a["t"][i0] < frm:
            continue
        net = side * (p1 / p0 - 1) * 100 - 0.034 - 0.034 * (p1 / p0)
        w = 0.5 if half and side == 1 and not w2.in_portrait(a, i0, 1) else 1.0
        n += 1
        s += net * w
        if side == 1:
            sl += net * w
        else:
            ss += net * w
    return n, round(s, 1), round(sl, 1), round(ss, 1)


def main():
    a = bc.load_bybit()
    frm = sm.T("2025-01-01")
    rows = []
    for g, at, x, h in itertools.product((True, False), (True, False), (False, True), (True, False)):
        legs = pm.run(a, optGate=g, optAtr=at, optX01=x)
        n, s, sl, ss = total(a, legs, frm, h)
        rows.append({"описание шорта": g, "2/6 ATR": at, "X01": x, "половина": h, "n": n, "итог": s, "лонг": sl, "шорт": ss})
    d = pd.DataFrame(rows)
    d["до_цели"] = (d["n"] - 222).abs() + (d["итог"] - 12.2).abs()
    print(d.sort_values("до_цели").drop(columns="до_цели").to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
