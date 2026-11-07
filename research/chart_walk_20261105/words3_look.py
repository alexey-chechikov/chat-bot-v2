"""Записки 06.11 как автомат: сверка с его точками и деньги ядра на четырёх рядах против варианта A + 2/6."""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import entry_common as ec  # noqa: E402
import pos  # noqa: E402
import state_map as sm  # noqa: E402
import words2 as w2  # noqa: E402
import words3 as w3  # noqa: E402

pd.set_option("display.width", 260, "display.max_columns", 40, "display.max_rows", 300)
PK = cw.SCR / "w3_series.pkl"


def series():
    if PK.exists():
        return pickle.load(open(PK, "rb"))
    out = []
    for k, a, f in ec.load_all():
        sm.add_state(a)
        out.append((k, a, f))
    pickle.dump(out, open(PK, "wb"))
    return out


def main():
    S = series()
    k, a, f = S[0]
    legs = w3.run(a)
    r = w3.recall(a, legs)
    print(r.to_string(index=False), flush=True)
    print("совпало", int(r["совпало"].sum()), "из", len(r), flush=True)
    t = a["t"]
    rows = []
    for x in legs:
        if t[x[0]] >= sm.T("2024-10-01") and t[x[0]] < sm.T("2024-12-10") or t[x[0]] >= sm.T("2024-12-28") and t[x[0]] < sm.T("2025-03-01") or t[x[0]] >= sm.T("2025-08-01") and t[x[0]] < sm.T("2025-09-25") or t[x[0]] >= sm.T("2026-01-10") and t[x[0]] < sm.T("2026-04-08"):
            rows.append({"вход": sm.utc(t[x[0]]), "выход": sm.utc(t[x[1]]), "с": x[4], "тип": x[5], "причина": x[6], "p0": round(x[2]), "p1": round(x[3]), "итог": round(w2.net(f, x), 2)})
    d = pd.DataFrame(rows)
    d.to_csv(pos.OUT / "w3_windows.csv", index=False)
    print(d.to_string(index=False), flush=True)
    res = []
    for k, a, f in S:
        for lab, fn in (("A+2/6", lambda: w2.run(a, **w2.MAIN26)), ("A", lambda: w2.run(a, **w2.MAIN)), ("ядро", lambda: w3.run(a)), ("ядро без выстроенных", lambda: w3.run(a, l_align=False, s_align=False))):
            res.append({"ряд": k, "вариант": lab, **w3.stats(a, f, fn())})
    print(pd.DataFrame(res).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
