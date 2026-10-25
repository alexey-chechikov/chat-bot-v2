"""Дымовая проверка переноса: каждая стратегия на последних ~6000 часах BTC — что-то торгует, сделки разумной длины."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import strategies as S  # noqa: E402

d = pd.read_csv(sys.argv[1], usecols=["ts", "open", "high", "low", "close"]).tail(6000 * 60)
d.index = pd.to_datetime(d["ts"], unit="ms")
for tf, rule in (("1h", "1h"), ("4h", "4h")):
    df = d.resample(rule).agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    b = tuple(df[k].to_numpy() for k in ("open", "high", "low", "close"))
    for name, (fn, tfs) in S.STRATS.items():
        tr = fn(b)
        if not tr:
            print(f"{tf} {name}: 0 сделок")
            continue
        r = np.array([s * (po / pi - 1) for _, _, s, pi, po, _ in tr])
        dur = np.array([k - j for j, k, *_ in tr])
        why = pd.Series([w for *_, w in tr]).value_counts().to_dict()
        print(f"{tf} {name}: {len(tr)} сделок, длит. медиана {np.median(dur):.0f} бар., до издержек {100 * r.mean():+.3f}%, {why}")
