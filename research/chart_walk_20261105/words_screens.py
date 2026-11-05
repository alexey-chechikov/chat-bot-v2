"""Сделки автомата на трёх скринах оператора (15.02–15.05.2025): какие он назвал, какие лишние, и сколько из шортов над голубыми открыто повторно, без нового пробоя красной."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import gpt_check as gc  # noqa: E402
import ledger as lg  # noqa: E402
import pos  # noqa: E402
import words as wd  # noqa: E402

pd.set_option("display.width", 220, "display.max_columns", 30, "display.max_rows", 200)


def net(fm, x):
    m, f, u = lg.trade_cash(fm, x[:5])
    return (m - f - u) / lg.NOTIONAL * 100


def screens(a, fm, legs):
    t = a["t"]
    named = {(cw.T(ts), act) for ts, act, _ in wd.MARKS}
    rows = []
    for x in legs:
        if not (cw.T("2025-02-15") <= t[x[0]] < cw.T("2025-05-15")):
            continue
        s = "L" if x[4] == 1 else "S"
        hit0 = any(a2 == s and abs(ts - t[x[0]]) <= 8 * 3600 for ts, a2 in named)
        hit1 = any(a2 == "x" + s and abs(ts - t[x[1]]) <= 8 * 3600 for ts, a2 in named)
        rows.append({"вход": pos.utc_full(t[x[0]])[:-3], "выход": pos.utc_full(t[x[1]])[:-3], "сторона": s, "тип": x[5], "причина": x[6], "результат_%": round(net(fm, x), 2), "назвал": "да" if hit0 or hit1 else ""})
    return pd.DataFrame(rows)


def main():
    m, h1, h4, d1, fund = cw.load()
    del m
    a, _ = gc.er.prep(h1, h4, d1, fund)
    wd.add_runs(a)
    fm = lg.funding_marks(a, fund)
    legs = wd.run(a)
    d = screens(a, fm, legs)
    print(d.to_string(index=False))
    print("всего", len(d), "сумма", round(d["результат_%"].sum(), 1), "| назвал", int((d["назвал"] == "да").sum()), round(d.loc[d["назвал"] == "да", "результат_%"].sum(), 1), "| лишние", int((d["назвал"] == "").sum()), round(d.loc[d["назвал"] == "", "результат_%"].sum(), 1))
    print(d.groupby(["сторона", "тип", "назвал"])["результат_%"].agg(["size", "sum"]).round(1).to_string())
    old = wd.run(a, event_short=False)
    sh = [x for x in old if x[4] == -1 and x[5] == "над голубыми"]
    fresh = [x for x in sh if a["f_run_R"][x[0]] == -2]
    rep = [x for x in sh if a["f_run_R"][x[0]] != -2]
    print("старый перевод, шорт над голубыми: всего", len(sh), "| на новом пробое красной", len(fresh), round(sum(net(fm, x) for x in fresh), 1), "| повторно без нового пробоя", len(rep), round(sum(net(fm, x) for x in rep), 1))
    m2, h1e, h4e, d1e, fe = pd.read_pickle(gc.er.ETH_PKL)
    del m2
    h1e, h4e = cw.features(h1e, h4e, 1), cw.features(h4e, h1e, 4)
    e, _ = gc.er.prep(h1e, h4e, d1e, fe)
    wd.add_runs(e)
    bs, fbs = gc.load_bitstamp()
    wd.add_runs(bs)
    xr, fx = gc.load_xrp()
    wd.add_runs(xr)
    for x, f, coin in ((a, fund, "BTC"), (e, fe, "ETH"), (bs, fbs, "Bitstamp"), (xr, fx, "XRP")):
        print(coin, "сдвиги (выход по закрытию часа):", lg.shift_rank(x, lg.funding_marks(x, f), [q[:5] for q in wd.run(x)]), flush=True)


if __name__ == "__main__":
    main()
