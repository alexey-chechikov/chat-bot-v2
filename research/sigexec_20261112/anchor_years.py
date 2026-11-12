"""432 и система по годам 2018–2026 на четырёх сдвигах свечи 4ч (00/01/02/03 UTC) и ансамбль окон 432 — Binance spot,
frozen-минутки (как служба). Вопрос: свеча от 00 UTC лучше других стабильно (её видят все — «фокус») или только в
последние годы (удача)? База $1000."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(Path(__file__).parent))
from services.btc_signals import run as rn  # noqa: E402
import ensemble_check as ec  # noqa: E402


def by_year(trades, w=1.0):
    out = {}
    for a, _, r in trades:
        y = datetime.fromtimestamp(a, timezone.utc).year
        out[y] = out.get(y, 0.0) + r * w
    return out


def main():
    R = rn.compute()
    a = R["a"]
    t, o, h, l, c = a["t"], a["o"], a["h"], a["l"], a["c"]
    shifts = [ec.run_one(t, o, h, l, c, shift_h=k) for k in range(4)]
    chans = [ec.run_one(t, o, h, l, c, ch=ch) for ch in (20, 30, 45, 60)]
    years = list(range(2018, 2027))
    for name, idx in (("432", 1), ("система", 0)):
        print(f"\n{name}: итог по годам, $ (свеча от 00 / 01 / 02 / 03 UTC; лучший сдвиг года)")
        ys = [by_year(s[idx]) for s in shifts]
        best = {k: 0 for k in range(4)}
        for y in years:
            v = [ys[k].get(y, 0.0) for k in range(4)]
            b = max(range(4), key=lambda k: v[k])
            best[b] += 1
            print(f"  {y}: " + "  ".join(f"{x:+7.0f}" for x in v) + f"   лучший {b:02d}:00")
        tot = [sum(ys[k].values()) for k in range(4)]
        print(f"  всего: " + "  ".join(f"{x:+7.0f}" for x in tot) + f"; лучший сдвиг по годам: {best}")
    print("\n432 по годам: окно 30 (как сейчас) против ансамбля окон 20/30/45/60 ×1/4, свеча 00 UTC")
    one = by_year(chans[1][1])
    ens = by_year([x for s in chans for x in s[1]], 0.25)
    for y in years:
        print(f"  {y}: {one.get(y, 0):+7.0f}  {ens.get(y, 0):+7.0f}")
    print(f"  всего: {sum(one.values()):+7.0f}  {sum(ens.values()):+7.0f}")


if __name__ == "__main__":
    main()
