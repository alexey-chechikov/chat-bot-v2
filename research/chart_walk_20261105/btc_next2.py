"""Проверка по времени на одном BTC: настройка добора и порог фандинга выбираются только по 2018–2022 (лучшее итог/просадка), смотрим 2023–2026. Плюс совместный прогон. Кривая по часам с открытыми сделками, разрез на 01.01.2023."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import btc_lab as bl  # noqa: E402
import btc_next as bn  # noqa: E402
import cw_data as cw  # noqa: E402
import plus as pl  # noqa: E402
import state_map as sm  # noqa: E402

pd.set_option("display.width", 220, "display.max_columns", 30, "display.max_rows", 60, "display.max_colwidth", 50)
CUTY = sm.T("2023-01-01")


def parts(a, f, legs):
    eq = pl.curve(a, f, legs)
    k = int(np.searchsorted(a["t"], CUTY))
    b = a["i0"]
    n = int(np.searchsorted(a["t"], bl.CUT, side="right")) - 1

    def seg(x, y):
        e = eq[x:y + 1] - eq[x]
        d = float((e - np.maximum.accumulate(e)).min())
        return round(float(e[-1]), 1), round(d, 1), round(float(e[-1]) / max(abs(d), 1.0), 2)

    return seg(b, k), seg(k, n)


def main():
    (a, f, lay), (b, fb, layb) = bl.load()
    C = {"cs": 1.0}
    la0, lb0 = bl.run(a, lay, cut=bl.CUT, rules=C), bl.run(b, layb, rules=C)
    p1, p2 = parts(a, f, la0)
    print("база 2018–22:", p1, "2023–26:", p2, flush=True)
    rows = []
    for first, add in ((1.0, 0.5), (1.0, 1.0), (0.75, 0.5), (0.75, 1.0), (0.5, 0.5), (0.5, 1.0), (0.5, 1.5)):
        for xl, xs in ((2, 2), (3, 2), (3, 3), (4, 2), (4, 3), (5, 3), (6, 3), (4, None), (None, 3)):
            x, y = parts(a, f, bn.pyramid(a, la0, xl, xs, first, add))
            rows.append({"вариант": f"первый {first}, добор {add}, лонг +{xl}, шорт +{xs}", "итог1": x[0], "пр1": x[1], "отн1": x[2], "итог2": y[0], "пр2": y[1], "отн2": y[2]})
    d = pd.DataFrame(rows)
    d.to_csv(bl.OUT / "btc_next2_pyramid.csv", index=False)
    print("== добор: лучшие 5 по 2018–22 и что они дали в 2023–26; связь рангов половин", round(float(d["отн1"].rank().corr(d["отн2"].rank())), 2), flush=True)
    print(d.sort_values("отн1", ascending=False).head(5).to_string(index=False), flush=True)
    print("вариантов лучше базы в обеих частях:", int(((d["отн1"] > p1[2]) & (d["отн2"] > p2[2])).sum()), "из", len(d), flush=True)

    fund = cw.load()[4]
    fs = pd.Series(fund.to_numpy(float))
    rk = fs.rolling(9, min_periods=3).mean().rolling(1096, min_periods=270).rank(pct=True).to_numpy()
    idx = np.searchsorted(fund.index.to_numpy(np.int64), a["t"], side="right") - 1
    hr = np.where(idx >= 0, rk[np.clip(idx, 0, None)], np.nan)
    rows = []
    for th in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7):
        x, y = parts(a, f, bl.run(a, lay, cut=bl.CUT, rules=C, sok=~(hr < th)))
        rows.append({"порог": th, "итог1": x[0], "пр1": x[1], "отн1": x[2], "итог2": y[0], "пр2": y[1], "отн2": y[2]})
    print("== фандинг по частям", flush=True)
    print(pd.DataFrame(rows).to_string(index=False), flush=True)

    rows = [{"вариант": "база", **bl.row(a, f, la0), "Bitstamp": pl.stats(b, fb, lb0)["итог"], "пик": bn.peak(la0, len(a["t"]))}]
    for th in (None, 0.3, 0.5):
        sok = None if th is None else ~(hr < th)
        lf = bl.run(a, lay, cut=bl.CUT, rules=C, sok=sok)
        for lab, cfg in (("без добора", None), ("0.5 + 0.5 на +2/+2", (2, 2, 0.5, 0.5)), ("0.5 + 0.5 на +4/+2", (4, 2, 0.5, 0.5)), ("0.75 + 0.5 на +2/+2", (2, 2, 0.75, 0.5))):
            la = lf if cfg is None else bn.pyramid(a, lf, *cfg)
            lb = lb0 if cfg is None else bn.pyramid(b, lb0, *cfg)
            x, y = parts(a, f, la)
            rows.append({"вариант": f"фандинг {th}, {lab}", **bl.row(a, f, la), "Bitstamp": pl.stats(b, fb, lb)["итог"], "пик": bn.peak(la, len(a["t"])), "отн1": x[2], "отн2": y[2]})
    q = pd.DataFrame(rows)
    q.to_csv(bl.OUT / "btc_next2_combo.csv", index=False)
    print(q[["вариант", "итог", "просадка", "отн", "с2025", "18–21", "22–07.24", "08.24–26", "Bitstamp", "пик", "отн1", "отн2"]].to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
