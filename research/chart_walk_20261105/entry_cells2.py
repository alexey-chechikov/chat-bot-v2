"""Те же клетки внутри каждого правила: какое правило в какой картине зарабатывает. Плюс доля дохода и сделок у простых описаний."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import entry_cells as ce  # noqa: E402
import pos  # noqa: E402

pd.set_option("display.width", 260, "display.max_columns", 40, "display.max_rows", 400)


def simple(d):
    rows = []
    D = {"лонг: над обеими, голубая 4ч растёт": (d["s"] == 1) & (d["голубые"] == "над обеими") & (d["голубая4ч"] == "растёт"),
         "лонг: остальные": (d["s"] == 1) & ~((d["голубые"] == "над обеими") & (d["голубая4ч"] == "растёт")),
         "шорт: цветные смешаны": (d["s"] == -1) & (d["цветные"] == "смешаны"),
         "шорт: цветные выстроены": (d["s"] == -1) & (d["цветные"] != "смешаны"),
         "шорт: смешаны, G у R ≤1 ATR": (d["s"] == -1) & (d["цветные"] == "смешаны") & (d["G_R"].abs() <= 1),
         "шорт: ATR не верхняя треть": (d["s"] == -1) & (d["ATR"] != "ATR верх"),
         "шорт: ATR верхняя треть": (d["s"] == -1) & (d["ATR"] == "ATR верх"),
         "шорт: смешаны и ATR не верхняя": (d["s"] == -1) & (d["цветные"] == "смешаны") & (d["ATR"] != "ATR верх")}
    for k, mask in D.items():
        row = {"описание": k}
        for c in ce.COINS:
            g = d[mask & (d["coin"] == c)]
            row[c] = round(g["r"].sum())
            row[c + "_n"] = len(g)
            row[c + "_ср"] = round(g["r"].mean(), 2)
        for lab, lo, hi in (("BTC_18–21", 2018, 2022), ("BTC_22–24", 2022, 2025), ("BTC_25–26", 2025, 2100)):
            g = d[mask & (d["coin"] == "BTC") & (d["год"] >= lo) & (d["год"] < hi)]
            row[lab] = round(g["r"].sum())
        for lab, lo, hi in (("ETH_18–21", 2018, 2022), ("ETH_22–24", 2022, 2025), ("ETH_25–26", 2025, 2100)):
            g = d[mask & (d["coin"] == "ETH") & (d["год"] >= lo) & (d["год"] < hi)]
            row[lab] = round(g["r"].sum())
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    d = ce.classify(pd.read_csv(pos.OUT / "entry_common_trades.csv"))
    print(ce.table(d, ["тип", "цветные"]).to_string(index=False), flush=True)
    print(ce.table(d, ["тип", "голубая4ч"]).to_string(index=False), flush=True)
    t = simple(d)
    t.to_csv(pos.OUT / "entry_simple.csv", index=False)
    print(t.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
