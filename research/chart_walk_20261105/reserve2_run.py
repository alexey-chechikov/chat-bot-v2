"""Один прогон второго резерва по PREREG_reserve2_1107.md."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import fetch_coins as fc  # noqa: E402
import plus as pl  # noqa: E402
import portrait_holdout as ph  # noqa: E402

pd.set_option("display.width", 260, "display.max_columns", 40, "display.max_rows", 300)
COINS = ("CRV", "TRB", "RUNE", "SUSHI", "EGLD", "ENJ", "KSM", "RSR", "BEL", "AXS", "ZEN", "GRT", "1INCH", "SAND", "CHZ", "ANKR", "RVN", "SFP", "COTI", "CHR")
OUT = Path(__file__).parent / "out" / "reserve2_1107.csv"


def main():
    assert not OUT.exists(), "второй резерв уже прогонялся"
    rows = []
    for c in COINS:
        sym = c + "USDT"
        fc.klines(sym)
        fc.funding(sym)
        a, f = ph.load(sym)
        lay = pl.layer(a)
        V = {"база R": pl.run(a, rank_th=None, size=False, lay=lay), "К1": pl.run(a, lay=lay), "К3": pl.run(a, sx="Y", lay=lay)}
        for lab, legs in V.items():
            rows.append({"монета": c, "с": pd.Timestamp(int(a["t"][a["i0"]]), unit="s").strftime("%m.%Y"), "вариант": lab, **pl.stats(a, f, legs)})
        print(c, "готово", flush=True)
    d = pd.DataFrame(rows)
    d.to_csv(OUT, index=False)
    print(d.pivot(index="монета", columns="вариант", values="итог").reindex(COINS).to_string(), flush=True)
    base = d[d["вариант"] == "база R"].set_index("монета")
    k1 = d[d["вариант"] == "К1"].set_index("монета")
    res = []
    for lab, g in d.groupby("вариант", sort=False):
        g = g.set_index("монета")
        res.append({"вариант": lab, "итог": round(g["итог"].sum()), "лучше_базы": int((g["итог"] > base["итог"]).sum()), "лучше_К1": int((g["итог"] > k1["итог"]).sum()), "просадка_мед": g["просадка"].median(), "отн_мед": round(g["отн"].median(), 2), "с2025": round(g["с2025"].sum()), "лонг": round(g["лонг"].sum()), "шорт": round(g["шорт"].sum()), "n": int(g["n"].sum())})
    r = pd.DataFrame(res).set_index("вариант")
    print(r.to_string(), flush=True)
    b, c1, c3 = r.loc["база R"], r.loc["К1"], r.loc["К3"]
    t = [c3["итог"] > c1["итог"], c3["лучше_К1"] >= 12, c3["просадка_мед"] >= c1["просадка_мед"] * 1.10, c3["с2025"] >= c1["с2025"]]
    print("К3 условия", t, "ПРОШЁЛ" if all(t) else "НЕ ПРОШЁЛ", "| свежий период", c3["с2025"], flush=True)
    print("К1 против базы", [c1["итог"] > b["итог"], c1["лучше_базы"] >= 12, c1["отн_мед"] > b["отн_мед"], c1["с2025"] > b["с2025"]], "| свежий период", c1["с2025"], flush=True)


if __name__ == "__main__":
    main()
