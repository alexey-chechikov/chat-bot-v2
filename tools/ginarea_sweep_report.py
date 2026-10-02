"""Разбор любой серии развёртки GinArea: итог по месяцам × конфигурациям.

    tools/ginarea_sweep_report.py btc_auto BTCUSDT
    tools/ginarea_sweep_report.py btc_short BTCUSDT
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.ginarea_target_sweep import out_path  # noqa: E402


def main(name: str, sym: str) -> None:
    from services.grid_model import odds_z as oz

    rows = [json.loads(ln) for ln in out_path(name).read_text(encoding="utf-8").splitlines()
            if ln.strip()]
    t = pd.DataFrame(rows)
    t = t[t["current_profit"].notna()]
    t["month"] = t["from"].str[:7]
    t = t[t["month"] >= "2025-10"]
    t["cfg"] = t.apply(lambda r: f"{r['gs']:g}/{r['target']:g}", axis=1)
    t = t.drop_duplicates(["cfg", "month"], keep="last")
    net = t.pivot(index="month", columns="cfg", values="current_profit")
    real = t.pivot(index="month", columns="cfg", values="profit")
    d = oz.load_daily(sym, refresh=False).loc["2025-10-01":"2026-09-30"]
    pk = np.sqrt(np.log(d["high"] / d["low"]) ** 2 / (4 * np.log(2)))
    sig = pk.resample("MS").mean() * 100
    mv = d["close"].resample("MS").last() / d["close"].resample("MS").first() - 1
    sig.index = sig.index.strftime("%Y-%m")
    mv.index = mv.index.strftime("%Y-%m")
    net = net.loc[[m for m in sig.sort_values().index if m in net.index]]
    print(f"[{name}] ИТОГ $ по месяцам (тихие сверху), шаг/цель; лучшая — *")
    print(f"{'месяц':>8} {'размах':>6} {'ход':>5} " + " ".join(f"{c:>8}" for c in net.columns))
    for m, row in net.iterrows():
        best = row.idxmax()
        cells = " ".join((f"{v:>7.0f}*" if c == best else f"{v:>8.0f}") if pd.notna(v)
                         else f"{'·':>8}" for c, v in row.items())
        print(f"{m:>8} {sig[m]:>5.2f}% {mv[m]:>+5.0%} {cells}")
    full = net.dropna(axis=1)
    print(f"{'сумма':>8} {'':>12} " + " ".join(f"{net[c].sum():>8.0f}" for c in net.columns))
    print(f"{'реализ':>8} {'':>12} " + " ".join(f"{real[c].sum():>8.0f}" for c in net.columns))
    print(f"{'худший':>8} {'':>12} " + " ".join(f"{net[c].min():>8.0f}" for c in net.columns))
    print(f"месяцев в плюсе: " + ", ".join(f"{c}: {(net[c] > 0).sum()}/{net[c].notna().sum()}"
                                          for c in net.columns))
    if "worst_bag" in t.columns and t["worst_bag"].notna().any():
        g = t.groupby("cfg")
        print("РИСК ВНУТРИ МЕСЯЦА (по истории теста GinArea):")
        for c, x in g:
            print(f"  {c}: худший мешок {x['worst_bag'].min():,.0f}$, худшая точка итога "
                  f"{x['worst_total'].min():,.0f}$, макс позиция {x['max_pos'].max():.3f}, "
                  f"месяцев {x['worst_bag'].notna().sum()}")
    if not full.empty:
        for half, months in (("окт–мар", full.index[full.index < "2026-04"]),
                             ("апр–сен", full.index[full.index >= "2026-04"])):
            sub = full.loc[months].sum()
            print(f"{half}: лучшая {sub.idxmax()} ({sub.max():,.0f}$); "
                  + ", ".join(f"{c}: {v:,.0f}" for c, v in sub.items()))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "BTCUSDT")
