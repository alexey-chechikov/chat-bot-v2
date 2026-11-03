"""Размер по волатильности на правилах оператора (PREREG.md, дописка до запуска): настройки индикатора по умолчанию на H1
(лонг и шорт) и шорт-кандидат H4. Запуск: r2_operator.py --pk-btc=<pkl>"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "research" / "tv_lab_1025"))
import strategies as S  # noqa: E402
from sweep import COST_T, PER, TF, ts  # noqa: E402


def weights(tf: TF, year_bars: int) -> np.ndarray:
    atrp = S.atr(tf.h, tf.l, tf.c, 14) / tf.c
    med = pd.Series(atrp).rolling(year_bars, min_periods=year_bars // 4).median().shift(1).to_numpy()
    w = np.clip(med / atrp, 0.5, 2.0)
    return np.where(np.isfinite(w), w, 1.0)


def curve(tf: TF, rows, side, w=None) -> dict:
    eq = np.zeros(tf.n)
    for e, xb, net, _why in rows:
        wt = 1.0 if w is None else w[e - 1]
        px = tf.o[e]
        eq[e:xb] += wt * (side * (tf.c[e:xb] / px - 1) - COST_T)
        eq[xb:] += wt * net
    out = {}
    for p, (a, b) in PER.items():
        m = (tf.t >= ts(a)) & (tf.t < ts(b))
        x = eq[m] - eq[m][0]
        dd = float(np.max(np.maximum.accumulate(np.r_[0.0, x]) - np.r_[0.0, x]))
        out[p] = {"sum": 100 * float(x[-1]), "dd": 100 * dd, "ratio": float(x[-1]) / dd if dd > 0 else None}
    return out


def main():
    pk = Path(next(a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--pk-btc=")))
    m, h1, h4, d1, fund = pd.read_pickle(pk)
    del m
    TFS = {"H1": (TF("H1", h1, h4, fund), 8760), "H4": (TF("H4", h4, h4, fund), 2190)}
    sets = {"индикатор по умолчанию, H1 лонг": ("H1", 1, "любое", 2, False, 5, 0.015, None),
            "индикатор по умолчанию, H1 шорт": ("H1", -1, "любое", 2, False, 5, 0.015, None),
            "шорт-кандидат H4": ("H4", -1, "любое", 1, True, 3, None, None)}
    res = {}
    for nm, (tfn, side, fam, N, flat, K, x, hold) in sets.items():
        tf, yb = TFS[tfn]
        rows = tf.run(side, tf.signal(side, "свой", fam, N, flat), tf.next_cut(side, "свой", K, x), hold)
        b, r = curve(tf, rows, side), curve(tf, rows, side, weights(tf, yb))
        res[nm] = {"без веса": b, "с весом": r, "лучше во всех 3": all(
            r[p]["ratio"] is not None and b[p]["ratio"] is not None and r[p]["ratio"] > b[p]["ratio"] for p in PER)}
        print(f"\n{nm}: сделок {len(rows)}")
        for k in ("без веса", "с весом"):
            print(f"  {k}: " + " | ".join(f"{p} {res[nm][k][p]['sum']:+.1f} · DD {res[nm][k][p]['dd']:.1f} · "
                                          f"{(res[nm][k][p]['ratio'] or 0):.2f}" for p in PER))
        print(f"  лучше во всех трёх: {res[nm]['лучше во всех 3']}")
    (HERE / "out" / "r2_operator.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))


if __name__ == "__main__":
    main()
