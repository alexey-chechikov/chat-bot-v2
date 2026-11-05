"""Прогон записок 4–6 по одной правке и вместе: четыре ряда, до 2025 и 2025–26 отдельно, совпадения с его действиями на старых и новых скринах."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import entry_common as ec  # noqa: E402
import pos  # noqa: E402
import words as wd  # noqa: E402
import words2 as w2  # noqa: E402

pd.set_option("display.width", 260, "display.max_columns", 40, "display.max_rows", 300)
CFG = (("v1", {}), ("xl", {"xl": True}), ("xl+sflip", {"xl": True, "sflip": True}), ("sblue", {"sblue": True}), ("above2", {"above": 2.0}), ("above3", {"above": 3.0}), ("xl+long_red", {"xl": True, "long_red": True}), ("xs_r", {"xs_r": True}),
       ("xl+sflip+sblue", {"xl": True, "sflip": True, "sblue": True}), ("все записки, above2", {"xl": True, "sflip": True, "sblue": True, "above": 2.0, "long_red": True}), ("все записки, above3", {"xl": True, "sflip": True, "sblue": True, "above": 3.0, "long_red": True}))


def main():
    series = ec.load_all()
    for coin, a, _ in series:
        assert [x[:7] for x in wd.run(a)] == [x[:7] for x in w2.run(a)], f"{coin}: v2 с выключенными правками разошлась с v1"
    print("v2 без правок = v1 на всех рядах", flush=True)
    rows = []
    for lab, kw in CFG:
        row = {"вариант": lab}
        for coin, a, fm in series:
            legs = w2.run(a, **kw)
            p = w2.periods(a, fm, legs)
            row[coin] = p["итог"]
            row[f"{coin}_n"] = p["n"]
            row[f"{coin}_до25"] = p["до_2025"]
            row[f"{coin}_25–26"] = p["2025–26"]
            row[f"{coin}_L"] = p["лонг"]
            row[f"{coin}_S"] = p["шорт"]
        a = series[0][1]
        legs = w2.run(a, **kw)
        row["старые_из_23"] = int(wd.recall(a, legs)["совпало"].sum())
        row["новые_из_15"] = int(w2.recall2(a, legs)["совпало"].sum())
        rows.append(row)
    t = pd.DataFrame(rows)
    t.to_csv(pos.OUT / "words2_variants.csv", index=False)
    print(t[["вариант", "BTC", "ETH", "Bitstamp", "XRP", "старые_из_23", "новые_из_15"]].to_string(index=False), flush=True)
    print(t[["вариант", "BTC_n", "ETH_n", "Bitstamp_n", "XRP_n", "BTC_до25", "BTC_25–26", "ETH_до25", "ETH_25–26", "XRP_до25", "XRP_25–26"]].to_string(index=False), flush=True)
    print(t[["вариант", "BTC_L", "BTC_S", "ETH_L", "ETH_S", "Bitstamp_L", "Bitstamp_S", "XRP_L", "XRP_S"]].to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
