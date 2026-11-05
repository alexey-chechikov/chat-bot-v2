"""Участок 2, вторая часть: версия правил 2 (слова записки 2), соседи точным списком, замеры в точках, 1ч вокруг сужения и 28.03."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import rules  # noqa: E402
import segment1 as s1  # noqa: E402
from segment2 import OUT, T0, T1, TM, split  # noqa: E402

gridk = cw.gridk
pd.set_option("display.width", 250, "display.max_columns", 60, "display.max_rows", 300)
V2 = {"tol": 0.5, "cross_only": 6, "priority": True, "entry_under": True}
POINTS = [("отбитие 93 400", "2025-03-06 06:00"), ("над Y4 + R1", "2025-03-11 20:00"), ("узко, под Y", "2025-03-13 16:00"), ("под Y", "2025-03-18 16:00"),
          ("отбитие 2", "2025-03-20 01:00"), ("сужение 21–23.03", "2025-03-22 12:00"), ("над голубой", "2025-03-24 12:00"), ("под голубой 28.03", "2025-03-28 04:00"),
          ("под обеими", "2025-03-28 08:00"), ("над Y 01.04", "2025-04-01 16:00"), ("цель 02.04", "2025-04-02 14:00"), ("под всеми 03.04", "2025-04-03 00:00"),
          ("сужение 05.04", "2025-04-05 16:00"), ("далеко 07.04", "2025-04-07 08:00"), ("дно 09.04", "2025-04-09 08:00"), ("над Y 09.04", "2025-04-09 20:00"),
          ("цель 11.04", "2025-04-11 18:00"), ("над голубой 12.04", "2025-04-12 16:00"), ("сужение 19.04", "2025-04-19 12:00"), ("выход 21.04", "2025-04-21 04:00"),
          ("под Y 26.04", "2025-04-26 20:00")]


def main():
    m, h1, h4, d1, fund = cw.load()
    mk = gridk.Market(m["ts"].to_numpy(), m["open"].to_numpy(), m["high"].to_numpy(), m["low"].to_numpy(), m["close"].to_numpy(), fund)
    a = rules.prepare(h1, h4)
    rows, res = [], {}

    def add(nm, kw, keep=False):
        tbl = rules.grid_legs(mk, rules.run(a, T0, T1, **kw), cw.utc)
        sa, sb, sall = split(tbl)
        rows.append({"вариант": nm, "A_$": sa["итог_$"], "B_$": sb["итог_$"], "всё_$": sall["итог_$"], "просадка": sall["просадка_от_пика_$"],
                     "A_пр": sa["просадка_от_пика_$"], "B_пр": sb["просадка_от_пика_$"], "ног": sall["ног"], "B_шорт": sb["шорт_$"], "B_лонг": sb["лонг_$"], "поз_B": sb.get("позиция_$1000_без_фандинга_$", 0)})
        res[nm] = {"A": sa, "B": sb, "всё": sall}
        if keep:
            tbl.to_csv(OUT / f"segment2_legs_{keep}.csv", index=False)
        return tbl

    add("v1: правила участка 1", {}, "v1")
    t2 = add("v2: слова записки 2", V2, "v2")
    add("v2 + не перекладываться, три TEMA <1%", {**V2, "min_w3": 1.0})
    add("v2 + выход лонга по 1ч", {**V2, "fast_long_exit": True})
    add("v2 без «далеко»", {**V2, "far": False})
    add("v2, кагал: закрыть и ждать", {**V2, "knot": "flat"})
    add("v2, кагал: две сетки", {**V2, "knot": "two"})
    for tol in (0.0, 0.25, 0.75, 1.0):
        add(f"v2, допуск цели {tol}%", {**V2, "tol": tol})
    for n in (0, 3, 12):
        add(f"v2, свежесть пересечения {n}", {**V2, "cross_only": n})
    for fg in (-4.0, -4.5, -5.5, -6.0):
        add(f"v2, далеко {fg}%", {**V2, "far_g": fg})
    for rk in (0.1, 0.2, 0.3):
        add(f"v2, ранг сужения {rk}", {**V2, "rank_max": rk})
    print(pd.DataFrame(rows).to_string(index=False))
    print(t2[t2["t1"] >= cw.T("2025-03-04")].drop(columns=["t0", "t1", "почему_открыта", "пик_номинал_$"]).to_string(index=False))
    pts = pd.DataFrame([s1.point_row(h1, h4, n, cw.T(t)) for n, t in POINTS])
    pts.to_csv(OUT / "segment2_points.csv", index=False)
    print(pts.iloc[:, :17].to_string(index=False))
    print(pts.iloc[:, [0, 1] + list(range(17, pts.shape[1]))].to_string(index=False))
    # 1ч: сужение 21–23.03 и порядок линий на 28.03
    w = h1[(h1["known"] >= cw.T("2025-03-20 12:00")) & (h1["known"] <= cw.T("2025-03-24 00:00"))]
    print("1ч 20–24.03: ширина", w["width"].min().round(2), w["width"].median().round(2), "ранг мин", w["width_rank"].min().round(2), "ATR% мин", w["atr_pct"].min().round(2), "объём к 30д мин", w["vol_vs30"].min().round(2),
          "диапазон", w["low"].min(), w["high"].max())
    w = h1[(h1["known"] >= cw.T("2025-03-27 20:00")) & (h1["known"] <= cw.T("2025-03-29 08:00"))]
    print(pd.DataFrame({"t": [cw.utc(int(x)) for x in w["known"]], "c": w["close"].round(), "G": w["G"].round(), "Y": w["Y"].round(), "R": w["R"].round(), "stack": w["stack"], "run_R": w["run_R"]}).iloc[::2].to_string(index=False))
    # сколько закрытий 4ч через голубую 24–28.03
    s = h4[(h4["known"] > cw.T("2025-03-24 00:00")) & (h4["known"] <= cw.T("2025-03-28 12:00"))]
    print("пересечений голубой 4ч 24–28.03:", int((np.sign(s["run_B"]).diff().abs() > 0).sum()), "диапазон", s["low"].min(), s["high"].max(), "d_B мин/макс", s["d_B"].min().round(2), s["d_B"].max().round(2))
    (OUT / "segment2b.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
