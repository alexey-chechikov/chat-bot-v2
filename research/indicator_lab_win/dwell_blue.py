"""И8, вопрос оператора: если цена держится под синей больше скольких-то дней, что дальше. Каждый эпизод под синей даёт одно наблюдение на день D (если дожил). Состояние цветных и наклон синей на этот момент.
Запуск: python -X utf8 dwell_blue.py"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import lab_core as lc

OUT = Path(__file__).parent / "out"
pd.set_option("display.width", 230, "display.max_columns", 40, "display.max_rows", 300)
DAYS = (0, 1, 2, 3, 5, 7, 10, 14, 21, 30, 45, 60)


def table(S, side=-1):
    c = S.h4["c"]
    k4 = S.h4["known"]
    G, Y, R, B = S.line4(lc.G), S.line4(lc.Y), S.line4(lc.R), S.line4(lc.B)
    rB = S.run4(lc.B)
    j0 = int(np.searchsorted(k4, S.t[S.i0]))
    n = len(c)
    # конец эпизода: 2 закрытия с другой стороны синей
    ends = np.flatnonzero(side * rB <= -2)
    rows = []
    for D in DAYS:
        need = max(D * 6, 2)
        ev = np.flatnonzero((side * rB == need) & (np.arange(n) >= j0))
        if len(ev) == 0:
            continue
        pos = np.searchsorted(ends, ev, side="right")
        ok = pos < len(ends)
        ev = ev[ok]
        x = ends[pos[ok]]
        pnl = side * (c[x] / c[ev] - 1) * 100 - 0.136
        left = (x - ev) / 6
        f10 = np.array([side * (c[min(e + 60, n - 1)] / c[e] - 1) * 100 for e in ev])
        z = np.maximum(ev - 30, 0)
        slope_with = side * (B[ev] - B[z]) > 0
        st_with = ((G[ev] < Y[ev]) & (Y[ev] < R[ev])) if side == -1 else ((G[ev] > Y[ev]) & (Y[ev] > R[ev]))
        st_against = ((G[ev] > Y[ev]) & (Y[ev] > R[ev])) if side == -1 else ((G[ev] < Y[ev]) & (Y[ev] < R[ev]))
        rows.append({"ряд": S.name, "день": D, "эпизодов": len(ev), "сред_итог_%": round(float(pnl.mean()), 2), "медиана_%": round(float(np.median(pnl)), 2), "плюс_%": round(float((pnl > 0).mean() * 100)), "сумма_%": round(float(pnl.sum())), "осталось_дней_медиана": round(float(np.median(left)), 1),
                     "через10д_%": round(float(f10.mean()), 2), "синяя_по_ходу_n": int(slope_with.sum()), "сумма_при_синей": round(float(pnl[slope_with].sum())), "синяя_против_n": int((~slope_with).sum()), "сумма_против": round(float(pnl[~slope_with].sum())),
                     "выстроены_n": int(st_with.sum()), "сумма_выстроены": round(float(pnl[st_with].sum())), "обратно_n": int(st_against.sum()), "сумма_обратно": round(float(pnl[st_against].sum()))})
    return pd.DataFrame(rows)


def main():
    all_ = []
    for nm in ("BTC", "ETH", "XRP", "Bitstamp"):
        S = lc.load(nm)
        t = table(S)
        all_.append(t)
        print(f"\n=== {nm}: шорт с дня D под синей до 2 закрытий над синей (без учёта фандинга)")
        print(t.drop(columns=["ряд"]).to_string(index=False))
    pd.concat(all_).to_csv(OUT / "dwell_blue.csv", index=False)


if __name__ == "__main__":
    main()
