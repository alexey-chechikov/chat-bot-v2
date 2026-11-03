"""Сверка с GPT c188548 (`docs/WEEX_GPT_432_R2_AND_EXPANDED_RESEARCH_2026-11-03.md` §2–3): 432 BTC/ETH H4, база, R2 и
ADX3 по календарным отрезкам GPT (2022–23, 2024, 2025, янв.–окт. 2026) на наших данных Binance spot.
Размер R2 тот же, что в my_rules.py (медиана ATR% за 2190 H4, мин. 500, без текущего бара; вес 0.5–2).
Итог/просадка не зависит от общего масштаба — «равная экспозиция» GPT его не меняет.
Запуск: r2_years.py --pk-btc=<pkl> --pk-eth=<pkl>"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import my_rules as M  # noqa: E402
from review import Data, run  # noqa: E402

YEARS = {"2022–23": ("2022-01-01", "2024-01-01"), "2024": ("2024-01-01", "2025-01-01"),
         "2025": ("2025-01-01", "2026-01-01"), "2026 янв–окт": ("2026-01-01", "2026-11-01")}


def main():
    args = dict(a.lstrip("-").split("=", 1) for a in sys.argv[1:])
    M.PERIODS = YEARS
    M.ALL = ("2022-01-01", "2026-11-01")
    for sym in ("BTC", "ETH"):
        D = Data(Path(args[f"pk-{sym.lower()}"]))
        base = run(D, 1)
        atrp = D.atr / D.c
        med = pd.Series(atrp).rolling(2190, min_periods=500).median().shift(1).to_numpy()
        w = np.where(np.isfinite(np.clip(med / atrp, 0.5, 2.0)), np.clip(med / atrp, 0.5, 2.0), 1.0)
        a3 = [u for u in base if D.adx[u["sig"]] > D.adx[u["sig"] - 3]]
        rows = {"база": M.eq_stats(D, M.legs_432(base)), "R2": M.eq_stats(D, M.legs_432(base, w))}
        # ADX3 как отдельная политика (а не отбор из сделок базы): заново, вход только при ADX[t] > ADX[t−3]
        ent0 = D.ent[1].copy()
        adx3 = np.zeros(len(D.c), bool)
        adx3[3:] = D.adx[3:] > D.adx[:-3]
        D.ent[1] = ent0 & adx3
        f = run(D, 1)
        D.ent[1] = ent0
        rows["ADX3"] = M.eq_stats(D, M.legs_432(f))
        rows["ADX3 + R2"] = M.eq_stats(D, M.legs_432(f, w))
        print(f"\n== {sym} H4 (Binance spot), итог % номинала / просадка % / итог÷просадка; отбор из сделок базы ≠ ADX3 "
              f"({len(a3)} из {len(base)} сделок базы прошли бы фильтр, у политики ADX3 сделок {len(f)})")
        cols = list(YEARS) + ["всё"]
        print("| Вариант | " + " | ".join(cols) + " |")
        print("|---|" + "---|" * len(cols))
        for nm, r in rows.items():
            print(f"| {nm} | " + " | ".join(f"{r[p]['n']} · {r[p]['sum']:+.1f} / {r[p]['dd']:.1f} / "
                                             f"{(r[p]['ratio'] or 0):.2f}" for p in cols) + " |")


if __name__ == "__main__":
    main()
