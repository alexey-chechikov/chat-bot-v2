"""С какого первого бара часового графика TradingView получаются его 222 сделки и +12.2% при издержке Pine 0.034% на сторону. Перебор начала по дням, 2/6 включён (стоп и тейк видны в его таблице), X01 обоих положений."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import bybit_check as bc  # noqa: E402
import bybit_combos as bk  # noqa: E402
import pine_mirror as pm  # noqa: E402
import state_map as sm  # noqa: E402

pd.set_option("display.width", 220, "display.max_columns", 30, "display.max_rows", 200)


def main():
    a = bc.load_bybit()
    t = a["t"]
    frm = sm.T("2025-01-01")
    rows = []
    for s in pd.date_range("2024-12-25", "2025-07-01", freq="1D"):
        a["i0"] = int(np.searchsorted(t, int(s.timestamp())))
        for x in (False, True):
            n, tot, sl, ss = bk.total(a, pm.run(a, optX01=x), frm, True)
            rows.append({"X01": x, "старт": s.strftime("%Y-%m-%d"), "n": n, "итог": tot, "лонг": sl, "шорт": ss, "баров_до_конца": len(t) - a["i0"]})
    d = pd.DataFrame(rows)
    d["до_цели"] = (d["n"] - 222).abs() + (d["итог"] - 12.2).abs()
    print(d.sort_values("до_цели").head(10).drop(columns="до_цели").to_string(index=False), flush=True)
    g = d[~d["X01"]]
    print("без X01: итог мин/медиана/макс", g["итог"].min(), g["итог"].median(), g["итог"].max(), flush=True)
    print(g.iloc[::10].drop(columns=["X01", "до_цели"]).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
