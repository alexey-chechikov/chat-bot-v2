"""Отбор вариантов Вина только по биткоину (оператор 07.11: сначала идеальный BTC). Код Вина из коммита 2449d0b распакован в scratchpad и не менялся. ETH, XRP и монеты не участвуют.
Правила записаны до прогона:
  ряды: BTC Binance spot 2018–07.11.2026 и Bitstamp BTC 2014–17, те же файлы, что у Вина, сверка sha256 с его манифестом;
  часть 1 = 2018–2022, часть 2 = 2023–07.11.2026, разрез на кривой по часам с открытыми сделками; мера — итог / просадка внутри части;
  каждый вариант считается на двух слоях: как у Вина и поверх Простое+ (ранг ≤0.6 для шорта, вес от ATR100, делитель 1.18). Размер Ж на слое Простое+ не считается: там он уже есть;
  опорные значения: Простое+ и Простое+ с шортом под жёлтой вес 1;
  кандидат = лучше Простое+ в части 1, в части 2 и на Bitstamp, итог всей истории не ниже;
  отбор по времени: в каждом семействе лучший вариант только по части 1, смотрим его часть 2 и Bitstamp;
  контроль перебора: доля вариантов, лучших в части 2, среди лучших в части 1 против доли среди всех; ранговая связь частей."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

WIN = Path("/private/tmp/claude-501/-Users-alexeychechikov/279942d8-034f-4a29-bc43-ed7d07642e98/scratchpad/win/research/indicator_lab_win")
os.environ["LAB_DATA"] = str(WIN.parent.parent / "data")
sys.path.insert(0, str(WIN))
import fam_i as fi  # noqa: E402
import fam_z as fz  # noqa: E402
import lab_core as lc  # noqa: E402
import lab_data as ld  # noqa: E402
import lab_sweep as ls  # noqa: E402
import words4 as w4  # noqa: E402

OUT = Path(__file__).parent / "out"
CSV = OUT / "btc_win_review.csv"
CUT = lc.T("2023-01-01")


def seg(eq, x, y):
    e = eq[x:y + 1] - eq[x]
    d = float((e - np.maximum.accumulate(e)).min())
    return round(float(e[-1]), 1), round(d, 1), round(float(e[-1]) / max(abs(d), 1.0), 2)


def measure(S, Bs, legs_fn):
    la = legs_fn(S)
    eq = lc.equity(S, la)
    k = int(np.searchsorted(S.t, CUT))
    n = len(S.t) - 1
    a, p1, p2 = seg(eq, S.i0, n), seg(eq, S.i0, k), seg(eq, k, n)
    r = lc.nets(S, la)
    t0 = S.t[np.array([x[0] for x in la])]
    lb = legs_fn(Bs)
    eb = lc.equity(Bs, lb)
    b = seg(eb, Bs.i0, len(Bs.t) - 1)
    return {"n": len(la), "итог": a[0], "просадка": a[1], "отн": a[2], "итог1": p1[0], "пр1": p1[1], "отн1": p1[2], "итог2": p2[0], "пр2": p2[1], "отн2": p2[2], "с2025": round(float(r[t0 >= lc.CUT25].sum()), 1), "Bs": b[0], "Bs_пр": b[1], "Bs_отн": b[2]}


def plus_kw(S):
    return w4.plus_layer(S)


def sweep_plus(S, spec):
    spec = dict(spec)
    pl = plus_kw(S)
    if "ens" in spec:
        out = []
        members = spec.pop("ens")
        for m in members:
            for x in sweep_plus(S, {**spec, **m}):
                out.append((*x[:5], x[5] / len(members), *x[6:]))
        return out
    if "flt" in spec:
        L, Sh = ls.masks(S, spec.pop("flt"))
        spec["Lok"], spec["Sok"] = L, Sh & pl["Sok"]
    else:
        spec["Sok"] = pl["Sok"]
    spec["w_fn"] = pl["w_fn"]
    return lc.run(S, **spec)


def jobs():
    J = []
    for fam, name, spec in ls.variants():
        J.append((fam, name, "как у Вина", lambda S, sp=spec: ls.legs_of(S, sp)))
        if "vol" not in spec:
            J.append((fam, name, "Простое+", lambda S, sp=spec: sweep_plus(S, sp)))
    for sn, ln, pn, zn in fz.grid():
        J.append(("З", f"шорт {sn}, лонг {ln}, пауза {pn}, {zn}", "сборка", lambda S, a=sn, b=ln, c=pn, d=zn: fz.legs_z(S, fz.SHORT[a], fz.LONG[b], fz.PAUSE[c], fz.SIZE[d], norm=False)))
    for fam, name, spec in fi.variants():
        for lay in ("постоянный", "плюс"):
            J.append((fam, name, lay, lambda S, sp=spec, l=lay: fi.legs_of(S, sp, l)))
    return J


def main():
    S, Bs = lc.load("BTC"), lc.load("Bitstamp")
    J = jobs()
    print("прогонов", len(J), flush=True)
    t0 = time.time()
    rows = []
    for q, (fam, name, lay, fn) in enumerate(J):
        try:
            rows.append({"семейство": fam, "вариант": name, "слой": lay, **measure(S, Bs, fn)})
        except Exception as e:  # пропуск вариантов без сделок записывается
            rows.append({"семейство": fam, "вариант": name, "слой": lay, "ошибка": str(e)[:80]})
        if q % 300 == 0:
            pd.DataFrame(rows).to_csv(CSV, index=False)
            print(q, f"{time.time() - t0:.0f}с", flush=True)
    pd.DataFrame(rows).to_csv(CSV, index=False)
    print("готово", len(rows), f"{time.time() - t0:.0f}с", flush=True)


if __name__ == "__main__":
    main()
