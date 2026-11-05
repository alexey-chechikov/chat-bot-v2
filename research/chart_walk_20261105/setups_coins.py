"""Его новые сетапы на всех рядах: первое закрепление под зелёной (S1, веер ≥1 ATR) и шорт от голубой 4ч (S2), со своими целями и отменами. 20 монет этими сетапами раньше не считались. По положению цены относительно голубых."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import entry_common as ec  # noqa: E402
import fetch_coins as fc  # noqa: E402
import ledger as lg  # noqa: E402
import portrait_holdout as ph  # noqa: E402
import portrait_holdout2 as p2  # noqa: E402
import pos  # noqa: E402
import setups as su  # noqa: E402

pd.set_option("display.width", 260, "display.max_columns", 40, "display.max_rows", 200)


def main():
    rows = []
    known = [(c, a, fm, "просмотрено") for c, a, fm in ec.load_all()]
    fresh = []
    for c in fc.COINS + p2.COINS2:
        a, fm = ph.load(c + "USDT")
        fresh.append((c, a, fm, "новые"))
    for coin, a, fm, grp in known + fresh:
        tr = su.to_frame(a, fm, coin, "S1", -1, su.one_at_a_time(su.s1_events(a, 1.0), lambda i: su.manage_s1(a, i)))
        tr += su.to_frame(a, fm, coin, "S2", -1, su.one_at_a_time(su.s2_events(a), lambda i: su.manage_s2(a, i)))
        for x in tr:
            x["группа"] = grp
        rows += tr
        print(coin, len(tr), flush=True)
    d = pd.DataFrame(rows)
    d.to_csv(pos.OUT / "setups_coins.csv", index=False)
    d["под_голубой4ч"] = d["где"] != "над обеими"
    t = d.groupby(["группа", "сетап", "где"])["r"].agg(["size", "sum", "mean"]).round(2)
    print(t.to_string(), flush=True)
    t = d.groupby(["группа", "сетап", "причина"])["r"].agg(["size", "sum", "mean"]).round(2)
    print(t.to_string(), flush=True)
    s1 = d[(d["сетап"] == "S1") & (d["где"] != "над обеими")]
    c = s1.groupby(["группа", "coin"])["r"].sum().round()
    print("S1 под голубой 4ч, по монетам:", c.to_dict(), flush=True)
    for g, x in s1.groupby("группа"):
        by = x.groupby("coin")["r"].sum()
        print(g, "S1 под голубой 4ч: сделок", len(x), "сумма", round(x["r"].sum()), "среднее", round(x["r"].mean(), 2), "плюс на монетах", int((by > 0).sum()), "из", len(by), flush=True)
    for g, x in d[(d["сетап"] == "S1") & (d["где"] == "над обеими")].groupby("группа"):
        by = x.groupby("coin")["r"].sum()
        print(g, "S1 над обеими: сделок", len(x), "сумма", round(x["r"].sum()), "среднее", round(x["r"].mean(), 2), "плюс на монетах", int((by > 0).sum()), "из", len(by), flush=True)
    for g, x in d[d["сетап"] == "S2"].groupby("группа"):
        by = x.groupby("coin")["r"].sum()
        print(g, "S2 всё: сделок", len(x), "сумма", round(x["r"].sum()), "среднее", round(x["r"].mean(), 2), "плюс на монетах", int((by > 0).sum()), "из", len(by), flush=True)
    b = d[d["coin"].isin(["BTC", "ETH"]) & (d["год"] >= 2025)].groupby(["coin", "сетап", "где"])["r"].agg(["size", "sum"]).round(1)
    print(b.to_string(), flush=True)
    btc = [q for q in known if q[0] == "BTC"][0]
    a, fm = btc[1], btc[2]
    x = d[(d["coin"] == "BTC") & (d["сетап"] == "S2")]
    print("BTC S2 сдвиги:", lg.shift_rank(a, fm, [(int(q.i0), int(q.i1), q.p0, q.p1, int(q.s)) for q in x.itertuples()]), flush=True)
    x = d[(d["coin"] == "BTC") & (d["сетап"] == "S1") & (d["где"] != "над обеими")]
    print("BTC S1 под голубой сдвиги:", lg.shift_rank(a, fm, [(int(q.i0), int(q.i1), q.p0, q.p1, int(q.s)) for q in x.itertuples()]), flush=True)


if __name__ == "__main__":
    main()
