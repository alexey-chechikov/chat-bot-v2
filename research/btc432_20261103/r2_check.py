"""R2 «размер по волатильности» — устойчивость (проверено ПОСЛЕ результата my_rules.py, выбранный вариант не меняется):
9 соседей (пределы веса × окно медианы), средний вес по периодам, та же проверка на ETH.
Запуск: r2_check.py --pk-btc=<pkl> --pk-eth=<pkl>"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from my_rules import eq_stats, legs_432  # noqa: E402
from review import PERIODS, Data, run, ts  # noqa: E402


def main():
    args = dict(a.lstrip("-").split("=", 1) for a in sys.argv[1:])
    for sym, key in (("BTC", "pk-btc"), ("ETH", "pk-eth")):
        D = Data(Path(args[key]))
        base = run(D, 1)
        r0 = eq_stats(D, legs_432(base))
        atrp = D.atr / D.c
        print(f"\n{sym}: L0 итог/просадка " + " · ".join(f"{p} {r0[p]['ratio']:.2f}" for p in list(PERIODS) + ["всё"]))
        print(f"| {sym}: пределы веса / окно медианы | " + " | ".join(f"{p}: сумма · просадка · итог/просадка" for p in PERIODS)
              + " | ср. вес A / B / C | лучше L0 во всех трёх |")
        for lo_, hi_ in ((0.67, 1.5), (0.5, 2.0), (0.33, 3.0)):
            for win, wname in ((1095, "6 мес"), (2190, "1 год"), (4380, "2 года")):
                med = pd.Series(atrp).rolling(win, min_periods=min(500, win)).median().shift(1).to_numpy()
                w = np.clip(med / atrp, lo_, hi_)
                w = np.where(np.isfinite(w), w, 1.0)
                r = eq_stats(D, legs_432(base, w))
                mw = []
                for p, (a, b) in PERIODS.items():
                    ws = [w[u["first"]] for u in base if ts(a) <= D.t[u["j"]] < ts(b)]
                    mw.append(np.mean(ws) if ws else np.nan)
                better = all(r[p]["ratio"] > r0[p]["ratio"] for p in PERIODS)
                print(f"| {lo_}–{hi_} / {wname} | " + " | ".join(f"{r[p]['sum']:+.1f} · {r[p]['dd']:.1f} · {r[p]['ratio']:.2f}"
                                                                 for p in PERIODS)
                      + f" | {mw[0]:.2f} / {mw[1]:.2f} / {mw[2]:.2f} | {'да' if better else 'нет'} |")


if __name__ == "__main__":
    main()
