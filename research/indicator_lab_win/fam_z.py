"""Семейство З из PREREG_win.md: сборка кандидата. Запуск: python -X utf8 fam_z.py [--workers 4]"""
from __future__ import annotations

import ctypes
import itertools
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

import lab_core as lc
import lab_data as ld
import lab_feat as lf
import lab_sweep as ls

OUT = Path(__file__).parent / "out"
SHORT = {"без": [], "ранг≤0.6": [("atr_rank", "<=", 0.6, "шорт")], "ранг≤0.8": [("atr_rank", "<=", 0.8, "шорт")], "не выстроены": [("stack", "<=", 0.0, "шорт")], "ADX≤25": [("adx14", "<=", 25.0, "шорт")], "ADX≤30": [("adx14", "<=", 30.0, "шорт")],
         "EMA50≤5%": [("d_ema50", "<=", 0.05, "шорт")], "EMA50≤10%": [("d_ema50", "<=", 0.10, "шорт")], "верх месяца": [("pos180", "<=", 0.0, "шорт")], "ER30≤0.2": [("er30", "<=", 0.2, "шорт")], "G≥1.5": [("d_G", ">=", 1.5, "шорт")], "G≥2": [("d_G", ">=", 2.0, "шорт")], "шортов нет": "off",
         "ранг≤0.6+не выстр": [("atr_rank", "<=", 0.6, "шорт"), ("stack", "<=", 0.0, "шорт")], "ранг≤0.6+G≥2": [("atr_rank", "<=", 0.6, "шорт"), ("d_G", ">=", 2.0, "шорт")], "не выстр+G≥2": [("stack", "<=", 0.0, "шорт"), ("d_G", ">=", 2.0, "шорт")]}
LONG = {"без": [], "ранг≤0.8": [("atr_rank", "<=", 0.8, "лонг")], "разброс≤3": [("w_GYR", "<=", 3.0, "лонг")], "импульс": [("ret180", ">=", 0.0, "лонг")]}
PAUSE = {"нет": 0, "12": 12}
SIZE = {"постоянный": None, "риск 0.25-3": (0.25, 3.0), "риск 0.5-2": (0.5, 2.0)}


def w_roll(S, lo, hi, n=100, days=365):
    key = ("wroll", lo, hi, n, days)
    if key not in S.cache:
        p = S.atr4(n) / S.h4["c"]
        med = pd.Series(p).rolling(days * 6, min_periods=500).median().shift(1).to_numpy()
        with np.errstate(invalid="ignore", divide="ignore"):
            w = np.clip(med / p, lo, hi)
        S.cache[key] = np.where(np.isfinite(w), w, 1.0)
    return S.cache[key]


def legs_z(S, sf, lf_, pause, size, norm=True):
    flt = list(lf_)
    kw = {}
    if sf == "off":
        kw["short"] = False
    else:
        flt += list(sf)
    if flt:
        kw["Lok"], kw["Sok"] = ls.masks(S, flt)
    if pause:
        kw["cool"] = pause
    if size:
        kw["w_fn"] = w_roll(S, *size)
    legs = lc.run(S, **kw)
    if size and norm and legs:
        m = float(np.mean([x[5] for x in legs]))
        legs = [(*x[:5], x[5] / m, *x[6:]) for x in legs]
    return legs


def grid():
    return list(itertools.product(SHORT, LONG, PAUSE, SIZE))


_S = {}


def _init(names):
    try:
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000)
    except Exception:
        pass
    for nm in names:
        _S[nm] = lc.load(nm)
        lf.feats(_S[nm])


def _one(a):
    k, (sn, ln, pn, zn) = a
    row = {"id": k, "шорт": sn, "лонг": ln, "пауза": pn, "размер": zn}
    daily = {}
    for nm, S in _S.items():
        legs = legs_z(S, SHORT[sn], LONG[ln], PAUSE[pn], SIZE[zn])
        for key, v in lc.stats(S, legs).items():
            row[f"{nm}_{key}"] = v
        if nm in ("BTC", "ETH", "XRP") and legs:
            daily[nm] = lc.daily_returns(S, legs).to_numpy(np.float32)
    return row, daily


def main():
    workers = int(next((a for i, a in enumerate(sys.argv) if sys.argv[i - 1] == "--workers"), 4))
    names = ["BTC", "ETH", "XRP", "Bitstamp"] + list(ld.COINS20)
    G = grid()
    print("вариантов", len(G), flush=True)
    t0 = time.time()
    rows, dd = [], {n: {} for n in ("BTC", "ETH", "XRP")}
    with ProcessPoolExecutor(max_workers=workers, initializer=_init, initargs=(names,)) as ex:
        for q, (row, daily) in enumerate(ex.map(_one, list(enumerate(G)), chunksize=4)):
            rows.append(row)
            for nm, arr in daily.items():
                dd[nm][row["id"]] = arr
            if q % 60 == 0:
                print(q, f"{time.time() - t0:.0f}с", flush=True)
    d = pd.DataFrame(rows)
    d.to_csv(OUT / "fam_z.csv", index=False)
    for nm in dd:
        L = max(len(a) for a in dd[nm].values())
        M = np.zeros((len(G), L), dtype=np.float32)
        for k, a in dd[nm].items():
            M[k, -len(a):] = a
        np.save(OUT / f"fam_z_daily_{nm}.npy", M)
    print("готово", f"{time.time() - t0:.0f}с", flush=True)


if __name__ == "__main__":
    main()
