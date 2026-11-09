"""Совместная кривая системы на всех монетах топа (без отбора): $1000 на вход × вес на каждой монете, сумма кривых по часам."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import plus as pl  # noqa: E402
import top_fetch as tf  # noqa: E402
import top_run as tr  # noqa: E402


def dd(x):
    x = np.asarray(x, float)
    return float((x - np.maximum.accumulate(np.r_[0.0, x])[1:]).min())


def main():
    cur = {}
    for c in tf.TOP:
        a, f = tr.load(c + "USDT")
        eq = pl.curve(a, f, tr.system(a))
        b = a["i0"]
        cur[c] = pd.Series(eq[b:] - eq[b], index=pd.to_datetime(a["t"][b:], unit="s"))
    d = pd.DataFrame(cur).resample("1D").last().ffill().fillna(0.0)
    alts = d.drop(columns="BTC")
    for lab, x in (("все 24", d.sum(1)), ("23 без BTC", alts.sum(1)), ("BTC фьючерс", d["BTC"])):
        y = x[x.index >= "2025-01-01"] - x[x.index < "2025-01-01"].iloc[-1]
        yrs = x.resample("YE").last().diff().fillna(x.resample("YE").last())
        print(f"{lab}: итог {x.iloc[-1]:+.0f}, просадка {dd(x):.0f}, отношение {x.iloc[-1] / abs(dd(x)):.2f} | с 2025 {y.iloc[-1]:+.0f}, просадка {dd(y):.0f} | годы",
              {int(k.year): int(v) for k, v in yrs.items()}, flush=True)
    r = d.diff().dropna()
    cor = r.drop(columns="BTC").corrwith(r["BTC"])
    print("связь дневных изменений кривой монеты с кривой BTC, медиана", round(float(cor.median()), 2), "мин", round(float(cor.min()), 2), "макс", round(float(cor.max()), 2), flush=True)
    worst = d.sum(1).diff().nsmallest(5)
    print("худшие дни портфеля:", {k.strftime("%Y-%m-%d"): round(float(v)) for k, v in worst.items()}, flush=True)


if __name__ == "__main__":
    main()
