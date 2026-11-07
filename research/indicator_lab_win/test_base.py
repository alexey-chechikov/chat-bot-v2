"""Сверка движка (W4): база обязана давать те же сделки, что words3.run и pine_mirror_simple.run, и те же числа, что таблица задания.
words3.py и pine_mirror_simple.py импортируются как есть, зависимости с жёстко заданными путями Мака заменены заглушками. Логика run не меняется.
Запуск: python -X utf8 test_base.py
"""
from __future__ import annotations

import sys
import time
import types
from pathlib import Path

import numpy as np
import pandas as pd

import lab_core as lc

CW = Path(__file__).parents[1] / "chart_walk_20261105"


def _stub(name, **kw):
    m = types.ModuleType(name)
    m.__dict__.update(kw)
    sys.modules[name] = m
    return m


def import_mac():
    """Настоящие words3.run и pine_mirror_simple.run без их зависимостей: run читает только словарь a."""
    _stub("cw_data", T=lc.T)
    for nm in ("ledger", "state_map", "words2", "bybit_check", "state_card", "words3_look"):
        _stub(nm)
    sys.path.insert(0, str(CW))
    import pine_mirror_simple as pm  # noqa: E402
    import words3 as w3  # noqa: E402
    return w3, pm


def mac_arrays(S):
    """Словарь a из определений задания (закрытая 4ч на каждом часе)."""
    j = S.j
    g4 = {k: S.line4(v) for k, v in {"G": lc.G, "Y": lc.Y, "R": lc.R, "B": lc.B}.items()}
    b1 = S.line1(lc.B)
    jp = np.clip(np.searchsorted(S.h4["known"], S.t - 3600, side="right") - 1, 0, None)
    a = {"t": S.t, "o": S.o, "h": S.h, "l": S.l, "c": S.c, "j": j, "i0": S.i0, "atr4": S.atr4()[j], "f_close": S.h4["c"][j], "B4p": g4["B"][jp], "B1h": b1, "f_B1": b1}
    for k, v in g4.items():
        a["f_" + k] = v[j]
        a["f_run_" + k] = lc.run_len(S.h4["c"] - v)[j]
    return a


def table_row(S, lx):
    st = lc.stats(S, lc.run(S, lx=lx))
    return st


REF = {  # w3_sweep.csv на коммите f18eb2a: итог, просадка, n, лонг, шорт, с2025
    ("BTC", "R"): (360.9, -64.3, 589, 320.2, 40.7, -5.3), ("BTC", "G"): (282.4, -49.3, 836, 255.2, 27.2, -5.2),
    ("ETH", "R"): (616.9, -104.1, 590, 505.7, 111.2, 23.5), ("ETH", "G"): (490.5, -84.0, 828, 386.4, 104.1, 46.4),
    ("Bitstamp", "R"): (322.0, -70.4, 242, 367.0, -45.0, 0.0), ("Bitstamp", "G"): (281.9, -47.1, 354, 293.5, -11.6, 0.0),
    ("XRP", "R"): (534.6, -137.2, 433, 574.1, -39.5, -50.5), ("XRP", "G"): (300.7, -150.8, 598, 334.5, -33.8, -12.6),
}
LINES = {"R": lc.R, "G": lc.G, "Y": lc.Y}


def main():
    w3, pm = import_mac()
    print("== 1. Сделки против файла Мака where_lose_trades_R.csv (BTC, выход R, данные до 06.11.2026 16:00)")
    d = pd.read_csv(CW / "out" / "where_lose_trades_R.csv", encoding="utf8")
    S = lc.load("BTC", cut=lc.T("2026-11-06 16:00"))
    legs = lc.run(S, lx=lc.R)
    r = lc.nets(S, legs)
    mine = pd.DataFrame({"t0": S.t[[x[0] for x in legs]], "s": [x[4] for x in legs], "p0": [x[2] for x in legs], "p1": [x[3] for x in legs], "r": r})
    print("Мак:", len(d), round(d["r"].sum(), 1), " мой:", len(mine), round(mine["r"].sum(), 1))
    m = d.merge(mine, on=["t0", "s"], how="outer", suffixes=("_м", "_я"), indicator=True)
    print("совпало входов:", int((m["_merge"] == "both").sum()), "только Мак:", int((m["_merge"] == "left_only").sum()), "только я:", int((m["_merge"] == "right_only").sum()))
    b = m[m["_merge"] == "both"]
    print("макс. разница цены входа %:", round(float((b["p0_м"] / b["p0_я"] - 1).abs().max() * 100), 4), "выхода %:", round(float((b["p1_м"] / b["p1_я"] - 1).abs().max() * 100), 4), "итога пунктов:", round(float((b["r_м"] - b["r_я"]).abs().max()), 4))
    dif = m[m["_merge"] != "both"]
    if len(dif):
        print(dif.head(20).to_string())

    print("== 2. Настоящие words3.run и pine_mirror_simple.run на моих массивах")
    ok = True
    for name in ("BTC", "ETH", "XRP", "Bitstamp"):
        S = lc.load(name)
        a = mac_arrays(S)
        for ex, ln in (("R", lc.R), ("G", lc.G), ("Y", lc.Y)):
            t0 = time.perf_counter()
            mine = lc.run(S, lx=ln)
            dt = time.perf_counter() - t0
            ref = w3.run(a, l_align=False, s_align=False, l_exit=ex)
            same = [(x[0], x[1], x[4]) for x in mine] == [(x[0], x[1], x[4]) for x in ref] and np.allclose([x[3] for x in mine], [x[3] for x in ref]) and np.allclose([x[2] for x in mine], [x[2] for x in ref])
            print(name, ex, "сделок", len(mine), "совпало с words3:", same, f"движок {dt * 1000:.0f} мс")
            ok &= same
            if ex in ("R", "G"):
                lab = "под красной" if ex == "R" else "под зелёной"
                pm_ref = pm.run(a, lab)
                same2 = [(x[0], x[1], x[4]) for x in mine if x[7] != "конец"] == [(x[0], x[1], x[4]) for x in pm_ref]
                print(name, ex, "совпало с pine_mirror_simple (закрытые):", same2)
                ok &= same2
        for st in (2.0, 6.0):
            mine = lc.run(S, lx=lc.R, stop=st, cool=0)
            ref = w3.run(a, l_align=False, s_align=False, l_exit="R", stop=st)
            print(name, f"стоп {st} ATR: мой {len(mine)} сделок, words3 {len(ref)} (у words3 блокировка повторного входа, у меня её нет, разница ожидаема)")
    print("все сделки совпали:", ok)

    print("== 3. Числа таблицы задания (данные до моей отсечки) и подбор конца данных Мака")
    for (name, ex), rf in REF.items():
        S = lc.load(name)
        st = lc.stats(S, lc.run(S, lx=LINES[ex]))
        print(name, ex, "мой", st["итог"], st["просадка"], st["n"], st["лонг"], st["шорт"], st["с2025"], "| Мак", rf)
    rows = []
    for name, cut in (("BTC", "2026-11-05 00:00"), ("BTC", "2026-11-05 12:00"), ("BTC", "2026-11-06 00:00"), ("BTC", "2026-11-06 16:00")):
        S = lc.load(name, cut=lc.T(cut))
        st = lc.stats(S, lc.run(S, lx=lc.R))
        rows.append((name, cut, st["итог"], st["просадка"], st["n"]))
    print(rows)
    assert ok


if __name__ == "__main__":
    main()
