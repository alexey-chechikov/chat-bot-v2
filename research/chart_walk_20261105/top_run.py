"""PREREG_top_breadth_1108.md, часть 1: система BTC без изменений на топе монет (фьючерсы Binance, с фандингом)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import btc_lab as bl  # noqa: E402
import btc_next as bn  # noqa: E402
import gpt_check as gc  # noqa: E402
import ledger as lg  # noqa: E402
import plus as pl  # noqa: E402
import state_card as sc  # noqa: E402
import top_fetch as tf  # noqa: E402
import words as wd  # noqa: E402

pd.set_option("display.width", 260, "display.max_columns", 40, "display.max_rows", 100)
OUT = Path(__file__).parent / "out" / "top_1108.csv"


def load(sym):
    f = pd.read_csv(tf.DIR / f"{sym}_1h.csv")
    f["ts"] = (f["ms"] // 1000).astype(np.int64)
    r = pd.read_csv(tf.DIR / f"{sym}_funding.csv")
    fund = pd.Series(r["rate"].to_numpy(float), index=(r["ms"].to_numpy(np.int64) // 1000))
    start = int(f["ts"].iloc[0]) + 180 * 86400
    a = gc.from_hourly(f[["ts", "open", "high", "low", "close", "volume"]], fund, pd.Timestamp(start, unit="s").strftime("%Y-%m-%d"))
    wd.add_runs(a)
    return a, lg.funding_marks(a, fund)


def system(a):
    lay = pl.layer(a)
    return bn.pyramid(a, bl.run(a, lay, rules={"cs": 1.0}), 2, 2, 0.5, 0.5)


def row(lab, a, f, legs):
    st = pl.stats(a, f, legs)
    r, w = pl.unit(f, legs)
    v = r * w
    t0 = a["t"][np.array([x[0] for x in legs])]
    mid = (a["t"][a["i0"]] + a["t"][-1]) / 2
    sh = lg.shift_rank(a, f, [x[:5] for x in legs])["всё"]
    h1, h2 = float(v[t0 < mid].sum()), float(v[t0 >= mid].sum())
    works = h1 > 0 and h2 > 0 and sh["лучше_%"] >= 90
    return {"монета": lab, "с": pd.Timestamp(int(a["t"][a["i0"]]), unit="s").strftime("%m.%Y"), "сделок": st["n"], "итог": st["итог"], "просадка": st["просадка"], "отн": st["отн"],
            "половина1": round(h1, 1), "половина2": round(h2, 1), "с2025": st["с2025"], "лонг": st["лонг"], "шорт": st["шорт"], "лучше_сдвигов_%": sh["лучше_%"], "работает": "да" if works else "нет"}


def main():
    rows = []
    a, f, _ = sc.load_coin("BTC")
    rows.append(row("BTC спот (судья)", a, f, system(a)))
    print(rows[-1], flush=True)
    miss = []
    for c in tf.TOP:
        sym = c + "USDT"
        if not (tf.DIR / f"{sym}_1h.csv").exists() or not (tf.DIR / f"{sym}_funding.csv").exists():
            miss.append(c)
            continue
        a, f = load(sym)
        if a["i0"] >= len(a["t"]) - 24 * 200:
            miss.append(c + " (меньше 200 дней учёта)")
            continue
        rows.append(row(c, a, f, system(a)))
        print(rows[-1], flush=True)
    d = pd.DataFrame(rows)
    d.to_csv(OUT, index=False)
    print(d.to_string(index=False), flush=True)
    alt = d[~d["монета"].str.startswith("BTC")]
    print("без BTC: монет", len(alt), "итог", round(alt["итог"].sum()), "в плюсе", int((alt["итог"] > 0).sum()), "обе половины в плюсе", int(((alt["половина1"] > 0) & (alt["половина2"] > 0)).sum()),
          "с 2025 в плюсе", int((alt["с2025"] > 0).sum()), "с 2025 сумма", round(alt["с2025"].sum()), "работает", int((alt["работает"] == "да").sum()), "медиана отн", round(alt["отн"].median(), 2), flush=True)
    print("пропущены:", miss, flush=True)


if __name__ == "__main__":
    main()
