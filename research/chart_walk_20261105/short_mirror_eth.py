"""Шорт сверху к голубой (зеркало лонга к голубой) на BTC и ETH после исправления знака в tp_blue.outcomes: без тейка и с тейком половина пути."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import entry_rules as er  # noqa: E402
import pos  # noqa: E402
import tp_blue as tb  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 40)


def main():
    m, h1, h4, d1, fund = cw.load()
    del m
    a, _ = er.prep(h1, h4, d1, fund)
    m2, h1e, h4e, d1e, fe = pd.read_pickle(er.ETH_PKL)
    del m2
    h1e, h4e = cw.features(h1e, h4e, 1), cw.features(h4e, h1e, 4)
    e, _ = er.prep(h1e, h4e, d1e, fe)
    tb.FR = [0.5]
    rows = []
    for x, coin in ((a, "BTC"), (e, "ETH")):
        arr = tb.make_arrays(x, -1)
        ev = tb.events(x, -1, "L1", arr)
        per = pos.period_of(x["t"][ev])
        for stop in ("S0", "S2", "S3"):
            out = tb.outcomes(x, arr, ev, -1, stop)
            for nm in ("без_тейка", "y0", "f0.5"):
                v = out[nm]
                ok = ~np.isnan(v)
                st = pos.stats(v[ok])
                rows.append({"монета": coin, "стоп": stop, "тейк": nm, "n": st["n"], "среднее_%": st["среднее_%"], "плюс_%": st["плюс_%"], "сумма_%": st["сумма_%"], "просадка_%": pos.max_dd(v[ok]), **{p: round(float(v[ok & (per == p)].sum()), 1) for p in pos.PER}, "ди_низ": st["ди_низ"]})
    t = pd.DataFrame(rows)
    t.to_csv(pos.OUT / "short_mirror_coins.csv", index=False)
    print(t.to_string(index=False))


if __name__ == "__main__":
    main()
