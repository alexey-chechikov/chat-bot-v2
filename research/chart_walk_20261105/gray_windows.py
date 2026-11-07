"""Какие окна красить серым в индикаторе: кандидаты определения «непонятно» против сделок, которые оператор не называл. Причинные признаки, только закрытые бары."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import entry_common as ec  # noqa: E402
import pos  # noqa: E402
import state_map as sm  # noqa: E402
import words as wd  # noqa: E402
import words2 as w2  # noqa: E402

pd.set_option("display.width", 220, "display.max_columns", 30)
BEST = {"gate": "shorts", "s_stop": 2.0, "s_tp": 6.0, "s_after": "covered"}
TOL_H = 12


def masks(a, legs):
    n = len(a["c"])
    flat = a["flat"] == 2
    between = a["phase"] == "между голубыми"
    plain = np.abs(a["s_b4"]) <= sm.FLAT_B4
    i0 = np.array([x[0] for x in legs])
    cnt = np.zeros(n)
    np.add.at(cnt, i0, 1)
    tr10 = pd.Series(cnt).rolling(240, min_periods=1).sum().to_numpy()
    return {"диапазон": flat, "между голубыми": between, "между и плоская": between & plain, "пила ≥6 сделок за 10 дн": tr10 >= 6, "пила ≥5": tr10 >= 5, "диапазон или между и плоская": flat | (between & plain), "диапазон, между и плоская, пила ≥6": flat | (between & plain) | (tr10 >= 6)}


def main():
    series = ec.load_all()
    for k, a, f in series:
        sm.add_state(a)
    a, fm = series[0][1], series[0][2]
    legs = w2.run(a, **BEST)
    t = a["t"]
    acts = [(cw.T(ts), act) for ts, act, _ in list(wd.MARKS) + list(w2.MARKS2)]
    in_win = np.array([any(cw.T(x) <= t[q[0]] < cw.T(z) for x, z, _ in sm.WINDOWS) for q in legs])
    named = np.array([any(((act[-1] == "L") == (q[4] == 1)) and min(abs(t[q[0]] - tt), abs(t[q[1]] - tt)) <= TOL_H * 3600 for tt, act in acts) for q in legs])
    r = np.array([w2.net(fm, q) for q in legs])
    i0 = np.array([q[0] for q in legs])
    M = masks(a, legs)
    b = a["i0"]
    rows = []
    for nm, m in M.items():
        g = m[i0]
        rows.append({"серое": nm, "доля_часов_%": round(m[b:].mean() * 100, 1), "сделок_в_сером_%": round(g.mean() * 100, 1), "итог_серых": round(r[g].sum()), "итог_остальных": round(r[~g].sum()), "на_сделку_серые": round(r[g].mean(), 2), "на_сделку_остальные": round(r[~g].mean(), 2),
                     "окна: названные в сером_%": round(g[in_win & named].mean() * 100), "окна: неназванные в сером_%": round(g[in_win & ~named].mean() * 100), "окна: итог неназванных в сером": round(r[in_win & ~named & g].sum()), "окна: итог названных в сером": round(r[in_win & named & g].sum())})
    print("BTC, сделки в разобранных окнах:", int(in_win.sum()), "названных", int((in_win & named).sum()), "итог", round(r[in_win & named].sum(), 1), "| неназванных", int((in_win & ~named).sum()), "итог", round(r[in_win & ~named].sum(), 1), flush=True)
    print(pd.DataFrame(rows).to_string(index=False), flush=True)
    print("его окна, доля серого по определениям", flush=True)
    win = (("05.12–28.12.25 флет", "2025-12-05", "2025-12-29"), ("22.12–03.01 только шорты от голубой", "2025-12-22", "2026-01-04"), ("10–21.07.26 флет", "2026-07-10", "2026-07-22"), ("01–05.07.26 рост", "2026-07-01", "2026-07-06"), ("29.09–29.10.26", "2026-09-29", "2026-10-29"))
    rows = []
    for lab, x, z in win:
        w = (t >= cw.T(x)) & (t < cw.T(z))
        rows.append({"окно": lab, **{nm: round(m[w].mean() * 100) for nm, m in M.items()}})
    print(pd.DataFrame(rows).to_string(index=False), flush=True)
    rows = []
    for k, x, f in series:
        lg_ = w2.run(x, **BEST)
        mm = masks(x, lg_)["диапазон, между и плоская, пила ≥6"]
        i = np.array([q[0] for q in lg_])
        rr = np.array([w2.net(f, q) for q in lg_])
        rows.append({"ряд": k, "серых_часов_%": round(mm[x["i0"]:].mean() * 100, 1), "сделок_%": round(mm[i].mean() * 100, 1), "итог_серых": round(rr[mm[i]].sum()), "итог_остальных": round(rr[~mm[i]].sum())})
    print(pd.DataFrame(rows).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
