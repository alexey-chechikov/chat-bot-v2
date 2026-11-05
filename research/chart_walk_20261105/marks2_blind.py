"""Сверка вслепую: три окна, размеченные оператором 05.11 (записки 4–6), против words.py как есть. Печатает сделки автомата и события линий, чтобы привязать его слова к датам."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import gpt_check as gc  # noqa: E402
import ledger as lg  # noqa: E402
import pos  # noqa: E402
import words as wd  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 30, "display.max_rows", 400)
WIN = (("окно 28.11.25–02.01.26", "2025-11-20", "2026-01-05"), ("окно 09.06–21.07.26", "2026-06-05", "2026-07-22"), ("окно 29.09–05.11.26", "2026-09-25", "2026-11-07"))


def net(fm, x):
    m, f, u = lg.trade_cash(fm, x[:5])
    return (m - f - u) / lg.NOTIONAL * 100


def trades(a, fm, legs, x, z):
    t = a["t"]
    rows = []
    for q in legs:
        if cw.T(x) <= t[q[0]] < cw.T(z):
            rows.append({"вход": pos.utc_full(t[q[0]])[:-3], "выход": pos.utc_full(t[q[1]])[:-3], "ст": "L" if q[4] == 1 else "S", "тип": q[5], "причина": q[6], "p0": round(q[2]), "p1": round(q[3]), "r": round(net(fm, q), 2)})
    return pd.DataFrame(rows)


def events(a, x, z):
    """Закрепления: 2-е закрытие 4ч за G, Y, R, B и 3-е закрытие 1ч за R и голубой 1ч."""
    t, j = a["t"], a["j"]
    i0, i1 = int(np.searchsorted(t, cw.T(x))), int(np.searchsorted(t, cw.T(z)))
    out = []
    for i in range(i0, min(i1, len(t))):
        new4 = j[i] != j[i - 1]
        row = []
        if new4:
            for nm, col in (("G", "f_run_G"), ("Y", "f_run_Y"), ("R", "f_run_R"), ("B4", "f_run_B")):
                v = a[col][i]
                if abs(v) == 2:
                    row.append(("над " if v > 0 else "под ") + nm + " 4ч")
        for nm, col in (("R1", "run_R"), ("B1", "run_B1")):
            v = a[col][i]
            if abs(v) == 3:
                row.append(("над " if v > 0 else "под ") + nm)
        if row:
            out.append({"час": pos.utc_full(t[i])[:-3], "цена": round(a["c"][i]), "что": ", ".join(row), "G": round(a["f_G"][i]), "Y": round(a["f_Y"][i]), "R": round(a["f_R"][i]), "B4": round(a["f_B"][i]), "B1": round(a["f_B1"][i])})
    return pd.DataFrame(out)


def main():
    m, h1, h4, d1, fund = cw.load()
    del m
    a, _ = gc.er.prep(h1, h4, d1, fund)
    wd.add_runs(a)
    fm = lg.funding_marks(a, fund)
    print("столбцы:", sorted(k for k in a.keys() if not isinstance(a[k], (int, float))), flush=True)
    print("конец ряда:", pos.utc_full(a["t"][-1]), flush=True)
    legs = wd.run(a)
    for lab, x, z in WIN:
        d = trades(a, fm, legs, x, z)
        print("\n==", lab, "сделок", len(d), "сумма", round(d["r"].sum(), 1), flush=True)
        print(d.to_string(index=False), flush=True)
        ev = events(a, x, z)
        ev.to_csv(pos.OUT / f"marks2_events_{x}.csv", index=False)
        print("событий", len(ev), "→", f"marks2_events_{x}.csv", flush=True)


if __name__ == "__main__":
    main()
