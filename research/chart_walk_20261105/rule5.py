"""B. Правило «над голубой 1ч и над жёлтой 4ч» и соседи: позиция, пока условие верно. Правила — PREREG_positions.md."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import pos  # noqa: E402

pd.set_option("display.width", 250, "display.max_columns", 40, "display.max_rows", 200)


def legs_of(state: np.ndarray, i_from: int, conf: int) -> list[tuple[int, int]]:
    """Вход после conf подряд часов с условием, выход после conf подряд часов без него. Закрытие часа."""
    legs, on, run_t, run_f, s = [], False, 0, 0, 0
    for i in range(i_from, len(state)):
        if state[i]:
            run_t += 1
            run_f = 0
        else:
            run_f += 1
            run_t = 0
        if not on and run_t >= conf:
            on, s = True, i
        elif on and run_f >= conf:
            legs.append((s, i))
            on = False
    if on:
        legs.append((s, len(state) - 1))
    return legs


def evaluate(a, name, state, side, conf, filt=None):
    """filt: 'под' — только входы под голубой 4ч, 'над' — только над ней."""
    legs = legs_of(state, a["i0"], conf)
    i0 = np.array([x for x, _ in legs])
    i1 = np.array([y for _, y in legs])
    above = a["f_close"][i0] > a["f_B"][i0]
    if filt == "под":
        keep = ~above
    elif filt == "над":
        keep = above
    else:
        keep = np.ones(len(i0), dtype=bool)
    i0, i1 = i0[keep], i1[keep]
    r = pos.pnl(a, i0, i1, side)
    t = a["t"]
    per = pos.period_of(t[i0])
    real = {p: float(r[per == p].sum()) for p in pos.PER}
    ctl = pos.control_fixed(a, i0, i1 - i0, side)
    rk = pos.rank_row(real, ctl)
    st = pos.stats(r)
    row = {"правило": name, "вход": filt or "все", "подтв": conf, "n": st["n"], "среднее_%": st["среднее_%"], "плюс_%": st["плюс_%"], "сумма_%": st["сумма_%"], "ди_низ": st["ди_низ"],
           "ди_верх": st["ди_верх"], "просадка_%": pos.max_dd(r), "часов_медиана": float(np.median(i1 - i0)) if len(i0) else 0}
    for p in pos.PER:
        row[f"{p}_%"] = rk[p]["сумма_%"]
        row[f"{p}_лучше"] = rk[p]["лучше_случайного_%"]
    row["всё_лучше_%"] = rk["всё"]["лучше_случайного_%"]
    row["случайные_медиана_%"] = rk["всё"]["случайные_медиана_%"]
    row["годно"] = bool(st["n"] >= 100 and all(rk[p]["сумма_%"] > 0 for p in pos.PER) and st["ди_низ"] > 0 and rk["всё"]["лучше_случайного_%"] >= 95)
    return row, r, i0, i1


def main():
    a, h1, h4, d1, fund = pos.load()
    c = a["c"]
    fc = a["f_close"]
    base_l = {"голубая 1ч + жёлтая 4ч": (c > a["B1h"]) & (fc > a["f_Y"]), "красная 1ч + жёлтая 4ч": (c > a["R1"]) & (fc > a["f_Y"]),
              "голубая 1ч + зелёная 4ч": (c > a["B1h"]) & (fc > a["f_G"]), "голубая 1ч + красная 4ч": (c > a["B1h"]) & (fc > a["f_R"]),
              "красная 1ч + жёлтая и зелёная 4ч": (c > a["R1"]) & (fc > a["f_Y"]) & (fc > a["f_G"])}
    base_s = {"голубая 1ч + жёлтая 4ч": (c < a["B1h"]) & (fc < a["f_Y"]), "красная 1ч + жёлтая 4ч": (c < a["R1"]) & (fc < a["f_Y"]),
              "голубая 1ч + зелёная 4ч": (c < a["B1h"]) & (fc < a["f_G"]), "голубая 1ч + красная 4ч": (c < a["B1h"]) & (fc < a["f_R"]),
              "красная 1ч + жёлтая и зелёная 4ч": (c < a["R1"]) & (fc < a["f_Y"]) & (fc < a["f_G"])}
    rows = []
    for side, sname, base in ((1, "лонг", base_l), (-1, "шорт", base_s)):
        for nm, st in base.items():
            for conf in (1, 3):
                for filt in (None, "под", "над"):
                    row, r, i0, i1 = evaluate(a, nm, st, side, conf, filt)
                    row = {"сторона": sname, **row}
                    rows.append(row)
    t = pd.DataFrame(rows)
    t.to_csv(pos.OUT / "rule5_table.csv", index=False)
    show = ["сторона", "правило", "вход", "подтв", "n", "среднее_%", "плюс_%", "сумма_%", "ди_низ", "просадка_%", "часов_медиана", "A_%", "B_%", "C_%", "A_лучше", "B_лучше", "C_лучше", "всё_лучше_%", "случайные_медиана_%", "годно"]
    print(t[show].to_string(index=False))
    print("годных:", int(t["годно"].sum()), "из", len(t))


if __name__ == "__main__":
    main()
