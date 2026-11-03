"""Пост-хок проверка «потолок ADX на входе 432» (PREREG.md): BTC — где замечено, ETH — решает.
Запуск: adx_check.py --pk-btc=<pkl> --pk-eth=<pkl>"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from review import PERIODS, Data, run, stats  # noqa: E402


def main():
    args = dict(a.lstrip("-").split("=", 1) for a in sys.argv[1:])
    for sym, key in (("BTC", "pk-btc"), ("ETH", "pk-eth")):
        D = Data(Path(args[key]))
        base_ent = D.ent[1].copy()
        rows = {}
        for cap in (None, 30, 35, 40):
            D.ent[1] = base_ent & (D.adx <= cap) if cap else base_ent
            u = run(D, 1)
            rows["L0" if cap is None else f"ADX ≤ {cap}"] = stats(D, u)
            if cap is None:
                x = np.array([x["net"] for x in u])
                a = D.adx[np.array([x["first"] for x in u])]
                rho = pd.Series(a).rank().corr(pd.Series(x).rank())
                print(f"{sym}: Spearman(ADX на входе, net) по всем {len(x)} сделкам {rho:+.3f}")
        D.ent[1] = base_ent
        print(f"| {sym} | " + " | ".join(f"{p}: n · сумма % · просадка %" for p in PERIODS) + " | всё: сумма · ср. [ДИ] |")
        for nm, r in rows.items():
            cells = [f"{r[p]['n']} · {r[p]['sum']:+.1f} · {r[p]['dd']:.1f}" for p in PERIODS]
            a = r["всё"]
            print(f"| {nm} | " + " | ".join(cells) + f" | {a['sum']:+.1f} · {a['mean']:+.2f} [{a['ci'][0]:+.2f}…{a['ci'][1]:+.2f}] |")


if __name__ == "__main__":
    main()
