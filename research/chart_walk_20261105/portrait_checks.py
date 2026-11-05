"""Основной вариант (words2.MAIN) на четырёх просмотренных рядах: соседи точным списком, годы, контроль сдвигами, блочный интервал, сделки во флете (только счёт, флет за скобками), сделки в окнах оператора."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import entry_common as ec  # noqa: E402
import ledger as lg  # noqa: E402
import pos  # noqa: E402
import words as wd  # noqa: E402
import words2 as w2  # noqa: E402

pd.set_option("display.width", 260, "display.max_columns", 40, "display.max_rows", 400)
NEI = (("основной", {}), ("наклон 3д", {"slope_d": 3}), ("наклон 10д", {"slope_d": 10}), ("k4=1", {"k4": 1}), ("k4=3", {"k4": 3}), ("k1=2", {"k1": 2}), ("k1=4", {"k1": 4}), ("запас голубой 0.25%", {"tol": 0.25}), ("запас голубой 1%", {"tol": 1.0}), ("далеко −4%", {"far_g": -4.0}), ("далеко −6%", {"far_g": -6.0}))
WIN = (("28.11.25–02.01.26", "2025-11-28", "2026-01-02"), ("09.06–21.07.26", "2026-06-09", "2026-07-21"), ("29.09–05.11.26", "2026-09-29", "2026-11-07"))


def total(fm, legs):
    return sum(w2.net(fm, x) for x in legs)


def years(a, fm, legs):
    t = a["t"]
    d = pd.DataFrame([{"год": pd.Timestamp(int(t[x[0]]), unit="s").year, "s": x[4], "r": w2.net(fm, x)} for x in legs])
    g = d.groupby("год")["r"]
    return pd.DataFrame({"сделок": g.size(), "итог": g.sum().round(1), "лонг": d[d["s"] == 1].groupby("год")["r"].sum().round(1), "шорт": d[d["s"] == -1].groupby("год")["r"].sum().round(1)}).T


def flat_flag(a, i):
    return abs(a["f_G"][i] - a["f_Y"][i]) <= 0.75 * a["atr4"][i] and a["x_cross"][i] >= 1


def by_tag(fm, legs):
    rows = {}
    for x in legs:
        k = ("L " if x[4] == 1 else "S ") + x[5].split(",")[0]
        q = rows.setdefault(k, [0, 0.0])
        q[0] += 1
        q[1] += w2.net(fm, x)
    return {k: (v[0], round(v[1])) for k, v in sorted(rows.items())}


def main():
    series = ec.load_all()
    rows = []
    for lab, kw in NEI:
        row = {"вариант": lab}
        for coin, a, fm in series:
            row[coin] = round(total(fm, w2.run(a, **{**w2.MAIN, **kw})))
        rows.append(row)
    nb = pd.DataFrame(rows)
    nb.to_csv(pos.OUT / "portrait_neighbors.csv", index=False)
    print(nb.to_string(index=False), flush=True)
    pers = {"BTC": pos.PER, "ETH": pos.PER, "Bitstamp": wd.PER_BS, "XRP": wd.PER_X}
    summ = []
    for coin, a, fm in series:
        ec.extras(a)
        legs = w2.run(a, **w2.MAIN)
        tr = [x[:5] for x in legs]
        s = lg.summary(a, fm, tr, "основной", coin, pers[coin])
        summ.append(s)
        print(coin, {k: s[k] for k in ("n", "среднее_%", "плюс_%", "сумма_%", "фандинг_%", "издержки_%", "ди_низ_сделки", "просадка_часы_%", "просадка_худшая_%", "дно", "под_водой_дней", "пик_сделок", "блок_низ_%", "блок_верх_%", "блок_≤0_%")}, {p: s[p] for p in pers[coin]}, flush=True)
        print(coin, "по правилам", by_tag(fm, legs), flush=True)
        print(coin, "сдвиги", lg.shift_rank(a, fm, tr), flush=True)
        fl = [x for x in legs if flat_flag(a, x[0])]
        nf = [x for x in legs if not flat_flag(a, x[0])]
        print(coin, "во флете", len(fl), round(total(fm, fl)), "вне флета", len(nf), round(total(fm, nf)), flush=True)
        if coin in ("BTC", "ETH"):
            print(years(a, fm, legs).to_string(), flush=True)
    pd.DataFrame(summ).to_csv(pos.OUT / "portrait_summary.csv", index=False)
    a, fm = series[0][1], series[0][2]
    t = a["t"]
    v1 = wd.run(a)
    legs = w2.run(a, **w2.MAIN)
    for lab, x0, x1 in WIN:
        inw = [q for q in legs if cw.T(x0) <= t[q[0]] < cw.T(x1)]
        old = [q for q in v1 if cw.T(x0) <= t[q[0]] < cw.T(x1)]
        print("\n==", lab, "v1", len(old), round(total(fm, old), 1), "| основной", len(inw), round(total(fm, inw), 1), flush=True)
        print(pd.DataFrame([{"вход": pos.utc_full(t[q[0]])[:-3], "выход": pos.utc_full(t[q[1]])[:-3], "ст": "L" if q[4] == 1 else "S", "тип": q[5], "причина": q[6], "p0": round(q[2]), "p1": round(q[3]), "r": round(w2.net(fm, q), 2)} for q in inw]).to_string(index=False), flush=True)
    print("его действия: старые", int(wd.recall(a, legs)["совпало"].sum()), "из 23; новые", int(w2.recall2(a, legs)["совпало"].sum()), "из 15", flush=True)


if __name__ == "__main__":
    main()
