"""Стратегия оператора (Простое+, шорт под жёлтой, добор) против 432 на BTC, один учёт: $1000 на сделку, 0.068% на сторону, фандинг по выплате, кривая по часам.
432 как research/btc432_20261103/review.py: 4ч, вход на открытии следующего бара, если закрытие выше максимума 30 прошлых баров, ADX14 ≥ 22, закрытие выше EMA200 и пробой ≥ 0.5 ATR14; выход на открытии следующего бара, если закрытие ниже минимума 30 баров или прошло 20 баров от сигнала; одна позиция; только лонг (шорт у 432 без эджа, 03.11)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

WIN = Path("/private/tmp/claude-501/-Users-alexeychechikov/279942d8-034f-4a29-bc43-ed7d07642e98/scratchpad/win/research/indicator_lab_win")
os.environ["LAB_DATA"] = str(WIN.parent.parent / "data")
sys.path.insert(0, str(WIN))
sys.path.insert(0, str(Path(__file__).parent))
import btc_combo as bcm  # noqa: E402
import lab_core as lc  # noqa: E402
import lab_feat as lf  # noqa: E402

pd.set_option("display.width", 220, "display.max_columns", 30)
CUT = lc.T("2023-01-01")


def s432(S, H=20):
    h, l, c, o = S.h4["h"], S.h4["l"], S.h4["c"], S.h4["o"]
    hi30 = pd.Series(h).shift(1).rolling(30).max().to_numpy()
    lo30 = pd.Series(l).shift(1).rolling(30).min().to_numpy()
    atr = S.atr4(14)
    e200 = lc.ema(c, 200)
    adx = lf.adx(S, 14)[0]
    with np.errstate(invalid="ignore", divide="ignore"):
        ent = (c > hi30) & (adx >= 22) & (c > e200) & ((c - hi30) / atr >= 0.5)
    ent[:300] = False
    last_hour = np.clip(np.searchsorted(S.t, S.h4["known"], side="right") - 1, 0, len(S.t) - 1)
    j0 = int(np.searchsorted(S.h4["known"], S.t[S.i0]))
    legs, pos, n = [], None, len(c)
    for i in range(max(j0, 300), n - 1):
        if pos is not None:
            if c[i] < lo30[i] or i - pos[1] >= H:
                legs.append((pos[0], int(last_hour[i]), pos[2], float(o[i + 1]), 1, 1.0, "432", "выход"))
                pos = None
            continue
        if ent[i]:
            pos = (int(last_hour[i]), i, float(o[i + 1]))
    if pos is not None:
        legs.append((pos[0], len(S.t) - 1, pos[2], float(S.c[-1]), 1, 1.0, "432", "конец"))
    return legs


def seg(eq, x, y):
    e = eq[x:y + 1] - eq[x]
    d = float((e - np.maximum.accumulate(e)).min())
    return round(float(e[-1]), 1), round(d, 1), round(float(e[-1]) / max(abs(d), 1.0), 2)


def report(S, legs, lab):
    eq = lc.equity(S, legs)
    n = len(S.t) - 1
    k = min(int(np.searchsorted(S.t, CUT)), n)
    a, p1, p2 = seg(eq, S.i0, n), seg(eq, S.i0, k), seg(eq, k, n)
    r = lc.nets(S, legs)
    t0 = S.t[np.array([x[0] for x in legs])]
    yrs = pd.Series(r).groupby(pd.to_datetime(t0, unit="s").year).sum()
    days_in = sum(x[1] - x[0] for x in legs) / max(n - S.i0, 1) * 100
    return {"что": lab, "сделок": len(r), "итог": a[0], "просадка": a[1], "отн": a[2], "с2025": round(float(r[t0 >= lc.CUT25].sum()), 1), "2018–22": f"{p1[0]:+.0f} / {p1[1]:.0f}", "2023–26": f"{p2[0]:+.0f} / {p2[1]:.0f}", "лет в плюсе": f"{int((yrs > 0).sum())} из {len(yrs)}", "в рынке %": round(days_in), "на сделку": round(float(r.mean()), 2)}, eq


def main():
    S, Bs = lc.load("BTC"), lc.load("Bitstamp")
    sys_kw = dict(reg=("E", 200), klx=2, sx=lc.G, ksx=2, cs=True, fund=None)
    rows, eqs = [], {}
    for lab, fn in (("твоя: Простое+, шорт под жёлтой, добор", lambda X: bcm.pyramid(X, bcm.run(X, **sys_kw))), ("простое правило R", lambda X: lc.run(X)), ("432, лонг", s432)):
        r, eq = report(S, fn(S), lab)
        rb, _ = report(Bs, fn(Bs), lab)
        r["Bitstamp"] = f"{rb['итог']:+.0f} / {rb['просадка']:.0f}"
        rows.append(r)
        eqs[lab] = eq
    print(pd.DataFrame(rows).to_string(index=False), flush=True)
    d = pd.DataFrame({k: pd.Series(v, index=pd.to_datetime(S.t, unit="s")) for k, v in eqs.items()})
    d = d[d.index >= pd.Timestamp(int(S.t[S.i0]), unit="s")].resample("1D").last().diff().dropna()
    a, b = d.columns[0], d.columns[2]
    print("связь дневных изменений твоей и 432:", round(float(d[a].corr(d[b])), 2), flush=True)
    both = (d[a] + d[b]).cumsum().to_numpy()
    dd = float((both - np.maximum.accumulate(np.r_[0.0, both])[1:]).min())
    print(f"обе вместе по $1000: итог {both[-1]:+.0f}, просадка {dd:.0f}, отношение {both[-1] / abs(dd):.2f}", flush=True)


if __name__ == "__main__":
    main()
