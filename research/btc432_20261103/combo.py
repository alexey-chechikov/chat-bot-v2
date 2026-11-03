"""Ближайшие кандидаты вместе (PREREG.md, дописка до запуска): 432 + E4 «ADX растёт за 3» + E10 «фандинг < 0.05%» + R2;
и 432 + E4 + R2. BTC — решение, ETH — подтверждение. Запуск: combo.py --pk-btc=<pkl> --pk-eth=<pkl>"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from deep import PN, Ctx, run2  # noqa: E402
from my_rules import eq_stats  # noqa: E402


def main():
    args = dict(a.lstrip("-").split("=", 1) for a in sys.argv[1:])
    res = {}
    for sym in ("BTC", "ETH"):
        X = Ctx(Path(args[f"pk-{sym.lower()}"]))
        D = X.D
        base = D.ent[1]
        up3 = D.adx > np.r_[np.full(3, np.nan), D.adx[:-3]]
        fr_ok = ~(X.fr_last >= 0.0005)
        V = {"L0": run2(X, base)[0], "R2": run2(X, base, w=X.w_r2)[0],
             "E4 + R2": run2(X, base & up3, w=X.w_r2)[0],
             "E4 + E10 + R2": run2(X, base & up3 & fr_ok, w=X.w_r2)[0]}
        st = {k: eq_stats(D, v) for k, v in V.items()}
        res[sym] = st
        print(f"\n== {sym}")
        for k, r in st.items():
            vs0 = sum(r[p]["ratio"] > st["L0"][p]["ratio"] for p in PN)
            vs2 = sum(r[p]["ratio"] > st["R2"][p]["ratio"] for p in PN)
            print(f"| {k} | " + " | ".join(f"{r[p]['n']} · {r[p]['sum']:+.1f} · DD {r[p]['dd']:.1f} · {r[p]['ratio']:.2f}" for p in PN)
                  + f" | лучше L0 в {vs0}/3, лучше R2 в {vs2}/3 |")
    (Path(__file__).parent / "out" / "combo.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))


if __name__ == "__main__":
    main()
