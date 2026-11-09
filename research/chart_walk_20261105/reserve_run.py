"""Один прогон резерва по PREREG_reserve_1107.md. Запускать только после совпадения plus.py с таблицей Вина."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import fetch_coins as fc  # noqa: E402
import plus as pl  # noqa: E402
import portrait_holdout as ph  # noqa: E402
import words2 as w2  # noqa: E402
import words3 as w3  # noqa: E402

pd.set_option("display.width", 260, "display.max_columns", 40, "display.max_rows", 300)
COINS = ("XMR", "DASH", "ZEC", "ONT", "IOTA", "BAT", "NEO", "QTUM", "IOST", "THETA", "ZIL", "KNC", "ZRX", "COMP", "KAVA", "BAND", "RLC", "SNX", "SKL", "YFI")
OUT = Path(__file__).parent / "out" / "reserve_1107.csv"


def main():
    assert not OUT.exists(), "резерв уже прогонялся"
    rows = []
    for c in COINS:
        sym = c + "USDT"
        fc.klines(sym)
        fc.funding(sym)
        a, f = ph.load(sym)
        lay = pl.layer(a)
        V = {"база R": pl.run(a, rank_th=None, size=False, lay=lay), "К1": pl.run(a, lay=lay), "К2": pl.run(a, counter=True, lay=lay), "разведка": pl.run(a, counter=True, sx="Y", lay=lay), "A+2/6": w2.run(a, **w2.MAIN26), "G": w3.run(a, l_align=False, s_align=False)}
        for lab, legs in V.items():
            rows.append({"монета": c, "с": pd.Timestamp(int(a["t"][a["i0"]]), unit="s").strftime("%m.%Y"), "вариант": lab, **pl.stats(a, f, legs)})
        print(c, "готово", flush=True)
    d = pd.DataFrame(rows)
    d.to_csv(OUT, index=False)
    piv = d.pivot(index="монета", columns="вариант", values="итог").reindex(COINS)
    print(piv.to_string(), flush=True)
    res = []
    base = d[d["вариант"] == "база R"].set_index("монета")
    k1 = d[d["вариант"] == "К1"].set_index("монета")
    for lab, g in d.groupby("вариант", sort=False):
        g = g.set_index("монета")
        res.append({"вариант": lab, "итог": round(g["итог"].sum()), "лучше_базы": int((g["итог"] > base["итог"]).sum()), "лучше_К1": int((g["итог"] > k1["итог"]).sum()), "просадка_мед": g["просадка"].median(), "отн_мед": round(g["отн"].median(), 2), "с2025": round(g["с2025"].sum()), "лонг": round(g["лонг"].sum()), "шорт": round(g["шорт"].sum()), "вес": round(g["вес"].mean(), 2), "n": int(g["n"].sum())})
    r = pd.DataFrame(res).set_index("вариант")
    print(r.to_string(), flush=True)
    b, c1, c2 = r.loc["база R"], r.loc["К1"], r.loc["К2"]
    t1 = [c1["итог"] > b["итог"], c1["лучше_базы"] >= 12, c1["отн_мед"] > b["отн_мед"], c1["с2025"] > b["с2025"]]
    t2 = [c2["итог"] > c1["итог"], c2["лучше_К1"] >= 12, c2["просадка_мед"] >= c1["просадка_мед"] * 1.10]
    print("К1 условия", t1, "ПРОШЁЛ" if all(t1) else "НЕ ПРОШЁЛ", "| свежий период", c1["с2025"], flush=True)
    print("К2 условия", t2, "ПРОШЁЛ" if all(t2) else "НЕ ПРОШЁЛ", "| свежий период", c2["с2025"], flush=True)


if __name__ == "__main__":
    main()
