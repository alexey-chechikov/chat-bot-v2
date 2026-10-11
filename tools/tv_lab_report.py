"""Отчёт лаборатории индикаторов: пять ворот из CLAUDE.md поверх tv_lab_cells.csv.

Ворота:
 1 издержки — медианный стоп ≥ 0.36% цены;
 2 время — плюс и лучше контроля в КАЖДОМ периоде (old/mid/fresh), свежий сам по себе;
 3 интервал — в свежем периоде n ≥ 100 и нижняя граница 95% интервала > 0;
 4 плоская поверхность — соседние ячейки (стоп ±шаг, RR ±шаг) в свежем тоже в плюсе;
 5 живое против бэктеста — для новых сигналов живого журнала нет: прошедшие 1–4
   идут только в бумажный журнал.

    .venv/bin/python3 tools/tv_lab_report.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CELLS = ROOT / "state" / "research" / "tv_lab_cells.csv"
ATR_ORDER = ["atr1", "atr1.5", "atr2"]
RR_ORDER = [2.0, 3.0, 5.0]


def gates(d: pd.DataFrame) -> pd.DataFrame:
    d = d[d.signal != "_control"].copy()
    d["g1"] = d.stop_pct_med >= 0.0036
    ok = pd.Series(True, d.index)
    for p in ("old", "mid", "fresh"):
        has = d[f"{p}_n"].fillna(0) >= 30
        good = (d[f"{p}_mean"] > 0) & (d[f"{p}_mean"] > d[f"{p}_ctrl"])
        ok &= good | (~has & (p != "fresh"))
    d["g2"] = d.g1 & ok & (d.fresh_n.fillna(0) >= 30)
    d["g3"] = d.g2 & (d.fresh_n >= 100) & (d.fresh_lo > 0)
    key = ["sym", "tf", "signal", "side"]
    pos = d.set_index(key + ["stop", "rr"]).fresh_mean > 0

    def neigh_ok(r) -> bool:
        cells = []
        i = RR_ORDER.index(r.rr)
        for j in (i - 1, i + 1):
            if 0 <= j < 3:
                cells.append((r.stop, RR_ORDER[j]))
        if r.stop in ATR_ORDER:
            s = ATR_ORDER.index(r.stop)
            for j in (s - 1, s + 1):
                if 0 <= j < 3:
                    cells.append((ATR_ORDER[j], r.rr))
        base = (r.sym, r.tf, r.signal, r.side)
        return all(bool(pos.get(base + c, False)) for c in cells)

    d["g4"] = False
    m = d.g3
    d.loc[m, "g4"] = [neigh_ok(r) for r in d[m].itertuples()]
    return d


def main() -> None:
    raw = pd.read_csv(CELLS)
    d = gates(raw)
    n = len(d)
    print(f"ячеек (монета × ТФ × сигнал × сторона × стоп × RR): {n}")
    for g, txt in (("g1", "1 издержки"), ("g2", "2 время: плюс и лучше контроля в каждом периоде"),
                   ("g3", "3 свежий: n≥100 и интервал выше нуля"), ("g4", "4 соседние ячейки тоже в плюсе")):
        print(f"  прошли до ворот {txt}: {int(d[g].sum())}")
    surv = d[d.g4].sort_values("fresh_mean", ascending=False)
    cols = ["sym", "tf", "signal", "side", "stop", "rr", "stop_pct_med", "old_mean", "mid_mean",
            "fresh_n", "fresh_mean", "fresh_lo", "fresh_wr", "fresh_ctrl", "fresh_pf"]
    pd.set_option("display.width", 250)
    print(surv[cols].round(3).to_string() if len(surv) else "выживших нет")
    near = d[d.g2 & ~d.g3].sort_values("fresh_lo", ascending=False)
    print("\nпрошли время, но не интервал (лучшие 25 по нижней границе):")
    print(near[cols].head(25).round(3).to_string())
    # сколько комбинаций сигнал×сторона×ТФ прошли 2 ворота хоть на одной монете
    by = d[d.g2].groupby(["signal", "side", "tf"]).sym.nunique().sort_values(ascending=False)
    print("\nсигнал прошёл ворота времени на скольких монетах (из 4):")
    print(by.head(30).to_string())
    d.to_csv(CELLS.with_name("tv_lab_gated.csv"), index=False)


if __name__ == "__main__":
    main()
