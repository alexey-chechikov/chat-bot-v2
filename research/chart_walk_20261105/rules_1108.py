"""PREREG_notes_1108.md: правила из записок оператора 08.11 на текущей системе BTC (копия services/btc_signals/engine.py с выключателями)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
import btc_lab as bl  # noqa: E402
import btc_next as bn  # noqa: E402
import plus as pl  # noqa: E402
import state_map as sm  # noqa: E402
from services.btc_signals import engine as en  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 30, "display.max_rows", 100)
TOL = 0.005
CUT = sm.T("2023-01-01")


def sim(a, lay, lx="R", lx_blue=False, l_stack=0, w_mixed=1.0, rank_th=en.RANK_TH, bounce=None, fbs=False, trail_l=None, trail_s=None):
    t, c, h, l, o, j = a["t"], a["c"], a["h"], a["l"], a["o"], a["j"]
    F, B, atr4, Bp = a["f_close"], a["f_B"], a["atr4"], a["B4p"]
    G, Y, R, stack = a["f_G"], a["f_Y"], a["f_R"], a["f_stack"]
    Rp = np.r_[R[0], R[:-1]]
    B1p = np.r_[np.nan, pd.Series(c).ewm(span=200, adjust=False).mean().to_numpy()[:-1]]
    rG0, rY0, rR0, rB0 = a["f_run_G"], a["f_run_Y"], a["f_run_R"], a["f_run_B"]
    rex0 = rY0 if lx == "Y" else rR0
    rk, W = lay
    n = len(t)
    new = np.r_[True, j[1:] != j[:-1]]
    legs, pos, last_fb = [], None, -10 ** 9

    def close(i, px, why):
        s, w, tg = pos["side"], pos["w"], pos["tag"]
        if tg in en.MAIN:
            legs.append((pos["i"], i, pos["entry"], float(px), s, tg, why, w * en.FIRST))
            if pos["add_i"] is not None:
                legs.append((pos["add_i"], i, pos["add_px"], float(px), s, tg + " добор", why, w * en.ADD))
        else:
            legs.append((pos["i"], i, pos["entry"], float(px), s, tg, why, w))

    def opn(i, s, tg, w):
        return {"side": s, "tag": tg, "entry": float(c[i]), "i": i, "w": float(W[i]) / en.DIV * w, "add_lv": float(c[i]) + s * en.X_ATR * float(atr4[i]), "add_i": None, "add_px": None,
                "atr": float(atr4[i]), "ext": float(c[i])}

    for i in range(int(a["i0"]), n):
        new4 = bool(new[i])
        rG, rY, rR, rB, rex = rG0[i], rY0[i], rR0[i], rB0[i], rex0[i]
        hit, px, why = False, 0.0, ""
        if pos and i > pos["i"]:
            pos["ext"] = max(pos["ext"], float(h[i])) if pos["side"] == 1 else min(pos["ext"], float(l[i]))
        if new4 and pos and pos["tag"] in en.MAIN:
            k = trail_l if pos["side"] == 1 else trail_s
            if k is not None and pos["side"] * (pos["ext"] - F[i]) > k * pos["atr"]:
                hit, px, why = True, float(c[i]), "откат"
        if pos and not hit:
            tg, e = pos["tag"], pos["entry"]
            if tg == en.CS:
                lv = float(Bp[i]) * (1 + TOL)
                if l[i] <= lv < e:
                    hit, px, why = True, min(lv, float(o[i])), "цель"
            elif tg == "отскок":
                lv = (float(Bp[i]) if bounce["target"] == "B4" else float(B1p[i])) * (1 - TOL)
                if h[i] >= lv > e:
                    hit, px, why = True, max(lv, float(o[i])), "цель"
            elif tg == "от синей":
                lv = float(Rp[i]) * (1 + TOL)
                if l[i] <= lv < e:
                    hit, px, why = True, min(lv, float(o[i])), "цель"
        if new4 and not hit and pos:
            tg = pos["tag"]
            if tg == "над синей" and (rex <= -2 or (lx_blue and rB <= -2)):
                hit, px, why = True, float(c[i]), "выход"
            elif tg == en.CS and rY >= 2:
                hit, px, why = True, float(c[i]), "отмена"
            elif tg == "под синей" and rG >= 2:
                hit, px, why = True, float(c[i]), "выход"
            elif tg == "отскок" and (rG <= -2 if bounce["cancel"] == "G" else rY <= -2):
                hit, px, why = True, float(c[i]), "отмена"
            elif tg == "от синей" and rB >= 2:
                hit, px, why = True, float(c[i]), "отмена"
        if pos and pos["tag"] in en.MAIN and not hit and pos["add_i"] is None:
            lv = pos["add_lv"]
            if (pos["side"] == 1 and h[i] >= lv) or (pos["side"] == -1 and l[i] <= lv):
                pos["add_i"] = i
                pos["add_px"] = max(lv, float(o[i])) if pos["side"] == 1 else min(lv, float(o[i]))
        if hit:
            close(i, px, why)
            pos = None
        if new4 and pos is None:
            mixed = w_mixed if stack[i] == 0 else 1.0
            if F[i] > B[i]:
                ok = l_stack == 0 or (stack[i] == 1 and (l_stack == 1 or (G[i] > G[max(i - 24, 0)] and Y[i] > Y[max(i - 24, 0)] and R[i] > R[max(i - 24, 0)])))
                if rG >= 2 and rex > -2 and ok:
                    pos = opn(i, 1, "над синей", mixed)
                elif rY == -2 and c[i] > B[i] * (1 + TOL):
                    pos = opn(i, -1, en.CS, 1.0)
            else:
                if rG <= -2 and (rank_th is None or not rk[i] > rank_th):
                    pos = opn(i, -1, "под синей", mixed)
                elif bounce and rG == 2 and c[i] < B[i] * (1 - TOL):
                    pos = opn(i, 1, "отскок", 1.0)
        if fbs and pos is None and i - last_fb >= 24 and F[i] <= B[i] and h[i] >= Bp[i] * (1 - TOL) and c[i] < Bp[i] and Rp[i] < c[i] * (1 - TOL):
            pos = opn(i, -1, "от синей", 1.0)
            last_fb = i
    if pos:
        close(n - 1, float(c[n - 1]), "конец")
    return legs


V = {
    "база": {},
    "V1 выход лонга под жёлтой": dict(lx="Y"),
    "V2 выход лонга под синей или красной": dict(lx_blue=True),
    "V3 лонг только G>Y>R": dict(l_stack=1),
    "V4 лонг G>Y>R и все вверх": dict(l_stack=2),
    "V5 линии путаются — вес ×0.5": dict(w_mixed=0.5),
    "V6 шорт без запрета по рангу": dict(rank_th=None),
    "V7 запрет шорта при ранге > 0.8": dict(rank_th=0.8),
    "V8 отскок, цель синяя 4ч, отмена под зелёной": dict(bounce={"target": "B4", "cancel": "G"}),
    "V9 отскок, отмена под жёлтой": dict(bounce={"target": "B4", "cancel": "Y"}),
    "V10 отскок, цель синяя 1ч": dict(bounce={"target": "B1", "cancel": "G"}),
    "V11 шорт от синей до красной": dict(fbs=True),
}


VB = {"база": {}, **{f"лонг: откат {k} ATR": dict(trail_l=k) for k in (3, 4, 5, 6)}, **{f"шорт: откат {k} ATR": dict(trail_s=k) for k in (3, 4, 5, 6)}}


def part(a, f, legs):
    r, w = pl.unit(f, legs)
    v = r * w
    t0 = a["t"][np.array([x[0] for x in legs])]
    return float(v[t0 < CUT].sum()), float(v[t0 >= CUT].sum())


def main():
    (a, f, lay), (b, fb, layb) = bl.load()
    ref = bn.pyramid(a, bl.run(a, lay, rules={"cs": 1.0}), 2, 2, 0.5, 0.5)
    mine = sim(a, lay)
    print("сверка базы с btc_lab: итог", pl.stats(a, f, ref)["итог"], "против", pl.stats(a, f, mine)["итог"], "сделок", len(ref), len(mine), flush=True)
    rows = []
    base = None
    for lab, kw in (VB if "B" in sys.argv[1:] else V).items():
        legs, lb = sim(a, lay, **kw), sim(b, layb, **kw)
        st, stb = pl.stats(a, f, legs), pl.stats(b, fb, lb)
        p1, p2 = part(a, f, legs)
        row = {"вариант": lab, "сделок": st["n"], "итог": st["итог"], "просадка": st["просадка"], "отн": st["отн"], "2018–22": round(p1, 1), "2023–26": round(p2, 1), "с 2025": st["с2025"], "Bitstamp": stb["итог"]}
        if base is None:
            base = row
        else:
            row["прошло"] = "да" if row["2018–22"] > base["2018–22"] and row["2023–26"] > base["2023–26"] and row["Bitstamp"] > base["Bitstamp"] else "нет"
        rows.append(row)
        print(row, flush=True)
    d = pd.DataFrame(rows)
    d.to_csv(Path(__file__).parent / "out" / "rules_1108.csv", index=False)
    print(d.to_string(index=False), flush=True)
    for lab in ("V8 отскок, цель синяя 4ч, отмена под зелёной", "V10 отскок, цель синяя 1ч", "V11 шорт от синей до красной"):
        legs = [x for x in sim(a, lay, **V[lab]) if x[5] in ("отскок", "от синей")]
        r, w = pl.unit(f, legs)
        print(lab, ": своих сделок", len(legs), "итог", round(float((r * w).sum()), 1), "в плюсе", round(float((r > 0).mean() * 100)), "%", flush=True)


if __name__ == "__main__":
    main()
