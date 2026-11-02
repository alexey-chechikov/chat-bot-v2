"""Сверка ядра gridk.c с research/weex/regime_grid.run (питон, та же механика, что прошлые прогоны режима):
окно 01.01–15.03.2025, ордер 0.0012 BTC, потолок $6 000, 50 лотов, фандинг Binance, мейкер/тейкер/проскальзывание
живые. Режимы: всегда лонг, всегда шорт, «лонг выше SMA100 / вне рынка» (закрытия на границах).
Для longflat последний отрезок у regime_grid не закрывается (мешок по close последней минуты) — к ядру
применяется та же поправка: net − exit_pnl + exit_fee + bag. Допуск — 1e-6 USD."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "research" / "weex"))
import gridk  # noqa: E402
import mr_data as md  # noqa: E402
import regime_grid as rg  # noqa: E402

m, h1, h4, d1, fund = md.build()
a, b = pd.Timestamp("2025-01-01", tz="UTC").timestamp(), pd.Timestamp("2025-03-15", tz="UTC").timestamp()
w = m[(m["ts"] >= a) & (m["ts"] < b)].reset_index(drop=True)
ts = w["ts"].to_numpy(np.int64)
o, h, l, c = (w[k].to_numpy(float) for k in ("open", "high", "low", "close"))
reg = d1["reg0"].reindex(ts // 86400 * 86400).to_numpy() == 1.0
f = fund[(fund.index >= a) & (fund.index < b)]
mk = gridk.Market(ts, o, h, l, c, f)
fdict = {int(i): float(r) for i, r in zip(np.searchsorted(ts, f.index.to_numpy()), f.to_numpy())}
rg.init((ts, o, h, l, c, reg, np.ones(len(ts), bool), None, fdict))
rg.MAX_LOTS = 50
bad = 0
for mode, side in (("long", 1), ("short", -1), ("longflat", 1)):
    r = rg.run(("v", mode, 0, 0.6, 1.4, 0.0012, 6000.0))
    ref_eq = r[5]
    if mode == "longflat":
        on = reg.astype(int)
        st = np.flatnonzero(np.diff(np.r_[0, on]) == 1)
        en = np.flatnonzero(np.diff(np.r_[on, 0]) == -1) + 1
        out = mk.run(st, en, side, step=0.6, tgt=1.4, qty=0.0012, cap=6000.0, max_lots=50)
        last = out[-1]
        if en[-1] >= len(ts):
            mine = out[:, 0].sum() - last[4] + last[12] + last[5]
        else:
            mine = out[:, 0].sum()
        extra = f"эпизодов {len(st)}"
    else:
        out = mk.run([0], [len(ts)], side, step=0.6, tgt=1.4, qty=0.0012, cap=6000.0, max_lots=50)
        mine = out[0, 0] - out[0, 4] + out[0, 12] + out[0, 5]
        extra = f"входов {int(out[0, 7])}, тейков {int(out[0, 8])}"
    diff = mine - ref_eq
    bad += abs(diff) > 1e-6
    print(f"{mode:9s} regime_grid {ref_eq:+.6f}  ядро {mine:+.6f}  разница {diff:+.2e}  ({extra})")
print("СВЕРКА:", "совпадает" if not bad else f"РАСХОЖДЕНИЙ {bad}")
sys.exit(1 if bad else 0)
