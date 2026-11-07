"""Выход шорта по запискам оператора: откуда просадка BTC и можно ли взять прибавку без неё. Разведка сверх правила из предрегистрации: в резерв не идёт, только следующая гипотеза.
Запуск: python -X utf8 short_exit_look.py"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import candidate as cd
import lab_core as lc
import lab_data as ld
import words4 as w4

OUT = Path(__file__).parent / "out"
pd.set_option("display.width", 240, "display.max_columns", 40, "display.max_rows", 100, "display.max_colwidth", 48)
Y, G, R, B = lc.Y, lc.G, lc.R, lc.B
CS = w4.CS


def legs(S, kw):
    return w4.run(S, **{**w4.plus_layer(S), **kw})


def split_half(S):
    """Половина шорта закрывается над зелёной, остаток над жёлтой: две половины идут отдельными сделками."""
    pl = w4.plus_layer(S)
    a = w4.run(S, **pl)
    b = w4.run(S, **pl, sx=Y)
    out = [(*x[:5], x[5] * 0.5 if x[4] == -1 else x[5] * 0.5, *x[6:]) for x in a] + [(*x[:5], x[5] * 0.5, *x[6:]) for x in b]
    return out


def dd_when(S, ll):
    eq = lc.equity(S, ll)[S.i0:]
    t = S.t[S.i0:]
    peak = np.maximum.accumulate(np.r_[0.0, eq])[1:]
    d = eq - peak
    i = int(np.argmin(d))
    p = int(np.argmax(eq[:i + 1])) if i > 0 else 0
    return round(float(d.min()), 1), pd.Timestamp(int(t[p]), unit="s").strftime("%d.%m.%Y"), pd.Timestamp(int(t[i]), unit="s").strftime("%d.%m.%Y")


def main():
    SS = {n: lc.load(n) for n in ("BTC", "ETH", "XRP", "Bitstamp")}
    coins = {c: lc.load(c) for c in ld.COINS20}
    ref = {c: lc.stats(S, cd.frozen(S)) for c, S in coins.items()}
    plan = [("Простое+", lambda S: legs(S, {})), ("+ противовес половиной", lambda S: legs(S, CS)), ("выход шорта над жёлтой", lambda S: legs(S, dict(sx=Y))), ("половина над зелёной, остаток над жёлтой", split_half),
            ("выход при построении вверх или над синей", lambda S: legs(S, dict(sx_stack="stack_or_blue"))), ("противовес + над жёлтой", lambda S: legs(S, {**CS, "sx": Y})), ("противовес + построение или над синей", lambda S: legs(S, {**CS, "sx_stack": "stack_or_blue"}))]
    rows = []
    for lab, fn in plan:
        r = {"вариант": lab}
        for n, S in SS.items():
            st = lc.stats(S, fn(S))
            r[n] = f"{st['итог']:+.0f}/{st['просадка']:.0f}"
            if n != "Bitstamp":
                r[n + "_25"] = round(st["с2025"])
            if n == "BTC":
                r["n"] = st["n"]
                r["периоды"] = f"{st['p1']:+.0f}/{st['p2']:+.0f}/{st['p3']:+.0f}"
                r["BTC_дно"] = dd_when(S, fn(S))[1:]
        c = {k: lc.stats(S, fn(S)) for k, S in coins.items()}
        r["монеты"] = round(sum(x["итог"] for x in c.values()))
        r["лучше"] = sum(c[k]["итог"] > ref[k]["итог"] for k in coins)
        r["монеты_дд"] = round(float(np.median([x["просадка"] for x in c.values()])))
        r["монеты25"] = round(sum(x["с2025"] for x in c.values()))
        rows.append(r)
    print(pd.DataFrame(rows).to_string(index=False))
    S = SS["BTC"]
    print("\nГоды BTC:")
    y = {}
    for lab, fn in plan:
        ll = fn(S)
        y[lab] = pd.Series(lc.nets(S, ll)).groupby(pd.to_datetime(S.t[[x[0] for x in ll]], unit="s").year).sum().round(0)
    print(pd.DataFrame(y).T.to_string())
    print("\nХудшие шорты BTC при выходе над жёлтой и при построении:")
    for lab, kw in (("над жёлтой", dict(sx=Y)), ("построение или над синей", dict(sx_stack="stack_or_blue"))):
        ll = [x for x in legs(S, kw) if x[4] == -1]
        r = lc.nets(S, ll)
        for k in np.argsort(r)[:4]:
            x = ll[k]
            print(lab, pd.Timestamp(int(S.t[x[0]]), unit="s").strftime("%d.%m.%Y"), pd.Timestamp(int(S.t[x[1]]), unit="s").strftime("%d.%m.%Y"), round(x[2]), round(x[3]), "вес", round(x[5], 2), "итог", round(float(r[k]), 1))


if __name__ == "__main__":
    main()
