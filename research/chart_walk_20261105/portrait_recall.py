"""Какие его действия потерял автомат под портрет и почему: сравнение с v1 по 23 старым и 15 новым действиям."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import gpt_check as gc  # noqa: E402
import pos  # noqa: E402
import words as wd  # noqa: E402
import words2 as w2  # noqa: E402

pd.set_option("display.width", 260, "display.max_columns", 40, "display.max_rows", 300)


def main():
    m, h1, h4, d1, fund = cw.load()
    del m
    a, _ = gc.er.prep(h1, h4, d1, fund)
    wd.add_runs(a)
    kw = {"gate": "full", "xl": True, "sflip": True}
    legs = w2.run(a, **kw)
    for fn in (wd.recall, w2.recall2):
        r = fn(a, legs)
        print(r.to_string(index=False), flush=True)
    t = a["t"]
    rows = []
    for q in legs:
        if cw.T("2025-02-15") <= t[q[0]] < cw.T("2025-05-20") or cw.T("2025-11-20") <= t[q[0]]:
            rows.append({"вход": pos.utc_full(t[q[0]])[:-3], "выход": pos.utc_full(t[q[1]])[:-3], "ст": "L" if q[4] == 1 else "S", "тип": q[5], "причина": q[6], "p0": round(q[2]), "p1": round(q[3])})
    d = pd.DataFrame(rows)
    d.to_csv(pos.OUT / "portrait_legs_2025_26.csv", index=False)
    print(d.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
