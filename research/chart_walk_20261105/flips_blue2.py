"""Перекладка по голубой 4ч с запасом 1%: контроль, годы, серии убытков, сравнение с держанием. Записано после flips_blue.py, запас 1% выбран там, соседи в out/flips_blue.csv."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import entry_rules as er  # noqa: E402
import flips_blue as fb  # noqa: E402
import history_v1 as hv  # noqa: E402
import pos  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 40, "display.max_rows", 100)


def streak(r):
    best = cur = 0
    for v in r:
        cur = cur + 1 if v <= 0 else 0
        best = max(best, cur)
    return best


def main():
    m, h1, h4, d1, fund = cw.load()
    del m
    a, _ = er.prep(h1, h4, d1, fund)
    m2, h1e, h4e, d1e, fe = pd.read_pickle(er.ETH_PKL)
    del m2
    h1e, h4e = cw.features(h1e, h4e, 1), cw.features(h4e, h1e, 4)
    e, _ = er.prep(h1e, h4e, d1e, fe)
    out = []
    for x, coin in ((a, "BTC"), (e, "ETH")):
        c0, c1 = x["c"][x["i0"]], x["c"][-1]
        cc = x["c"][x["i0"]:]
        pct = (cc / c0 - 1) * 100
        dd = float((pct - np.maximum.accumulate(pct)).min())
        print(coin, "держание: цена", round(float(c0)), "до", round(float(c1)), "итог %", round(float((c1 / c0 - 1) * 100)), "просадка % от входа", round(dd))
        for conf, band in ((1, 1), (2, 1)):
            d = fb.frame(x, fb.flip_legs(x, conf, band))
            r = d["pnl"].to_numpy()
            print(coin, f"закрытий {conf}, запас {band}%: по годам", d.groupby("год")["pnl"].sum().round(0).astype(int).to_dict(), "худшая", round(float(r.min()), 1), "лучшая", round(float(r.max()), 1), "серия убытков", streak(r), "сделок в год", round(len(r) / 8.85, 1))
            d["тип"] = f"{conf}/{band}"
            t = hv.group_table(x, d, "тип")
            t.insert(0, "монета", coin)
            out.append(t)
            real = {p: float(r[d["per"] == p].sum()) for p in pos.PER}
            cl = pos.control_fixed(x, d.loc[d["s"] == 1, "i0"].to_numpy(), (d.loc[d["s"] == 1, "i1"] - d.loc[d["s"] == 1, "i0"]).to_numpy(), 1)
            cs = pos.control_fixed(x, d.loc[d["s"] == -1, "i0"].to_numpy(), (d.loc[d["s"] == -1, "i1"] - d.loc[d["s"] == -1, "i0"]).to_numpy(), -1)
            ctl = {p: cl[p] + cs[p] for p in pos.PER}
            rk = pos.rank_row(real, ctl)
            print("  обе стороны:", {k: (v["сумма_%"], v["случайные_медиана_%"], v["лучше_случайного_%"]) for k, v in rk.items()})
    t = pd.concat(out)
    t.to_csv(pos.OUT / "flips_blue_control.csv", index=False)
    print(t.to_string(index=False))


if __name__ == "__main__":
    main()
