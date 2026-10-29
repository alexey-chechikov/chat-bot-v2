"""Как именно расходятся тейкеры и стакан: глубокая выгрузка против первой закрытой записи журнала (BTC/ETH) —
отношение, корреляция, совпадение знака, и меняются ли значения бара между записями журнала."""
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
for sym in ("BTCUSDT", "ETHUSDT"):
    deep = pd.read_csv(ROOT / "research/coinglass_compare/data" / f"{sym}_1h.csv")
    deep.index = pd.to_datetime(deep.pop("bar_utc"), utc=True)
    recs = defaultdict(list)
    for line in open(ROOT / "state/coinglass/tv" / f"{sym}_1h.jsonl", encoding="utf-8"):
        r = json.loads(line)
        if r.get("closed"):
            recs[r["bar"]].append(r)
    print(f"\n{sym}")
    for c in ("bid_ask_delta", "taker_delta", "taker_buy"):
        a, b, firsts = [], [], []
        changes = 0
        for bar, rs in recs.items():
            t = pd.Timestamp(bar)
            if t not in deep.index or rs[0].get(c) is None or pd.isna(deep.at[t, c]):
                continue
            a.append(rs[0][c])
            b.append(deep.at[t, c])
            vals = {round(x[c], 6) for x in rs if x.get(c) is not None}
            changes += len(vals) > 1
        a, b = np.array(a), np.array(b)
        ratio = np.median(b / a) if len(a) else float("nan")
        print(f"  {c}: баров {len(a)}, корреляция {np.corrcoef(a, b)[0, 1]:.3f}, медиана отношения выгрузка/журнал "
              f"{ratio:.3f}, знак совпал {np.mean(np.sign(a) == np.sign(b)):.2f}, бары с разными значениями внутри "
              f"журнала {changes}")
    last = sorted(recs)[-30:-25]
    for bar in last:
        rs = recs[bar]
        print("   ", bar[:16], "журнал:", [(x["obs"][5:16], round(x["bid_ask_delta"] or 0), round(x["taker_delta"] or 0))
                                         for x in rs][:4],
              "выгрузка:", round(deep.at[pd.Timestamp(bar), "bid_ask_delta"]), round(deep.at[pd.Timestamp(bar), "taker_delta"]))
