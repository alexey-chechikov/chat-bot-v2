"""Только биткоин. Ситуации из карты как правила на полном потоке и вес по силе правила поверх Простое+ со шортом под жёлтой. Полный список вариантов здесь, число просмотренных называется. Судья: три периода Binance и Bitstamp 2014–17."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import btc_lab as bl  # noqa: E402
import btc_map as bm  # noqa: E402
import plus as pl  # noqa: E402

pd.set_option("display.width", 230, "display.max_columns", 30, "display.max_rows", 100, "display.max_colwidth", 60)


def arrays(a):
    G, Y, R = a["f_G"], a["f_Y"], a["f_R"]
    n = len(G)
    z = np.maximum(np.arange(n) - 24, 0)
    d_all = (G < G[z]) & (Y < Y[z]) & (R < R[z])
    u_all = (G > G[z]) & (Y > Y[z]) & (R > R[z])
    clean = (R > Y) & (Y > G)
    return {"все_вниз": d_all, "все_вверх": u_all, "чистый": clean}


def main():
    (a, f, lay), (b, fb, layb) = bl.load()
    A, Bb = arrays(a), arrays(b)
    C = {"cs": 1.0}
    V = [("Простое+", {}, None), ("Простое+ и cs вес 1", {"rules": C}, None),
         ("+ нет шорта, когда все три смотрят вниз", {"rules": C}, lambda q: dict(sok=~q["все_вниз"])),
         ("+ нет шорта при порядке R>Y>G", {"rules": C}, lambda q: dict(sok=~q["чистый"])),
         ("+ нет шорта сразу после плюсовой", {"rules": C, "no_s_after_win": True}, None),
         ("+ лонг ×1.5, когда все три смотрят вверх", {"rules": C}, lambda q: dict(lw=np.where(q["все_вверх"], 1.5, 1.0))),
         ("+ лонг ×0.5, когда не все смотрят вверх", {"rules": C}, lambda q: dict(lw=np.where(q["все_вверх"], 1.0, 0.5))),
         ("+ все три условия: не вниз, лонг ×1.5", {"rules": C}, lambda q: dict(sok=~q["все_вниз"], lw=np.where(q["все_вверх"], 1.5, 1.0)))]
    rows = []
    for lab, kw, fn in V:
        ka = {**kw, **(fn(A) if fn else {})}
        kb = {**kw, **(fn(Bb) if fn else {})}
        s = bl.row(a, f, bl.run(a, lay, cut=bl.CUT, **ka))
        sb = pl.stats(b, fb, bl.run(b, layb, **kb))
        rows.append({"вариант": lab, **s, "Bitstamp": sb["итог"], "Bs_просадка": sb["просадка"]})
    d = pd.DataFrame(rows)
    d.to_csv(bl.OUT / "btc_lab2.csv", index=False)
    print(d.to_string(index=False), flush=True)

    print("== вес по силе правила поверх Простое+ и cs, только прошлые годы, 2020–2026", flush=True)
    la, lb = bl.run(a, lay, cut=bl.CUT, rules=C), bl.run(b, layb, rules=C)
    tr = pd.DataFrame([{"ряд": "BTC", "год": pd.Timestamp(int(a["t"][x[0]]), unit="s").year, "r": pl.unit(f, [x])[0][0]} for x in la] + [{"ряд": "Bitstamp", "год": pd.Timestamp(int(b["t"][x[0]]), unit="s").year, "r": pl.unit(fb, [x])[0][0]} for x in lb])
    tags = pd.Series([x[5] for x in la] + [x[5] for x in lb])
    w = bm.walk(tr, tags)[:len(la)]
    vw = np.array([x[7] for x in la])
    rows = [{"вес": "его вес, без силы правила", **bm.eval_w(a, f, la, vw)}, {"вес": "его вес × сила правила", **bm.eval_w(a, f, la, vw * w)}]
    for m, nm in ((np.array([x[5] == "L над синей" for x in la]), "только лонг ×1.5"),):
        rows.append({"вес": nm + " (постоянно)", **bm.eval_w(a, f, la, vw * np.where(m, 1.5, 1.0))})
    print(pd.DataFrame(rows).to_string(index=False), flush=True)
    t0 = pd.to_datetime(a["t"][[x[0] for x in la]], unit="s").year
    print("вес по годам:", pd.DataFrame({"tag": [x[5] for x in la], "год": t0, "w": w}).groupby(["tag", "год"])["w"].mean().round(2).unstack().to_string(), flush=True)

    print("== соседи cs на BTC: все сделки потока", flush=True)
    rows = []
    for lab, wt in (("cs 0.25", 0.25), ("cs 0.5", 0.5), ("cs 0.75", 0.75), ("cs 1", 1.0), ("cs 1.25", 1.25), ("cs 1.5", 1.5)):
        s = bl.row(a, f, bl.run(a, lay, cut=bl.CUT, rules={"cs": wt}))
        sb = pl.stats(b, fb, bl.run(b, layb, rules={"cs": wt}))
        rows.append({"вариант": lab, **s, "Bitstamp": sb["итог"]})
    print(pd.DataFrame(rows).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
