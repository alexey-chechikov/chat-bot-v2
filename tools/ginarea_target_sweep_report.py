"""Разбор развёртки цели ETH Auto по месяцам (движок GinArea).

Решение названо заранее (01.10.2026, до результатов):
- в каждом из трёх тихих месяцев (QUIET) и трёх бурных (STORMY) находим
  лучшую цель; эффект есть, только если ВСЕ три тихих выбирают цель ниже,
  чем ВСЕ три бурных (или наоборот) — иначе «нет»;
- дополнительно: связь размаха месяца с лучшей целью по всем 12 месяцам
  и устойчивость по половинам года (ворота №2);
- соседние цели должны вести себя согласованно (ворота №4).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.ginarea_target_sweep import OUT, QUIET, STORMY  # noqa: E402


def load() -> pd.DataFrame:
    rows = [json.loads(ln) for ln in OUT.read_text(encoding="utf-8").splitlines() if ln.strip()]
    t = pd.DataFrame(rows)
    t = t[t["current_profit"].notna()]
    t["month"] = t["from"].str[:7]
    t = t[t["month"] >= "2025-10"]
    return t.drop_duplicates(["target", "month"], keep="last")


def month_sigma() -> pd.Series:
    from services.grid_model import odds_z as oz
    d = oz.load_daily("ETHUSDT", refresh=False).loc["2025-10-01":"2026-09-30"]
    pk = np.sqrt(np.log(d["high"] / d["low"]) ** 2 / (4 * np.log(2)))
    s = pk.resample("MS").mean()
    s.index = s.index.strftime("%Y-%m")
    return s * 100


def main() -> None:
    t = load()
    net = t.pivot(index="month", columns="target", values="current_profit")
    real = t.pivot(index="month", columns="target", values="profit")
    sig = month_sigma().reindex(net.index)
    net = net.loc[sig.sort_values().index]
    print("ИТОГ $ по месяцам (тихие сверху), лучшая цель — *")
    print(f"{'месяц':>8} {'размах':>7} " + " ".join(f"{c:>7}" for c in net.columns))
    for m, row in net.iterrows():
        best = row.idxmax()
        cells = " ".join((f"{v:>6.0f}*" if c == best else f"{v:>7.0f}")
                         for c, v in row.items())
        tag = " тихий" if m in QUIET else " бурный" if m in STORMY else ""
        print(f"{m:>8} {sig[m]:>6.2f}% {cells}{tag}")
    print(f"{'сумма':>8} {'':>7} " + " ".join(f"{v:>7.0f}" for v in net.sum()))
    print(f"{'реализ':>8} {'':>7} " + " ".join(f"{v:>7.0f}" for v in real.sum()))

    best = net.idxmax(axis=1)
    q = [best[m] for m in QUIET if m in best]
    s = [best[m] for m in STORMY if m in best]
    print(f"\nЗАРАНЕЕ НАЗВАННАЯ ПАРА: лучшая цель в тихих {q}, в бурных {s}")
    if len(q) == 3 and len(s) == 3:
        if max(q) < min(s):
            print("→ ДА: в тихих месяцах все лучшие цели НИЖЕ, чем в бурных")
        elif min(q) > max(s):
            print("→ ДА (обратная): в тихих месяцах все лучшие цели ВЫШЕ, чем в бурных")
        else:
            print("→ НЕТ: тихие и бурные месяцы не разделяются по лучшей цели")
    rho = pd.Series(best.astype(float).values).corr(pd.Series(sig[best.index].values),
                                                   method="spearman")
    print(f"связь размаха и лучшей цели по {len(best)} месяцам (Спирмен): {rho:+.2f}")
    for half, months in (("1-я половина", net.index[net.index < "2026-04"]),
                         ("2-я половина", net.index[net.index >= "2026-04"])):
        sub = net.loc[months]
        print(f"{half}: сумма по целям " + ", ".join(
            f"{c}: {v:,.0f}" for c, v in sub.sum().items()) +
            f" → лучшая {sub.sum().idxmax()}")
    # ворота №4: насколько лучшая цель отрывается от соседей
    gap = (net.max(axis=1) - net.apply(lambda r: r.drop(r.idxmax()).max(), axis=1))
    print(f"отрыв лучшей цели от второй: медиана {gap.median():.0f}$, "
          f"месяцев с отрывом <10% итога: "
          f"{int((gap < 0.1 * net.max(axis=1).abs()).sum())} из {len(gap)}")


if __name__ == "__main__":
    main()
