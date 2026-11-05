"""PREREG_portrait.md: один прогон на 10 новых монетах. Настройки не меняются."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import fetch_coins as fc  # noqa: E402
import gpt_check as gc  # noqa: E402
import ledger as lg  # noqa: E402
import pos  # noqa: E402
import words as wd  # noqa: E402
import words2 as w2  # noqa: E402

pd.set_option("display.width", 260, "display.max_columns", 40, "display.max_rows", 100)
CUT = cw.T("2025-01-01")
FIRST = {"gate": "against", "xl": True, "sflip": True, "sblue": True}  # основной вариант первой проверки, она его не пропустила


def load(sym):
    f = pd.read_csv(fc.DIR / f"{sym}_1h.csv")
    f["ts"] = (f["ms"] // 1000).astype(np.int64)
    r = pd.read_csv(fc.DIR / f"{sym}_funding.csv")
    fund = pd.Series(r["rate"].to_numpy(float), index=(r["ms"].to_numpy(np.int64) // 1000))
    start = int(f["ts"].iloc[0]) + 180 * 86400
    a = gc.from_hourly(f, fund, pd.Timestamp(start, unit="s").strftime("%Y-%m-%d"))
    wd.add_runs(a)
    return a, lg.funding_marks(a, fund)


def stats(a, fm, legs):
    r = np.array([w2.net(fm, x) for x in legs])
    s = np.array([x[4] for x in legs])
    t0 = a["t"][np.array([x[0] for x in legs])]
    eq, worst, _, _ = lg.equity(a, fm, [x[:5] for x in legs])
    b = a["i0"]
    dd = lg.drawdown(eq[b:], worst[b:], a["t"][b:])
    return {"n": len(r), "итог": round(float(r.sum())), "лонг": round(float(r[s == 1].sum())), "шорт": round(float(r[s == -1].sum())), "с_2025": round(float(r[t0 >= CUT].sum())), "просадка": round(dd[0] / lg.NOTIONAL * 100)}


def main():
    rows = []
    for c in fc.COINS:
        sym = c + "USDT"
        a, fm = load(sym)
        v1 = wd.run(a)
        main_ = w2.run(a, **FIRST)
        port = w2.run(a, gate="portrait")
        blocked = [x for x in v1 if not w2.allow(a, x[0], x[4], x[5], "against")]
        row = {"монета": c, "с": pd.Timestamp(int(a["t"][a["i0"]]), unit="s").strftime("%m.%Y"), "сумма_против": round(sum(w2.net(fm, x) for x in blocked)), "n_против": len(blocked)}
        for lab, legs in (("v1", v1), ("осн", main_), ("порт", port)):
            for k, v in stats(a, fm, legs).items():
                row[f"{lab}_{k}"] = v
        s = lg.shift_rank(a, fm, [x[:5] for x in main_])
        row["осн_лучше_случайного_%"] = s["всё"]["лучше_%"]
        s1 = lg.shift_rank(a, fm, [x[:5] for x in v1])
        row["v1_лучше_случайного_%"] = s1["всё"]["лучше_%"]
        rows.append(row)
        print(row, flush=True)
    d = pd.DataFrame(rows)
    d.to_csv(pos.OUT / "portrait_holdout.csv", index=False)
    print(d[["монета", "с", "v1_итог", "осн_итог", "порт_итог", "v1_просадка", "осн_просадка", "порт_просадка", "v1_n", "осн_n", "порт_n", "v1_лучше_случайного_%", "осн_лучше_случайного_%"]].to_string(index=False), flush=True)
    print(d[["монета", "v1_лонг", "осн_лонг", "порт_лонг", "v1_шорт", "осн_шорт", "порт_шорт", "v1_с_2025", "осн_с_2025", "порт_с_2025", "сумма_против", "n_против"]].to_string(index=False), flush=True)
    print("\nКРИТЕРИИ", flush=True)
    print("1 сумма: v1", d["v1_итог"].sum(), "осн", d["осн_итог"].sum(), d["осн_итог"].sum() > d["v1_итог"].sum(), flush=True)
    print("2 лучше v1 на монетах:", int((d["осн_итог"] > d["v1_итог"]).sum()), "из 10", flush=True)
    print("3 шорты осн:", d["осн_шорт"].sum(), "(v1", d["v1_шорт"].sum(), ")", flush=True)
    print("4 сделки против картины в минусе на монетах:", int((d["сумма_против"] < 0).sum()), "из 10; сумма", d["сумма_против"].sum(), flush=True)
    print("5 сделок осн / v1:", round(d["осн_n"].sum() / d["v1_n"].sum() * 100), "%", flush=True)
    print("6 с 2025: v1", d["v1_с_2025"].sum(), "осн", d["осн_с_2025"].sum(), "порт", d["порт_с_2025"].sum(), flush=True)
    print("просадка, медиана: v1", d["v1_просадка"].median(), "осн", d["осн_просадка"].median(), "порт", d["порт_просадка"].median(), flush=True)


if __name__ == "__main__":
    main()
