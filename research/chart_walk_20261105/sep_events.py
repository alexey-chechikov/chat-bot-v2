"""События линий 01–26.09.2026 и замер кандидата на флет: зелёная и жёлтая близко и пересекались. Сколько времени занимает, совпадает ли с окнами, которые оператор назвал флетом."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import entry_common as ec  # noqa: E402
import gpt_check as gc  # noqa: E402
import marks2_blind as mb  # noqa: E402
import pos  # noqa: E402
import words as wd  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 30, "display.max_rows", 400)
THEIR = (("05–28.12.25", "2025-12-05", "2025-12-28"), ("22.12–03.01", "2025-12-22", "2026-01-03"), ("10–21.07.26", "2026-07-10", "2026-07-21"), ("10–28.10.26", "2026-10-10", "2026-10-28"))
TREND = (("падение 28.01–06.02.26", "2026-01-28", "2026-02-06"), ("рост 01–15.09.26", "2026-09-01", "2026-09-15"), ("рост 01–05.07.26", "2026-07-01", "2026-07-05"), ("падение 01–10.03.25", "2025-03-01", "2025-03-10"), ("рост 21.04–01.05.25", "2025-04-21", "2025-05-01"))


def main():
    m, h1, h4, d1, fund = cw.load()
    del m
    a, _ = gc.er.prep(h1, h4, d1, fund)
    wd.add_runs(a)
    ev = mb.events(a, "2026-09-01", "2026-09-26")
    print(ev.to_string(index=False), flush=True)
    ec.extras(a)
    t = a["t"]
    gy = np.abs(a["f_G"] - a["f_Y"]) / a["atr4"]
    print("|G−Y| в ATR, квантили 10/25/50/75/90:", np.round(np.nanquantile(gy[a["i0"]:], [.1, .25, .5, .75, .9]), 2), flush=True)
    rows = []
    for k in (0.5, 0.75, 1.0, 1.5):
        for nc in (1, 2):
            fl = (gy <= k) & (a["x_cross"] >= nc)
            row = {"|G−Y|≤ATR×": k, "кроссов_10д≥": nc, "вся_история_%": round(float(fl[a["i0"]:].mean() * 100), 1)}
            for lab, x, z in THEIR + TREND:
                i0, i1 = int(np.searchsorted(t, cw.T(x))), int(np.searchsorted(t, cw.T(z)))
                row[lab] = round(float(fl[i0:i1].mean() * 100))
            rows.append(row)
    print(pd.DataFrame(rows).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
