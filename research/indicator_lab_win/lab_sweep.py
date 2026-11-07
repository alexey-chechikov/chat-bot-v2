"""Перебор по PREREG_win.md (W4, G2, W2): каждый вариант считается полным потоком на рядах отбора. Процессы с пониженным приоритетом.
Запуск: python -X utf8 lab_sweep.py [--ser BTC,ETH,XRP] [--workers 4]"""
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
import lab_feat as lf

OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)
GL, YL, RL, BL = lc.G, lc.Y, lc.R, lc.B


def T_(n):
    return ("T", n)


def E_(n):
    return ("E", n)


def variants():
    V = [("база", "база R", {}), ("база", "база G", {"lx": GL}), ("база", "только лонг", {"short": False})]
    # А. лонг
    for le, lx, kl, kx, b in itertools.product((30, 50, 75, 100), (50, 100, 150, 200, 300), (1, 2, 3), (1, 2, 3), (100, 150, 200, 300, 400)):
        V.append(("А", f"лонг T{le}/T{lx} k{kl}/{kx} B{b}", dict(le=T_(le), lx=T_(lx), k_le=kl, k_lx=kx, reg=E_(b))))
    # Б. шорт
    for se, sx, ks, kx, b in itertools.product((30, 50, 75, 100), (30, 50, 75, 100), (1, 2, 3), (1, 2, 3), (100, 150, 200, 300, 400)):
        V.append(("Б", f"шорт T{se}/T{sx} k{ks}/{kx} B{b}", dict(se=T_(se), sx=T_(sx), k_se=ks, k_sx=kx, reg=E_(b))))
    # В. выходы
    sides = ((0, "обе"), (1, "лонг"), (-1, "шорт"))
    for n, x, mode, (sd, sn) in itertools.product((8, 12, 16, 24, 36, 48, 72), (0, 0.5, 1, 1.5, 2), ("peak", "cur"), sides):
        V.append(("В-время", f"время {n}ч {mode}<{x} {sn}", dict(t_n=n, t_x=x, t_mode=mode, t_side=sd)))
    for x in (1, 1.5, 2, 3, 4):
        V.append(("В-безубыток", f"безубыток {x}", dict(be=float(x))))
    for x, on, (sd, sn) in itertools.product((2, 3, 4, 5, 6, 8), (0, 2, 3, 4, 6), sides):
        V.append(("В-плавающий", f"плавающий {x} от {on} {sn}", dict(trail=float(x), trail_on=float(on), trail_side=sd)))
    for w, ln in itertools.product((1 / 3, 0.5, 2 / 3), (("G", GL), ("Y", YL))):
        V.append(("В-части", f"часть {w:.2f} под {ln[0]}", dict(part=(ln[1], 2), part_w=w)))
    for w in (1 / 3, 0.5, 2 / 3):
        V.append(("В-части", f"шорт часть {w:.2f} над G, остаток над Y", dict(sx=YL, spart=(GL, 2), part_w=w)))
    for x in (6, 8, 10, 12, 16):
        V.append(("В-тейк", f"тейк {x}", dict(tp=float(x))))
    for x in (1.5, 2, 3, 4, 6):
        V.append(("В-стоп", f"стоп {x}", dict(stop=float(x))))
        V.append(("В-стоп", f"стоп шорта {x}", dict(sstop=float(x))))
    for sw, (nm, ln) in itertools.product((1, 2, 3, 4, 6), (("G", GL), ("Y", YL))):
        V.append(("В-перекл", f"лонг под {nm} до пика {sw}, дальше R", dict(lx0=ln, lx_sw=float(sw))))
    for sw, (nm, ln) in itertools.product((1, 2, 3, 4, 6), (("Y", YL), ("R", RL))):
        V.append(("В-перекл", f"шорт над G до пика {sw}, дальше {nm}", dict(sx=ln, sx0=GL, sx_sw=float(sw))))
    # Г. повторный вход
    for x in (1, 2, 3, 6, 12, 18, 30):
        V.append(("Г", f"пауза {x}", dict(cool=x)))
    V.append(("Г", "новый экстремум", dict(rebreak=True)))
    for x in (1, 2, 3, 6):
        V.append(("Г", f"пауза {x} и экстремум", dict(cool=x, rebreak=True)))
    for x in (0.5, 1, 2, 3):
        V.append(("Г", f"зазор синей {x} лонг", dict(band_l=float(x))))
        V.append(("Г", f"зазор синей {x} шорт", dict(band_s=float(x))))
        V.append(("Г", f"зазор синей {x} обе", dict(band_l=float(x), band_s=float(x))))
    # Д. фильтры
    grid = [("d_G", ">=", (0.25, 0.5, 0.75, 1, 1.5, 2)), ("d_G", "<=", (1, 2, 3, 4)), ("d_B", "<=", (2, 4, 6, 8, 10)), ("d_B", ">=", (0.5, 1, 2)), ("sl6_B", ">=", (0, 0.25, 0.5)), ("sl30_B", ">=", (-1, 0, 1, 2)), ("sl30_B", "<=", (2, 4, 6, 8)),
            ("sl6_G", ">=", (0, 0.5, 1)), ("sl1_G", ">=", (0,)), ("adx14", ">=", (15, 20, 25, 30)), ("adx14", "<=", (20, 25, 30, 40)), ("adx3", ">=", (20, 30, 40, 50)), ("di14", ">=", (0, 5, 10)), ("di3", ">=", (0, 10, 20)),
            ("er30", ">=", (0.1, 0.15, 0.2, 0.3)), ("er6", ">=", (0.2, 0.4, 0.6)), ("er90", ">=", (0.05, 0.1, 0.2)), ("xG30", "<=", (2, 3, 4, 6)), ("xG60", "<=", (3, 4, 6, 8, 10)), ("xG120", "<=", (6, 8, 10, 14)),
            ("pos180", ">=", (-0.25, 0, 0.25)), ("pos180", "<=", (0, 0.25, 0.4)), ("newhi30", ">=", (1,)), ("newhi90", ">=", (1,)), ("newhi180", ">=", (1,)), ("atr_rank", ">=", (0.2, 0.4, 0.6)), ("atr_rank", "<=", (0.4, 0.6, 0.8)),
            ("atr_ratio", ">=", (0.8, 1, 1.2)), ("atr_ratio", "<=", (1, 1.2, 1.5)), ("body", ">=", (0, 0.25, 0.5)), ("clv", ">=", (0, 0.1, 0.2)), ("rng_atr", ">=", (0.75, 1, 1.5)), ("vol30", ">=", (0.75, 1, 1.5, 2)),
            ("w_GYR", "<=", (2, 3, 5)), ("w_GYR", ">=", (1, 2)), ("w_GB", "<=", (2, 4, 6)), ("stack", ">=", (0, 1)), ("d_sma20", ">=", (0,)), ("d_sma50", ">=", (0,)), ("d_sma100", ">=", (0,)), ("d_sma200", ">=", (0,)),
            ("d_ema20", "<=", (0.02, 0.05, 0.1)), ("d_ema50", "<=", (0.05, 0.1, 0.2)), ("ret90", ">=", (0,)), ("ret180", ">=", (0,)), ("taker6", ">=", (0,)), ("fund", "<=", (0.01, 0.03, 0.05))]
    for f, op, ths in grid:
        for th, sd in itertools.product(ths, ("обе", "лонг", "шорт")):
            V.append(("Д", f"{f}{op}{th} {sd}", dict(flt=[(f, op, float(th), sd)])))
    # Е. 4ч и 1ч
    for (nm, ln), band, wait in itertools.product((("G", GL), ("Y", YL)), (0, 0.25, 0.5, 1), (4, 8, 12, 24)):
        V.append(("Е-откат", f"откат {nm}+{band} за {wait}ч", dict(entry="pull1", e_line=ln, e_band=float(band), e_wait=wait)))
    for (nm, ln), k, wait in itertools.product((("T50", T_(50)), ("T200", T_(200)), ("E200", E_(200))), (1, 2, 3), (4, 8, 12)):
        V.append(("Е-подтв", f"подтв 1ч {nm} k{k} за {wait}ч", dict(entry="conf1", e_conf=ln, e_k=k, e_wait=wait)))
    V.append(("Е-ранний", "вход до закрытия k2", dict(entry="early")))
    V.append(("Е-ранний", "вход до закрытия k3", dict(entry="early", k_le=3, k_se=3)))
    for (nm, ln), k, af in itertools.product((("T50", T_(50)), ("T100", T_(100)), ("T200", T_(200)), ("E200", E_(200))), (2, 3, 6), (None, 1, 2, 3, 4, 6)):
        V.append(("Е-выход1ч", f"выход 1ч {nm} k{k} после {af}", dict(x1=ln, x1_k=k, x1_after=None if af is None else float(af))))
    for (nm, ln), k in itertools.product((("G", GL), ("Y", YL)), (2, 3)):
        V.append(("Е-X01", f"X01 4ч под {nm} и 1ч T200 k{k}", dict(x1=T_(200), x1_k=k, x1_with4=ln)))
    # Ж. размер и ансамбль
    for (lo, hi), n in itertools.product(((0.5, 1.5), (0.25, 2), (0.25, 3)), (14, 100)):
        V.append(("Ж-размер", f"риск {lo}-{hi} ATR{n}", dict(vol=dict(lo=lo, hi=hi, n=n))))
    V.append(("Ж-ансамбль", "выход G,R", dict(ens=[dict(lx=GL), dict(lx=RL)])))
    V.append(("Ж-ансамбль", "выход G,Y,R", dict(ens=[dict(lx=GL), dict(lx=YL), dict(lx=RL)])))
    V.append(("Ж-ансамбль", "k1,2,3 на R", dict(ens=[dict(k_le=k, k_lx=k, k_se=k, k_sx=k) for k in (1, 2, 3)])))
    V.append(("Ж-ансамбль", "9 точек k×выход", dict(ens=[dict(k_le=k, k_lx=k, k_se=k, k_sx=k, lx=x) for k in (1, 2, 3) for x in (GL, YL, RL)])))
    V.append(("Ж-ансамбль", "вход T30,50,75", dict(ens=[dict(le=T_(n), se=T_(n), sx=T_(n)) for n in (30, 50, 75)])))
    V.append(("Ж-ансамбль", "синяя 100,200,300", dict(ens=[dict(reg=E_(n)) for n in (100, 200, 300)])))
    return V


CMP = {">=": np.greater_equal, "<=": np.less_equal}
CENTER = {"clv": 0.5, "pos180": 0.5, "pos30": 0.5, "pos90": 0.5, "taker6": 0.5}


def masks(S, flt):
    F = lf.feats(S)
    n = len(S.h4["c"])
    L, Sh = np.ones(n, bool), np.ones(n, bool)
    for f, op, th, sd in flt:
        if f.startswith("newhi"):
            vl, vs = F[f], F["newlo" + f[5:]]
        elif f in lf.SIGNED:
            vl, vs = F[f], -F[f]
        elif f in CENTER:
            vl, vs = F[f] - CENTER[f], CENTER[f] - F[f]
        else:
            vl = vs = F[f]
        with np.errstate(invalid="ignore"):
            cl, cs = CMP[op](vl, th) | ~np.isfinite(vl), CMP[op](vs, th) | ~np.isfinite(vs)
        if sd in ("обе", "лонг"):
            L &= cl
        if sd in ("обе", "шорт"):
            Sh &= cs
    return L, Sh


def vol_weights(S, lo, hi, n):
    A = S.atr4(n)
    p = A / S.h4["c"]
    med = pd.Series(p).expanding(min_periods=500).median().shift(1).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        w = np.clip(med / p, lo, hi)
    return np.where(np.isfinite(w), w, 1.0)


def legs_of(S, spec):
    spec = dict(spec)
    if "ens" in spec:
        out = []
        members = spec.pop("ens")
        for m in members:
            kw = {**spec, **m}
            for x in legs_of(S, kw):
                out.append((*x[:5], x[5] / len(members), *x[6:]))
        return out
    if "flt" in spec:
        spec["Lok"], spec["Sok"] = masks(S, spec.pop("flt"))
    if "vol" in spec:
        v = spec.pop("vol")
        spec["w_fn"] = vol_weights(S, v["lo"], v["hi"], v["n"])
        legs = lc.run(S, **spec)
        m = np.mean([x[5] for x in legs]) if legs else 1.0
        return [(*x[:5], x[5] / m, *x[6:]) for x in legs]
    return lc.run(S, **spec)


_S = {}


def _init(names):
    try:
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000)
    except Exception:
        pass
    for nm in names:
        _S[nm] = lc.load(nm)
        lf.feats(_S[nm])


def _one(args):
    k, fam, name, spec = args
    row = {"id": k, "семейство": fam, "вариант": name}
    daily = {}
    for nm, S in _S.items():
        legs = legs_of(S, spec)
        st = lc.stats(S, legs)
        for key, v in st.items():
            row[f"{nm}_{key}"] = v
        if legs:
            daily[nm] = lc.daily_returns(S, legs).to_numpy(np.float32)
    return row, daily


def main():
    names = next((a.split(",") for i, a in enumerate(sys.argv) if sys.argv[i - 1] == "--ser"), ["BTC", "ETH", "XRP"])
    workers = int(next((a for i, a in enumerate(sys.argv) if sys.argv[i - 1] == "--workers"), 4))
    V = variants()
    print("вариантов", len(V), "семейства", pd.Series([v[0] for v in V]).value_counts().to_dict(), flush=True)
    t0 = time.time()
    rows, dd = [], {nm: {} for nm in names}
    with ProcessPoolExecutor(max_workers=workers, initializer=_init, initargs=(names,)) as ex:
        for q, (row, daily) in enumerate(ex.map(_one, [(k, *v) for k, v in enumerate(V)], chunksize=12)):
            rows.append(row)
            for nm, arr in daily.items():
                dd[nm][row["id"]] = arr
            if q % 300 == 0:
                print(q, f"{time.time() - t0:.0f}с", flush=True)
    d = pd.DataFrame(rows)
    d["spec"] = [json.dumps({a: b for a, b in v[2].items()}, ensure_ascii=False, default=str) for v in V]
    tag = "_".join(names)
    d.to_csv(OUT / f"sweep_{tag}.csv", index=False)
    for nm in names:
        L = max(len(a) for a in dd[nm].values())
        M = np.zeros((len(V), L), dtype=np.float32)
        for k, a in dd[nm].items():
            M[k, -len(a):] = a
        np.save(OUT / f"sweep_daily_{nm}.npy", M)
    print("готово", len(d), f"{time.time() - t0:.0f}с", flush=True)


if __name__ == "__main__":
    main()
