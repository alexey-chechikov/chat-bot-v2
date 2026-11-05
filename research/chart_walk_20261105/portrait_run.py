"""Автомат под портрет настоящим прогоном: если сигнал вне описания, позиции нет до следующего сигнала. Сравнение с v1 на четырёх рядах, 2025–26 отдельно, повторение его действий."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import entry_common as ec  # noqa: E402
import ledger as lg  # noqa: E402
import pos  # noqa: E402
import words as wd  # noqa: E402
import words2 as w2  # noqa: E402

pd.set_option("display.width", 280, "display.max_columns", 40, "display.max_rows", 300)
XS = {"xl": True, "sflip": True}
CFG = (("v1", {}), ("xl+sflip", XS), ("портрет", {"gate": "portrait"}), ("полный, xl+sflip", {"gate": "full", **XS}), ("против картины", {"gate": "against"}), ("против картины, xl+sflip", {"gate": "against", **XS}), ("против картины, xl+sflip+sblue", {"gate": "against", "sblue": True, **XS}))


def row_for(coin, a, fm, kw):
    legs = w2.run(a, **kw)
    tr = [x[:5] for x in legs]
    yrs = (a["t"][-1] - a["t"][a["i0"]]) / (365.25 * 86400)
    eq, worst, _, _ = lg.equity(a, fm, tr)
    b = a["i0"]
    dd = lg.drawdown(eq[b:], worst[b:], a["t"][b:])
    p = w2.periods(a, fm, legs)
    return {f"{coin}_n/г": round(len(legs) / yrs), coin: p["итог"], f"{coin}_дд": round(dd[0] / lg.NOTIONAL * 100), f"{coin}_L": p["лонг"], f"{coin}_S": p["шорт"], f"{coin}_до25": p["до_2025"], f"{coin}_25–26": p["2025–26"]}


def main():
    series = ec.load_all()
    rows = []
    for lab, kw in CFG:
        row = {"вариант": lab}
        for coin, a, fm in series:
            row.update(row_for(coin, a, fm, kw))
        a = series[0][1]
        legs = w2.run(a, **kw)
        row["старые_23"] = int(wd.recall(a, legs)["совпало"].sum())
        row["новые_15"] = int(w2.recall2(a, legs)["совпало"].sum())
        rows.append(row)
    t = pd.DataFrame(rows)
    t.to_csv(pos.OUT / "portrait_variants.csv", index=False)
    print(t[["вариант", "BTC", "ETH", "Bitstamp", "XRP", "BTC_дд", "ETH_дд", "Bitstamp_дд", "XRP_дд", "BTC_n/г", "ETH_n/г", "старые_23", "новые_15"]].to_string(index=False), flush=True)
    print(t[["вариант", "BTC_L", "BTC_S", "ETH_L", "ETH_S", "Bitstamp_L", "Bitstamp_S", "XRP_L", "XRP_S"]].to_string(index=False), flush=True)
    print(t[["вариант", "BTC_до25", "BTC_25–26", "ETH_до25", "ETH_25–26", "XRP_до25", "XRP_25–26"]].to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
