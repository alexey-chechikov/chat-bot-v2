"""Свои улучшения 432 BTC H4 (R1 ретест, R2 размер по волатильности, R3 + шорт-кандидат, R4 частичная фиксация).
Правила — PREREG.md (дописка до запуска). Запуск: my_rules.py --pk-btc=<bars_*.pkl BTC>"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "research" / "operator_rules_20261103"))
from review import COST, PERIODS, Data, run, ts  # noqa: E402
from sweep import TF  # noqa: E402

MAKER = 0.00016


def eq_stats(D: Data, legs: list) -> dict:
    """legs: (j вход, k выход, цена входа, сторона, вес, net). Переоценка по закрытиям H4; итог, просадка, отношение."""
    eq = np.zeros(len(D.c))
    for j, k, px, s, w, net in legs:
        eq[j:k] += w * (s * (D.c[j:k] / px - 1) - COST)
        eq[k:] += w * net
    out = {}
    for name, (a, b) in list(PERIODS.items()) + [("всё", ("2017-01-01", "2030-01-01"))]:
        m = (D.t >= ts(a)) & (D.t < ts(b))
        e = eq[m] - (eq[m][0] if m.any() else 0)
        s_ = float(e[-1]) if m.any() else 0.0
        dd = float(np.max(np.maximum.accumulate(np.r_[0.0, e]) - np.r_[0.0, e]))
        n = sum(1 for j, *_r in legs if ts(a) <= D.t[j] < ts(b))
        out[name] = {"n": n, "sum": 100 * s_, "dd": 100 * dd, "ratio": s_ / dd if dd > 0 else None}
    return out


def legs_432(units, w=None):
    return [(u["j"], u["k"], u["px"], u["side"], 1.0 if w is None else w[u["first"]], u["net"]) for u in units]


def r1_retest(D: Data, M: int):
    o, h, l, c, n = D.o, D.h, D.l, D.c, len(D.c)
    ent = D.ent[1]
    legs, i = [], 0
    while i < n - 1:
        if not ent[i]:
            i += 1
            continue
        lvl, fill = D.hi30[i], None
        for b in range(i + 1, min(i + 1 + M, n)):
            if l[b] <= lvl:
                fill = (b, min(o[b], lvl))
                break
        if fill is None:
            i = min(i + M, n - 1) + 1
            continue
        j, px = fill
        k = None
        for q in range(j, n - 1):
            if c[q] < D.lo30[q] or q - i >= 20:
                k = q + 1
                break
        if k is None:
            k = n - 1
        out = o[k] if k < n - 1 else c[-1]
        net = out / px - 1 - MAKER - COST - D.fsum(j, k)
        legs.append((j, k, px, 1, 1.0, net))
        i = k
    return legs


def r4_partial(D: Data, units, kATR: float):
    legs = []
    for u in units:
        j, k, px = u["j"], u["k"], u["px"]
        tp = px + kATR * u["atr"]
        hit = np.flatnonzero(D.h[j:k] >= tp)
        if len(hit):
            jj = j + int(hit[0])
            net_half = tp / px - 1 - COST - MAKER - D.fsum(j, jj)
            legs.append((j, jj, px, 1, 0.5, net_half))
        else:
            legs.append((j, k, px, 1, 0.5, u["net"]))
        legs.append((j, k, px, 1, 0.5, u["net"]))
    return legs


def main():
    pk = Path(next(a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--pk-btc=")))
    D = Data(pk)
    base = run(D, 1)
    res = {"L0 исходная": eq_stats(D, legs_432(base))}
    for M in (3, 6, 12):
        res[f"R1 ретест, лимит живёт {M} баров"] = eq_stats(D, r1_retest(D, M))
    atrp = D.atr / D.c
    med = pd.Series(atrp).rolling(2190, min_periods=500).median().shift(1).to_numpy()
    w = np.clip(med / atrp, 0.5, 2.0)
    w = np.where(np.isfinite(w), w, 1.0)
    res["R2 размер по волатильности"] = eq_stats(D, legs_432(base, w))
    for k in (2.0, 3.0, 4.0):
        res[f"R4 половина на +{k:g} ATR"] = eq_stats(D, r4_partial(D, base, k))
    m, h1, h4, d1, fund = pd.read_pickle(pk)
    del m, h1
    tf = TF("H4", h4, h4, fund)
    sig = tf.signal(-1, "свой", "любое", 1, True)
    rows = tf.run(-1, sig, tf.next_cut(-1, "свой", 3, None), None)
    short = [(e, xb, tf.o[e], -1, 1.0, net) for e, xb, net, _w in rows]
    res["S* шорт-кандидат отдельно"] = eq_stats(D, short)
    res["R3 L0 + S* шорт-кандидат"] = eq_stats(D, legs_432(base) + short)
    (HERE / "out" / "my_rules.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    cols = list(PERIODS) + ["всё"]
    print("| Вариант | " + " | ".join(f"{p}: n · сумма % · просадка % · итог/просадка" for p in cols) + " |")
    print("|---|" + "---|" * len(cols))
    for nm, r in res.items():
        cells = [f"{r[p]['n']} · {r[p]['sum']:+.1f} · {r[p]['dd']:.1f} · {r[p]['ratio']:.2f}" if r[p]["ratio"] is not None
                 else f"{r[p]['n']} · {r[p]['sum']:+.1f} · 0" for p in cols]
        print(f"| {nm} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()
