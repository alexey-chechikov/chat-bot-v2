"""Контроль частей Простого+ с пересчётом потока: ранг и вес сдвигаются по кругу на случайное время, сделки считаются заново. Плюс веса вперемешку на сделках без фильтра, для сверки с цифрой Вина 99.2%. Ряды поиска, резерв не участвует."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import plus as pl  # noqa: E402
import state_card as sc  # noqa: E402
import state_map as sm  # noqa: E402
import words3_sweep as ws  # noqa: E402

pd.set_option("display.width", 220, "display.max_columns", 30)
REPS = 99


def main():
    cut = sm.T("2026-11-07")
    S = []
    for k in ("BTC", "ETH"):
        a, f, _ = sc.load_coin(k)
        S.append((k, a, f))
    for k, grp, a, f in ws.series():
        if k in ("Bitstamp", "XRP"):
            S.append((k, a, f))
    rng = np.random.default_rng(20261107)
    rows = []
    for k, a, f in S:
        rk, W = pl.layer(a)
        n = len(rk)
        real = pl.stats(a, f, pl.run(a, cut=cut, lay=(rk, W)))
        shifts = rng.integers(90 * 24, n - 90 * 24, size=REPS)
        for lab, fn in (("ранг сдвинут, вес настоящий", lambda s: (np.roll(rk, s), W)), ("вес сдвинут, ранг настоящий", lambda s: (rk, np.roll(W, s))), ("оба сдвинуты", lambda s: (np.roll(rk, s), np.roll(W, s)))):
            tot, rat = [], []
            for s in shifts:
                st = pl.stats(a, f, pl.run(a, cut=cut, lay=fn(int(s))))
                tot.append(st["итог"])
                rat.append(st["отн"])
            tot, rat = np.array(tot), np.array(rat)
            rows.append({"ряд": k, "что": lab, "настоящий_итог": real["итог"], "медиана_итог": round(float(np.median(tot)), 1), "лучше_итог_%": round(float((tot < real["итог"]).mean() * 100)), "настоящее_отн": real["отн"], "медиана_отн": round(float(np.median(rat)), 2), "лучше_отн_%": round(float((rat < real["отн"]).mean() * 100))})
        legs = pl.run(a, cut=cut, lay=(rk, W), rank_th=None)
        r, w = pl.unit(f, legs)
        rl = float((r * w).sum())
        ctl = np.array([float((r * rng.permutation(w)).sum()) for _ in range(9999)])
        rows.append({"ряд": k, "что": "веса вперемешку, сделки без фильтра", "настоящий_итог": round(rl, 1), "медиана_итог": round(float(np.median(ctl)), 1), "лучше_итог_%": round(float((ctl < rl).mean() * 100), 1)})
        print(k, "готово", flush=True)
    d = pd.DataFrame(rows)
    d.to_csv(Path(__file__).parent / "out" / "plus_ctl.csv", index=False)
    print(d.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
