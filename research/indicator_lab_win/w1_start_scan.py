"""W1: какое начало часового графика даёт на Bybit 222 сделки и +12.2% при издержке 0.034%, как на графике оператора. Линии 4ч считаются по всей истории (request.security), автомат стартует с первой свечи графика.
Запуск: python -X utf8 w1_start_scan.py"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lab_core as lc
import w1_variant_a as v


def main():
    w2 = v.import_w2()
    S = lc.load("BybitBTC")
    a = v.arrays(S)
    frm = lc.T("2025-01-01")
    rows = []
    for st in pd.date_range("2024-12-16", "2025-05-15", freq="3D"):
        a2 = dict(a)
        a2["i0"] = int(np.searchsorted(S.t, int(st.timestamp())))
        for mode, kw in (("A+2/6", w2.MAIN26), ("A+2/6+X01", {**w2.MAIN26, "x01_all": "add"})):
            leg = [x for x in w2.run(a2, **kw) if S.t[x[0]] >= frm and x[6] != "конец"]
            net = [x[4] * (x[3] / x[2] - 1) * 100 - 0.034 - 0.034 * (x[3] / x[2]) for x in leg]
            desc = [(not (x[4] == 1)) or bool(w2.in_portrait(a, x[0], 1)) for x in leg]
            half = sum(n * (1.0 if d else 0.5) for n, d in zip(net, desc))
            rows.append({"начало": st.strftime("%d.%m.%Y"), "что": mode, "сделок": len(leg), "итог_0.034": round(sum(net), 1), "итог_половина": round(half, 1)})
    d = pd.DataFrame(rows)
    print(d[d["сделок"].between(219, 225)].to_string(index=False))
    print("ближайшие к +12.2 при 218-226 сделках:")
    q = d[d["сделок"].between(218, 226)].copy()
    q["откл"] = (q["итог_половина"] - 12.2).abs()
    print(q.sort_values("откл").head(5).to_string(index=False))


if __name__ == "__main__":
    main()
