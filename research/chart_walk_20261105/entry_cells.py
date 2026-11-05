"""Портрет входа в его словах: где цена относительно голубых, как стоят цветные, куда идёт голубая 4ч, сколько до ближайшей линии против сделки. Суммы итога по клеткам на четырёх рядах. Ни одна сделка не выбрасывается."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import entry_common as ec  # noqa: E402
import pos  # noqa: E402

pd.set_option("display.width", 260, "display.max_columns", 40, "display.max_rows", 400)
COINS = ("BTC", "ETH", "Bitstamp", "XRP")


def classify(d):
    d = d.copy()
    d["голубые"] = np.select([(d["от_B4"] > 0) & (d["от_B1"] > 0), (d["от_B4"] < 0) & (d["от_B1"] < 0)], ["над обеими", "под обеими"], "между")
    d["цветные"] = np.select([(d["G_Y"] > 0) & (d["Y_R"] > 0), (d["G_Y"] < 0) & (d["Y_R"] < 0)], ["вверх G>Y>R", "вниз G<Y<R"], "смешаны")
    d["голубая4ч"] = np.where(d["накл_B4"] > 0, "растёт", "падает")
    d["G_к_R"] = pd.cut(d["G_R"].abs(), [-1, 1, 3, 1000], labels=["G у R ≤1", "G от R 1–3", "G от R >3"])
    d["ATR"] = d.groupby("coin")["atr_pct"].transform(lambda x: pd.qcut(x, 3, labels=["ATR низ", "ATR сред", "ATR верх"]))
    return d


def table(d, by):
    rows = []
    for side, nm in ((1, "лонг"), (-1, "шорт")):
        ds = d[d["s"] == side]
        for key, g in ds.groupby(by, observed=True):
            row = {"сторона": nm, "клетка": " · ".join(key) if isinstance(key, tuple) else str(key)}
            ok = 0
            for c in COINS:
                x = g[g["coin"] == c]
                row[c] = round(x["r"].sum())
                row[c + "_n"] = len(x)
                ok += x["r"].sum() > 0
            row["плюс_рядов"] = int(ok)
            b = g[g["coin"] == "BTC"]
            e = g[g["coin"] == "ETH"]
            row["BTC_25–26"] = round(b.loc[b["год"] >= 2025, "r"].sum())
            row["ETH_25–26"] = round(e.loc[e["год"] >= 2025, "r"].sum())
            rows.append(row)
    return pd.DataFrame(rows)


def main():
    d = pd.read_csv(pos.OUT / "entry_common_trades.csv")
    d = classify(d)
    for by in (["голубые"], ["цветные"], ["голубая4ч"], ["ATR"], ["голубые", "цветные"], ["голубые", "голубая4ч"], ["цветные", "голубая4ч"], ["цветные", "G_к_R"]):
        t = table(d, by)
        print("\n==", by, flush=True)
        print(t.to_string(index=False), flush=True)
    full = table(d, ["голубые", "цветные", "голубая4ч"])
    full.to_csv(pos.OUT / "entry_cells.csv", index=False)
    print(full.sort_values(["сторона", "плюс_рядов"], ascending=[True, False]).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
