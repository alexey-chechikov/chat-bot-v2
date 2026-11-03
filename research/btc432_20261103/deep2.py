"""Из диагностики D2 (пропущенные движения ниже EMA200): M — мягче фильтр тренда; U — «разворотная нога» 432 ниже EMA200.
Правила — PREREG.md (дописка после deep.py, до запуска). Запуск: deep2.py --pk-btc=<pkl> --pk-eth=<pkl>"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "research" / "tv_lab_1025"))
import strategies as S  # noqa: E402
from deep import PN, Ctx, better, run2  # noqa: E402
from my_rules import eq_stats  # noqa: E402

OUT = Path(__file__).parent / "out"


def ent_with(X: Ctx, trend):
    D, c = X.D, X.D.c
    hi = X.high_n[30]
    with np.errstate(invalid="ignore", divide="ignore"):
        core = (c > hi) & (D.adx >= 22) & ((c - hi) / D.atr >= 0.5)
    e = (core & trend)
    e[:300] = False
    return e


def main():
    args = dict(a.lstrip("-").split("=", 1) for a in sys.argv[1:])
    res = {}
    for sym in ("BTC", "ETH"):
        X = Ctx(Path(args[f"pk-{sym.lower()}"]))
        D, c = X.D, X.D.c
        b = eq_stats(D, run2(X, D.ent[1])[0])
        V = {"M EMA100 вместо EMA200": c > S.ema(c, 100), "M EMA50 вместо EMA200": c > S.ema(c, 50),
             "M без фильтра тренда": np.ones(len(c), bool), "U только ниже EMA200 (разворотная нога)": c < D.e200}
        out = {"L0": b}
        for nm, tr in V.items():
            legs, trades = run2(X, ent_with(X, tr))
            r = eq_stats(D, legs)
            out[nm] = {"stats": r, "better_all3": better(r, b),
                       "better_n": sum(r[p]["ratio"] is not None and b[p]["ratio"] is not None and r[p]["ratio"] > b[p]["ratio"] for p in PN),
                       "n_trades": len(trades), "mean_net_pct": 100 * float(np.mean([t["net"] for t in trades])) if trades else None}
        # L0 + разворотная нога: позиции не пересекаются по входу, но могут пересечься по времени — считаем как две ноги
        legs_u, _ = run2(X, ent_with(X, c < D.e200))
        legs_0, _ = run2(X, D.ent[1])
        r = eq_stats(D, legs_0 + legs_u)
        out["L0 + U вместе"] = {"stats": r, "better_all3": better(r, b),
                                "better_n": sum(r[p]["ratio"] is not None and r[p]["ratio"] > b[p]["ratio"] for p in PN)}
        res[sym] = out
        print(f"\n== {sym}: L0 " + " | ".join(f"{p} {b[p]['sum']:+.1f} · {b[p]['ratio']:.2f}" for p in PN))
        for nm, v in out.items():
            if nm == "L0":
                continue
            r = v["stats"]
            print(f"| {nm} | " + " | ".join(f"{r[p]['sum']:+.1f} · {r[p]['dd']:.1f} · {(r[p]['ratio'] or 0):.2f}" for p in PN)
                  + f" | лучше L0 в {v['better_n']} из 3 | сделок {v.get('n_trades', '—')} · ср. {v.get('mean_net_pct') or 0:+.2f}% |")
    (OUT / "deep2_result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))


if __name__ == "__main__":
    main()
