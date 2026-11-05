"""Отдельно от автомата: «ушли далеко от зелёной, вернулись к ней, не пробили — снова шорт» (и зеркало лонга) на BTC и ETH, соседи порогов, стопы и тейки.
Дописано после history_v1 (там reshort лучший из шортов, но зависит от других сделок автомата). Плюс сводка кандидатов одной строкой на период."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import history_v1 as hv  # noqa: E402
import pos  # noqa: E402
import rule5  # noqa: E402
import tp_blue as tb  # noqa: E402
import tp_blue2 as tb2  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 40, "display.max_rows", 200)


def r1_legs(a, side, far, near):
    """side −1: 4ч ниже зелёной на far% или дальше, затем ближе near% под ней без закрытия над ней — шорт. Выход: снова далеко, или через зелёную и жёлтую + 3 закрытия 1ч через красную."""
    legs = []
    t, j = a["t"], a["j"]
    dg = a["f_d_G"] * side
    fc, fg, fy = a["f_close"], a["f_G"], a["f_Y"]
    if side == -1:
        back = fc > fg
        brk = (fc > fg) & (fc > fy) & (a["run_R"] >= 3)
    else:
        back = fc < fg
        brk = (fc < fg) & (fc < fy) & (a["run_R"] <= -3)
    seen, cur, j_prev = False, None, -1
    for i in range(a["i0"], len(t)):
        new4 = j[i] != j_prev
        j_prev = j[i]
        if cur is not None:
            if (new4 and dg[i] >= far) or brk[i]:
                legs.append((cur, i))
                cur = None
                seen = bool(dg[i] >= far)
            continue
        if not new4:
            continue
        if dg[i] >= far:
            seen = True
        elif back[i]:
            seen = False
        elif seen and 0 < dg[i] < near:
            cur, seen = i, False
    if cur is not None:
        legs.append((cur, len(t) - 1))
    return legs


def frame(a, legs, side):
    d = pd.DataFrame(legs, columns=["i0", "i1"])
    d["s"] = side
    d["p0"], d["p1"] = a["c"][d["i0"]], a["c"][d["i1"]]
    d["pnl"] = pos.pnl(a, d["i0"].to_numpy(), d["i1"].to_numpy(), side)
    d["per"] = pos.period_of(a["t"][d["i0"]])
    return d


def row_of(a, d, label):
    st = pos.stats(d["pnl"].to_numpy())
    real = {p: float(d.loc[d["per"] == p, "pnl"].sum()) for p in pos.PER}
    rk = pos.rank_row(real, pos.control_fixed(a, d["i0"].to_numpy(), (d["i1"] - d["i0"]).to_numpy(), int(d["s"].iloc[0])))
    return {"что": label, "n": st["n"], "среднее_%": st["среднее_%"], "плюс_%": st["плюс_%"], "сумма_%": st["сумма_%"], "просадка_%": pos.max_dd(d["pnl"].to_numpy()), "A_%": rk["A"]["сумма_%"], "B_%": rk["B"]["сумма_%"], "C_%": rk["C"]["сумма_%"],
            "ди_низ": st["ди_низ"], "лучше_случайного_%": rk["всё"]["лучше_случайного_%"], "случайные_медиана_%": rk["всё"]["случайные_медиана_%"]}


def main():
    a, h1, h4, d1, fund = pos.load()
    e = tb2.eth_arrays()
    rows = []
    for coin, x in (("BTC", a), ("ETH", e)):
        for side, nm in ((-1, "шорт"), (1, "лонг")):
            for far, near in ((5, 1), (3, 1), (4, 1), (6, 1), (7, 1), (5, 0.5), (5, 1.5), (5, 2)):
                d = frame(x, r1_legs(x, side, far, near), side)
                if len(d) < 10:
                    continue
                rows.append({"монета": coin, "сторона": nm, "далеко": far, "близко": near, **row_of(x, d, "по правилу")})
    t = pd.DataFrame(rows).drop(columns=["что"])
    t.to_csv(pos.OUT / "short_r1_table.csv", index=False)
    print(t.to_string(index=False))
    # стопы и тейки для шорта R1 на BTC и ETH, базовые пороги
    for coin, x in (("BTC", a), ("ETH", e)):
        d = frame(x, r1_legs(x, -1, 5, 1), -1)
        g = pd.DataFrame([{"стоп": k or 0, "тейк": m or 0, "сумма": round(float(np.sum([hv.manage(x, r, k, m) for r in d.itertuples()])), 1)} for k in (None, 1.0, 1.5, 2.0, 3.0) for m in (None, 1.0, 2.0, 3.0, 5.0)])
        print(coin, "шорт R1, сумма % при стопе (строка) и тейке (столбец) в ATR 4ч")
        print(g.pivot(index="стоп", columns="тейк", values="сумма").to_string())
    # сводка кандидатов BTC
    x = tb.make_arrays(a, 1)
    ev = tb.events(a, 1, "L1", x)
    tb.FR = [0.4, 0.5]
    l1 = tb.outcomes(a, x, ev, 1, "S2")["f0.5"]
    l1_per = pos.period_of(a["t"][ev])
    _, r5, i0, i1 = rule5.evaluate(a, "над", (a["c"] > a["B1h"]) & (a["f_close"] > a["f_Y"]), 1, 3, "над")
    r5_per = pos.period_of(a["t"][i0])
    rs = frame(a, r1_legs(a, -1, 5, 1), -1)
    parts = [("лонг к голубой L1, тейк половина пути, стоп 3 ATR", l1, l1_per, a["t"][ev]), ("лонг над голубыми и жёлтой 4ч", r5, r5_per, a["t"][i1]),
             ("шорт после возврата к зелёной", rs["pnl"].to_numpy(), rs["per"].to_numpy(), a["t"][rs["i1"].to_numpy()])]
    all_r, all_t = [], []
    for nm, v, per, tt in parts:
        print(nm, "n", len(v), "сумма", round(float(v.sum()), 1), {p: round(float(v[per == p].sum()), 1) for p in pos.PER}, "просадка", pos.max_dd(v))
        all_r.append(v)
        all_t.append(tt)
    r, tt = np.concatenate(all_r), np.concatenate(all_t)
    o = np.argsort(tt)
    per = pos.period_of(tt[o])
    print("всего трёх: n", len(r), "сумма", round(float(r.sum()), 1), {p: round(float(r[o][per == p].sum()), 1) for p in pos.PER}, "просадка", pos.max_dd(r[o]), "в год", round(len(r) / 8.85, 1))


if __name__ == "__main__":
    main()
