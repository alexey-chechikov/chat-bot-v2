"""PREREG_trade_table_1109.md: лонг, вошедший далеко от красной, закрывается под жёлтой/зелёной. Запуск: python exit_cond_1109.py"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import btc_lab as bl  # noqa: E402
import flat_1109 as fl  # noqa: E402

OUT = Path(__file__).parent / "out"
pd.set_option("display.width", 220, "display.max_columns", 30)


def main():
    D = pd.read_pickle(OUT / "trade_table_btc.pkl")
    d = D[(D["ряд"] == "Binance") & (D["тип"] == "лонг над синей") & (D["_t0"] < 1672531200)]
    q = {f"q{int(p * 100)}": float(np.quantile(d["от красной, ATR"], p)) for p in (0.6, 0.8)}
    print("пороги расстояния от красной (ATR), лонги 2018–22:", {k: round(v, 2) for k, v in q.items()}, flush=True)
    A = bl.load()
    (a, f, lay), (b, fb, layb) = A
    rows, base = [], None
    for lab, kw in [("база", {})] + [(f"дальше {k} ({v:.2f} ATR) → под {nm}", dict(far_thr=v, far_line=ln)) for k, v in q.items() for ln, nm in (("Y", "жёлтой"), ("G", "зелёной"))]:
        r = fl.row(lab, A, fl.sim(a, lay, **kw), fl.sim(b, layb, **kw))
        if base is None:
            base = r
        else:
            r["прошло"] = "да" if r["2018–22"] > base["2018–22"] and r["2023–26"] > base["2023–26"] and r["Bitstamp"] > base["Bitstamp"] else "нет"
        rows.append(r)
    R = pd.DataFrame(rows)
    print(R.to_string(index=False), flush=True)
    R.to_csv(OUT / "exit_cond_1109.csv", index=False)


if __name__ == "__main__":
    main()
