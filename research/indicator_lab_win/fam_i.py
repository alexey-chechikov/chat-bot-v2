"""Семейство И из PREREG_win.md: записки оператора 07.11. Каждый вариант на двух слоях: постоянный размер и Простое+. Запуск: python -X utf8 fam_i.py [--workers 4]"""
from __future__ import annotations

import ctypes
import itertools
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

import lab_core as lc
import lab_data as ld
import lab_sweep as ls
import words4 as w4

OUT = Path(__file__).parent / "out"
G, Y, R, B = lc.G, lc.Y, lc.R, lc.B


def variants():
    V = [("база", "база", {})]
    V += [("И1", "выход лонга под жёлтой", dict(lx=Y)), ("И1", "выход лонга под зелёной", dict(lx=G)), ("И1", "выход под жёлтой только при Y>G", dict(lx_yg=True))]
    V += [("И2", "выход шорта над жёлтой", dict(sx=Y)), ("И2", "выход шорта при построении вверх", dict(sx_stack="stack")), ("И2", "выход шорта над жёлтой или построение", dict(sx_stack="y_or_stack"))]
    for tr, w, x in itertools.product(("after_exit", "y_over_g", "y_under_r", "under_y", "under_r"), (0.5, 1.0), (("G", G), ("Y", Y))):
        V.append(("И3", f"противовес {tr} w{w} отмена {x[0]}", dict(cs=tr, cs_w=w, cs_x=x[1])))
    for tr, w, x in itertools.product(("over_y", "over_g_down", "stack_up"), (0.5, 1.0), (("G", G), ("Y", Y))):
        V.append(("И4", f"лонг к синей {tr} w{w} отмена {x[0]}", dict(cl=tr, cl_w=w, cl_x=x[1])))
    for m, tol in itertools.product(("wrong", "all"), (0.25, 0.5, 1.0)):
        V.append(("И5", f"лонг от синей {m} допуск {tol}", dict(fbl=m, fb_tol=tol)))
    for m, tol, x in itertools.product(("wrong", "all"), (0.25, 0.5, 1.0), (("B", B), ("Y", Y))):
        V.append(("И5", f"шорт от синей {m} допуск {tol} отмена {x[0]}", dict(fbs=m, fb_tol=tol, fbs_x=x[1])))
    for wo, tl in itertools.product(("stack", "y<r"), ("red", "G", "red+G")):
        V.append(("И6", f"неправильный порядок {wo}: {tl}", dict(wo=wo, tl=tl)))
    V.append(("И6", "вход над зелёной под красной, цель красная", dict(tl_entry=True)))
    for k in (1, 2, 3):
        ax = dict(k=k, le=Y, se=Y, lx=Y, sx=Y)
        V.append(("И7", f"ось жёлтая k{k}", ax))
        for w in (0.5, 1.0):
            V.append(("И7", f"ось жёлтая k{k} + лонг к синей w{w}", {**ax, "cl": "over_y", "cl_w": w, "cl_x": Y}))
            V.append(("И7", f"ось жёлтая k{k} + шорт к синей w{w}", {**ax, "cs": "under_y", "cs_w": w, "cs_x": Y}))
            V.append(("И7", f"ось жёлтая k{k} + оба w{w}", {**ax, "cl": "over_y", "cl_w": w, "cl_x": Y, "cs": "under_y", "cs_w": w, "cs_x": Y}))
    V.append(("И9", "только чистый шорт", dict(clean_short="only")))
    V.append(("И9", "шорт кроме чистого", dict(clean_short="not")))
    full = dict(lx_yg=True, sx=Y, cs="under_y", cs_w=0.5, cs_x=Y, cl="over_y", cl_w=1.0, cl_x=Y, fbl="wrong", fbs="wrong", tl_entry=True)
    V.append(("И10", "всё вместе словами оператора", dict(full)))
    for lab, drop in (("без выхода под жёлтой", ["lx_yg"]), ("без выхода шорта над жёлтой", ["sx"]), ("без противовеса", ["cs", "cs_w", "cs_x"]), ("без лонга к синей", ["cl", "cl_w", "cl_x"]), ("без лонга от синей", ["fbl"]), ("без шорта от синей", ["fbs"]), ("без входа к красной", ["tl_entry"])):
        V.append(("И10", f"всё кроме: {lab}", {a: b for a, b in full.items() if a not in drop}))
    # И8: постоянная позиция по синей
    for k in (2, 3, 6, 12):
        V.append(("И8", f"лонг и шорт по синей k{k}", dict(_blue=dict(k=k, both=True, n=0, sx="B"))))
    for n, sx in itertools.product((0, 1, 2, 3, 5, 7, 10, 14, 21, 30, 45, 60), ("B", "Y", "R")):
        V.append(("И8", f"шорт после {n}д под синей, выход над {sx}", dict(_blue=dict(k=2, both=False, n=n, sx=sx))))
    for n, cond in itertools.product((3, 7, 14, 21, 30), ("slope", "notup", "slope+notup")):
        V.append(("И8", f"шорт после {n}д под синей, {cond}", dict(_blue=dict(k=2, both=False, n=n, sx="B", cond=cond))))
    for n in (7, 10, 14, 21, 30, 45):
        V.append(("И8", f"основной шорт только первые {n}д под синей", dict(_cap=n)))
    for room, k in itertools.product((0.5, 1.0, 1.5, 2.0, 3.0), (1, 2)):
        V.append(("И11", f"к красной: запас от {room} ATR, закрытий над зелёной {k}", dict(tl_entry=True, tl_room=room, tl_k=k)))
    V.append(("И11", "выход шорта при построении вверх или над синей", dict(sx_stack="stack_or_blue")))
    V.append(("И11", "выход шорта над красной", dict(sx=R)))
    return V


def blue_kw(S, b):
    rB = S.run4(B)
    n4 = b["n"] * 6
    F_ = S.line4(B)
    sl = F_ - np.r_[np.full(30, np.nan), F_[:-30]]
    Gv, Yv, Rv = S.line4(G), S.line4(Y), S.line4(R)
    ok = rB <= -max(n4, b["k"])
    c = b.get("cond")
    if c in ("slope", "slope+notup"):
        ok = ok & (sl < 0)
    if c in ("notup", "slope+notup"):
        ok = ok & ~((Gv > Yv) & (Yv > Rv))
    kw = dict(se=B, sx={"B": B, "Y": Y, "R": R}[b["sx"]], Sok=ok, k=b["k"])
    if b["both"]:
        kw.update(le=B, lx=B)
    return kw


def legs_of(S, spec, layer):
    spec = dict(spec)
    if "_blue" in spec:
        spec.update(blue_kw(S, spec.pop("_blue")))
    if "_cap" in spec:
        spec["Sok"] = S.run4(B) > -spec.pop("_cap") * 6
    if layer == "плюс":
        pl = w4.plus_layer(S)
        spec["w_fn"] = pl["w_fn"]
        spec["Sok"] = pl["Sok"] if "Sok" not in spec else (spec["Sok"] & pl["Sok"])
    return w4.run(S, **spec)


_S = {}


def _init(names):
    try:
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000)
    except Exception:
        pass
    for nm in names:
        _S[nm] = lc.load(nm)


def _one(a):
    k, fam, name, spec, layer = a
    row = {"id": k, "семейство": fam, "вариант": name, "слой": layer}
    daily = {}
    for nm, S in _S.items():
        legs = legs_of(S, spec, layer)
        for key, v in lc.stats(S, legs).items():
            row[f"{nm}_{key}"] = v
        if nm in ("BTC", "ETH", "XRP") and legs:
            daily[nm] = lc.daily_returns(S, legs).to_numpy(np.float32)
    return row, daily


def run_table(V, names, workers, tag):
    jobs = [(k, a[0], a[1], a[2], lay) for k, ((a), lay) in enumerate(itertools.product(V, ("постоянный", "плюс")))]
    print("вариантов", len(V), "прогонов на ряд", len(jobs), "рядов", len(names), flush=True)
    t0 = time.time()
    rows, dd = [], {n: {} for n in ("BTC", "ETH", "XRP")}
    with ProcessPoolExecutor(max_workers=workers, initializer=_init, initargs=(names,)) as ex:
        for q, (row, daily) in enumerate(ex.map(_one, jobs, chunksize=4)):
            rows.append(row)
            for nm, arr in daily.items():
                dd[nm][row["id"]] = arr
            if q % 100 == 0:
                print(q, f"{time.time() - t0:.0f}с", flush=True)
    d = pd.DataFrame(rows)
    d.to_csv(OUT / f"{tag}.csv", index=False)
    for nm in dd:
        L = max(len(a) for a in dd[nm].values())
        M = np.zeros((len(jobs), L), dtype=np.float32)
        for k, a in dd[nm].items():
            M[k, -len(a):] = a
        np.save(OUT / f"{tag}_daily_{nm}.npy", M)
    print("готово", f"{time.time() - t0:.0f}с", flush=True)


def main():
    workers = int(next((a for i, a in enumerate(sys.argv) if sys.argv[i - 1] == "--workers"), 4))
    run_table(variants(), ["BTC", "ETH", "XRP", "Bitstamp"], workers, "fam_i")


if __name__ == "__main__":
    main()
