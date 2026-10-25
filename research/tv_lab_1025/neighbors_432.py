"""Strategy 432 — соседи настроек (ворота 4 CLAUDE.md), 25.10. Правило до прогона: 27 ячеек Donchian 20/30/40 × ADX
18/22/26 × удержание 15/20/30 баров (пробой ≥0.5 ATR — как у автора) + пробой 0.3/0.7 в центре; плоская поверхность —
≥ 2/3 ячеек обгоняют медиану случайного входа выше EMA200 на BTC И на ETH. Данные — как validate_432 (2017–2026, 4h)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import run as R  # noqa: E402
import strategies as S  # noqa: E402
from validate_432 import control  # noqa: E402


def s432p(b, dc=30, adx_min=22.0, hold=20, mag_min=0.5):
    o, h, l, c = b
    hi = pd.Series(h).shift(1).rolling(dc).max().to_numpy()
    lo = pd.Series(l).shift(1).rolling(dc).min().to_numpy()
    a = S.atr(h, l, c, 14)
    e200 = S.ema(c, 200)
    _, _, adx = S.dmi(h, l, c, 14, 14)
    mag = np.where((c > hi) & (a > 0), (c - hi) / a, 0.0)
    ent = (c > hi) & (adx >= adx_min) & (c > e200) & (mag >= mag_min)
    ent[:300] = False
    out, pos = [], None
    for i in range(len(c) - 1):
        if pos is not None:
            j, si, px = pos
            if c[i] < lo[i] or i - si >= hold:
                out.append((j, i + 1, 1, px, o[i + 1], "сигнал"))
                pos = None
                continue
        if pos is None and ent[i]:
            pos = (i + 1, i, o[i + 1])
    return out


def main():
    for sym, path in (("BTCUSDT", sys.argv[1]), ("ETHUSDT", sys.argv[2])):
        df = R.bars(path)["4h"]
        fund = R.funding(sym)
        b = tuple(df[k].to_numpy() for k in ("open", "high", "low", "close"))
        cells = [(dc, ax, hd, 0.5) for dc in (20, 30, 40) for ax in (18.0, 22.0, 26.0) for hd in (15, 20, 30)]
        cells += [(30, 22.0, 20, 0.3), (30, 22.0, 20, 0.7)]
        res = []
        for dc, ax, hd, mg in cells:
            tr = R.evaluate(df, s432p(b, dc, ax, hd, mg), fund)
            ctl = control(df, tr, fund, reps=300)
            m = tr["net"].mean()
            res.append((dc, ax, hd, mg, len(tr), m, float(np.median(ctl)), (1 + int((ctl >= m).sum())) / 301))
        beat = sum(1 for x in res if x[5] > x[6])
        sig = sum(1 for x in res if x[7] <= 0.05)
        print(f"== {sym}: ячеек {len(res)}, выше медианы случайного {beat}, ранг ≤0.05 {sig}; net от "
              f"{100 * min(x[5] for x in res):+.2f}% до {100 * max(x[5] for x in res):+.2f}%", flush=True)
        for x in res:
            print(f"   DC {x[0]} ADX {x[1]:.0f} удерж. {x[2]} пробой {x[3]}: n {x[4]} net {100 * x[5]:+.2f}% "
                  f"случ. {100 * x[6]:+.2f}% ранг {x[7]:.3f}")


if __name__ == "__main__":
    main()
