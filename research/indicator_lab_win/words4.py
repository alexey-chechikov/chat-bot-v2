"""Автомат по запискам оператора 07.11 (семейство И в PREREG_win.md). Отдельный код, lab_core не меняется. Все выключатели выключены — ровно lab_core.run, это проверяется в main.

Основная сделка: как простое правило, линии входа и выхода настраиваются.
Противовес над синей (cs): шорт, цель синяя, отмена закреплением над линией. Лонг под синей (cl): цель синяя, отмена закреплением под линией.
От синей (fbl, fbs): вход на закрытии часа после касания синей, цель красная.
Неправильный порядок (tl): лонг, открытый при таком порядке, ведётся к красной или до выхода под зелёной.
Только закрытые бары: цели от значения линии на прошлом закрытом баре 4ч, по уровню или открытию часа. Вес сделки = вес размера × доля."""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import candidate as cd
import lab_core as lc

G, Y, R, B = lc.G, lc.Y, lc.R, lc.B
DEF = dict(k=2, le=G, se=G, lx=R, sx=G, lx_yg=False, sx_stack=None,
           cs=None, cs_w=0.5, cs_x=G, cs_k=None, cs_far=None, cs_ok=None, cl=None, cl_w=1.0, cl_x=Y, fbl=None, fbs=None, fb_tol=0.5, fbs_x=B,
           tl=None, tl_entry=False, tl_room=None, tl_k=None, wo="stack", tol=0.5, Lok=None, Sok=None, w_fn=None, clean_short=None)


def run(S, **kw):
    P = {**DEF, **kw}
    t, o, h, l, c, j, is4 = S.t, S.o, S.h, S.l, S.c, S.j, S.is4
    n = len(t)
    F = S.h4["c"]
    Gv, Yv, Rv, Bv = S.line4(G), S.line4(Y), S.line4(R), S.line4(B)
    rG, rY, rB = S.run4(G), S.run4(Y), S.run4(B)
    rle, rlx, rse, rsx = S.run4(P["le"]), S.run4(P["lx"]), S.run4(P["se"]), S.run4(P["sx"])
    rcs, rcl, rfs = S.run4(P["cs_x"]), S.run4(P["cl_x"]), S.run4(P["fbs_x"])
    rR = S.run4(R)
    jp_ = np.clip(np.searchsorted(S.h4["known"], t - 3600, side="right") - 1, 0, None)
    Bp, Rp = Bv[jp_], Rv[jp_]
    k = P["k"]
    cs_k = P["cs_k"] or k
    cs_far, cs_ok = P["cs_far"], P["cs_ok"]
    A4 = S.atr4()
    Lok, Sok, w_fn = P["Lok"], P["Sok"], P["w_fn"]
    cs, cl, fbl, fbs, tl, wo, tol, ftol = P["cs"], P["cl"], P["fbl"], P["fbs"], P["tl"], P["wo"], P["tol"] / 100, P["fb_tol"] / 100
    lx_yg, sx_stack, clean = P["lx_yg"], P["sx_stack"], P["clean_short"]
    tl_entry, tl_room, tl_k = P["tl_entry"], P["tl_room"], P["tl_k"] or P["k"]
    need_hour = bool(cs or cl or fbl or fbs or tl or tl_entry)
    idx = range(S.i0, n) if need_hour else S.pos4[S.pos4 >= S.i0].tolist()
    legs = []
    side, i_e, p_e, w_e, tag, tgt = 0, -1, 0.0, 1.0, "", None
    lock_up, armed_yg, last_fb = False, True, -10 ** 9

    def stack_up(q):
        return Gv[q] > Yv[q] > Rv[q]

    def stack_dn(q):
        return Gv[q] < Yv[q] < Rv[q]

    def look(q):
        z = max(q - 6, 0)
        return int(Gv[q] > Gv[z]) + int(Yv[q] > Yv[z]) + int(Rv[q] > Rv[z])

    def wrong(q):
        return Yv[q] < Rv[q] if wo == "y<r" else not stack_up(q)

    def close(i, px, why):
        nonlocal side, tag, tgt
        legs.append((i_e, i, p_e, float(px), side, w_e, tag, why))
        side, tag, tgt = 0, "", None

    def opn(i, s, tg, frac=1.0, target=None):
        nonlocal side, i_e, p_e, w_e, tag, tgt
        side, i_e, p_e, tag, tgt = s, i, float(c[i]), tg, target
        w_e = (float(w_fn[j[i]]) if w_fn is not None else 1.0) * frac

    for i in idx:
        jj = j[i]
        new4 = is4[i]
        just_long = False
        if side != 0 and tgt is not None:
            base = Bp[i] if tgt == "B" else Rp[i]
            if side == 1:
                lv = base * (1 - tol)
                if h[i] >= lv and p_e < lv:
                    if tag == "к красной":
                        lock_up = True
                    close(i, max(lv, o[i]), "цель")
                    if not new4:
                        continue
            else:
                lv = base * (1 + tol)
                if l[i] <= lv and p_e > lv:
                    close(i, min(lv, o[i]), "цель")
                    if not new4:
                        continue
        if new4:
            f = F[jj]
            if rG[jj] < 0:
                lock_up = False
            if Yv[jj] <= Gv[jj]:
                armed_yg = True
            if side == 1:
                if tag == "над синей":
                    if lx_yg:
                        ex = (Yv[jj] > Gv[jj] and rY[jj] <= -k) or rR[jj] <= -k
                    else:
                        ex = rlx[jj] <= -k
                    if ex:
                        close(i, c[i], "линия")
                        just_long = True
                elif tag in ("к красной", "неправильный, под G"):
                    if rG[jj] <= -k:
                        close(i, c[i], "под G")
                        just_long = True
                elif tag == "к синей":
                    if rcl[jj] <= -k:
                        close(i, c[i], "отмена")
                elif tag == "от синей":
                    if rB[jj] <= -k:
                        close(i, c[i], "под синей")
            elif side == -1:
                if tag == "под синей":
                    if sx_stack == "stack":
                        ex = stack_up(jj) and look(jj) == 3 and rG[jj] >= k
                    elif sx_stack == "stack_or_blue":
                        ex = rB[jj] >= k or (stack_up(jj) and look(jj) == 3 and rG[jj] >= k)
                    elif sx_stack == "y_or_stack":
                        ex = rY[jj] >= k or (stack_up(jj) and look(jj) == 3 and rG[jj] >= k)
                    else:
                        ex = rsx[jj] >= k
                    if ex:
                        close(i, c[i], "линия")
                elif tag == "противовес":
                    if rcs[jj] >= k:
                        close(i, c[i], "отмена")
                elif tag == "от синей":
                    if rfs[jj] >= k:
                        close(i, c[i], "отмена")
            if side == 0:
                if f > Bv[jj]:
                    go = rle[jj] >= k and rlx[jj] > -k and (Lok is None or Lok[jj]) and not lock_up
                    if lx_yg:
                        go = rle[jj] >= k and rR[jj] > -k and not (Yv[jj] > Gv[jj] and rY[jj] <= -k) and (Lok is None or Lok[jj]) and not lock_up
                    if go:
                        if tl and wrong(jj):
                            if tl == "red" and Rv[jj] > c[i]:
                                opn(i, 1, "к красной", 1.0, "R")
                            elif tl == "red+G":
                                opn(i, 1, "к красной", 1.0, "R" if Rv[jj] > c[i] else None)
                            elif tl == "G":
                                opn(i, 1, "неправильный, под G")
                            else:
                                opn(i, 1, "над синей")
                        else:
                            opn(i, 1, "над синей")
                    elif tl_entry and rG[jj] >= tl_k and rR[jj] <= -k and Rv[jj] > c[i] * (1 + tol) and (tl_room is None or Rv[jj] - c[i] >= tl_room * A4[jj]) and not lock_up and (Lok is None or Lok[jj]):
                        opn(i, 1, "к красной", 1.0, "R")
                    elif cs:
                        sig = (cs == "after_exit" and just_long) or \
                              (cs == "y_over_g" and Yv[jj] > Gv[jj] and rG[jj] <= -k and armed_yg) or \
                              (cs == "y_under_r" and Yv[jj] < Rv[jj] and look(jj) < 3 and rG[jj] == -k) or \
                              (cs == "under_y" and rY[jj] == -cs_k) or \
                              (cs == "under_y_exit" and (rY[jj] == -cs_k or just_long)) or \
                              (cs == "y_under_r_any" and rG[jj] == -cs_k) or \
                              (cs == "under_r" and rR[jj] == -k)
                        room = c[i] > Bv[jj] * (1 + tol) if cs_far is None else c[i] > Bv[jj] + cs_far * A4[jj]
                        if sig and room and (cs_ok is None or cs_ok[jj]):
                            opn(i, -1, "противовес", P["cs_w"], "B")
                            if cs == "y_over_g":
                                armed_yg = False
                else:
                    ok = rse[jj] <= -k and rsx[jj] < k and (Sok is None or Sok[jj])
                    if ok and clean == "only":
                        ok = stack_dn(jj) and look(jj) == 0
                    if ok and clean == "not":
                        ok = not (stack_dn(jj) and look(jj) == 0)
                    if ok:
                        opn(i, -1, "под синей")
                    elif cl:
                        sig = (cl == "over_y" and rY[jj] == k) or \
                              (cl == "over_g_down" and rG[jj] == k and look(jj) == 0) or \
                              (cl == "stack_up" and stack_up(jj) and look(jj) == 3 and rG[jj] >= k)
                        if sig and c[i] < Bv[jj] * (1 - tol):
                            opn(i, 1, "к синей", P["cl_w"], "B")
        if side == 0 and (fbl or fbs) and i - last_fb >= 24:
            f = F[jj]
            if fbl and f > Bv[jj] and (fbl == "all" or wrong(jj)):
                if l[i] <= Bp[i] * (1 + ftol) and c[i] > Bp[i] and Rp[i] > c[i] * (1 + tol):
                    opn(i, 1, "от синей", 1.0, "R")
                    last_fb = i
            elif fbs and f <= Bv[jj] and (fbs == "all" or not stack_up(jj)):
                if h[i] >= Bp[i] * (1 - ftol) and c[i] < Bp[i] and Rp[i] < c[i] * (1 - tol):
                    opn(i, -1, "от синей", 1.0, "R")
                    last_fb = i
    if side != 0:
        close(n - 1, c[n - 1], "конец")
    return legs


CS = dict(cs="under_y", cs_w=0.5, cs_x=Y)


def plus_layer(S):
    """Слой Простое+: вес от ATR100 с делителем 1.18, фильтр основного шорта ранг ≤ 0.6."""
    r = cd.atr_rank(S, 365, 100)
    with np.errstate(invalid="ignore"):
        ok = (r <= 0.6) | ~np.isfinite(r)
    return {"Sok": ok, "w_fn": cd.weights(S, 100, 365, 0.5, 2.0) / 1.18}


def frozen2(S):
    """Второй кандидат для резерва: Простое+ и шорт в противовес над синей. Параметры заморожены."""
    return run(S, **plus_layer(S), **CS)


def frozen3(S):
    """Разведка, решений по ней не принимать: второй кандидат и выход шорта над жёлтой."""
    return run(S, **plus_layer(S), **CS, sx=Y)


def main():
    for name in ("BTC", "ETH", "XRP", "Bitstamp"):
        S = lc.load(name)
        a = [x[:6] for x in lc.run(S)]
        b = [x[:6] for x in run(S)]
        print(name, "все выключатели выключены = lab_core.run:", a == b, len(a))
        assert a == b
        c1, c2 = cd.frozen(S), run(S, **plus_layer(S))
        same = [(x[0], x[1], x[4]) for x in c1] == [(x[0], x[1], x[4]) for x in c2] and np.allclose([x[5] for x in c1], [x[5] for x in c2])
        print(name, "слой Простое+ = candidate.frozen:", same, len(c1))
        assert same


if __name__ == "__main__":
    main()
