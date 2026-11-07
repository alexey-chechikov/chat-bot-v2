"""Полный поток с пересчётом следующих входов: выход X01 на всех лонгах и стоп/тейк шорта в ATR. Все ряды уже просмотрены, это замер, а не проверка."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import entry_common as ec  # noqa: E402
import fetch_coins as fc  # noqa: E402
import ledger as lg  # noqa: E402
import portrait_holdout as ph  # noqa: E402
import portrait_holdout2 as p2  # noqa: E402
import pos  # noqa: E402
import words as wd  # noqa: E402
import words2 as w2  # noqa: E402

pd.set_option("display.width", 260, "display.max_columns", 30, "display.max_rows", 300)
A = {"gate": "shorts"}
NOTES = {"xl": True, "sflip": True, "sblue": True}
CFG = {"A": A, "A+xl": {**A, "xl": True}, "A+X01 все": {**A, "xl": True, "x01_all": "add"}, "A+X01 вместо": {**A, "xl": True, "x01_all": "only"},
       "A+ATR 2/6": {**A, "s_stop": 2.0, "s_tp": 6.0}, "A+ATR 2/6 событие": {**A, "s_stop": 2.0, "s_tp": 6.0, "s_after": "covered"},
       "A+X01 все+ATR": {**A, "xl": True, "x01_all": "add", "s_stop": 2.0, "s_tp": 6.0, "s_after": "covered"},
       "заметки": NOTES, "заметки+ATR 2/6": {**NOTES, "s_stop": 2.0, "s_tp": 6.0}}


def row(coin, grp, a, fm, lab, legs):
    r = np.array([w2.net(fm, x) for x in legs])
    s = np.array([x[4] for x in legs])
    t0 = a["t"][np.array([x[0] for x in legs])]
    eq, worst, _, _ = lg.equity(a, fm, [x[:5] for x in legs])
    b = a["i0"]
    return {"ряд": coin, "группа": grp, "вариант": lab, "n": len(r), "итог": round(float(r.sum()), 1), "лонг": round(float(r[s == 1].sum()), 1), "шорт": round(float(r[s == -1].sum()), 1), "с2025": round(float(r[t0 >= ph.CUT].sum()), 1), "просадка": round(lg.drawdown(eq[b:], worst[b:], a["t"][b:])[0] / lg.NOTIONAL * 100, 1)}


def one(coin, grp, a, fm):
    v1 = wd.run(a)
    off = w2.run(a)
    assert [x[:5] for x in v1] == [x[:5] for x in off], "выключатели выключены — обязан быть words.run"
    rows = [row(coin, grp, a, fm, "v1", v1)]
    for lab, kw in CFG.items():
        rows.append(row(coin, grp, a, fm, lab, w2.run(a, **kw)))
    return rows


def main():
    rows = []
    for k, a, f in ec.load_all():
        rows += one(k, "основные", a, f)
        print(k, "готово", flush=True)
    for c in fc.COINS + p2.COINS2:
        a, f = ph.load(c + "USDT")
        rows += one(c, "монеты", a, f)
    d = pd.DataFrame(rows)
    d.to_csv(pos.OUT / "gpt_r3_flow.csv", index=False)
    print(d[d["группа"] == "основные"].drop(columns="группа").to_string(index=False), flush=True)
    m = d[d["группа"] == "монеты"]
    base = m[m["вариант"] == "A"].set_index("ряд")["итог"]
    rows2 = []
    for lab, g in m.groupby("вариант", sort=False):
        rows2.append({"вариант": lab, "n": g["n"].sum(), "итог": round(g["итог"].sum()), "лонг": round(g["лонг"].sum()), "шорт": round(g["шорт"].sum()), "с2025": round(g["с2025"].sum()), "просадка_медиана": g["просадка"].median(), "лучше_A_монет": int((g.set_index("ряд")["итог"] > base).sum())})
    print(pd.DataFrame(rows2).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
