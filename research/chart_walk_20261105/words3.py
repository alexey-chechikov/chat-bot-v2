"""Автомат «слова» версия 3: записки 06.11 по окнам, размеченным вслепую (BTC: 14.10–25.11.24 и декабрь, 30.12.24–17.02.25, 04.08–22.09.25, 12.01–23.02.26, 23.02–06.04.26). Отдельный код, words2 не меняется. Каждая мысль — выключатель, сделки не выбрасываются.

Ядро (записки 23.02, 30.12, 14.10):
  лонг: над синей 4ч, закрепление над зелёной (k закрытий 4ч), цветные выстроены G>Y>R и все три растут за сутки;
  выход лонга: закрепление под зелёной (l_exit="G"), вариант: пока под зелёной не добираем, закрепление под жёлтой закрываем (l_exit="Y");
  шорт: под синей 4ч, закрепление под зелёной, цветные G<Y<R и все три падают за сутки (s_align; 23.02 без этого условия, 04.08 с ним);
  выход шорта: закрепление над зелёной.
Добавки:
  l_counter  12.01: цветные смотрят вниз, но закрепились над зелёной, лонг под синей, цель район синей; отмена — закрепление под жёлтой; шорт опять при закреплении ниже синей или жёлтой;
  s_up       12.01 и 14.10: шорт над синей при закреплении под красной ("R") или жёлтой ("Y"), цель синяя 4ч или 1ч, отмена — закрепление над зелёной, после цели закрепление под синей — перезаход;
  s_up_w     14.10: такой шорт половиной объёма, приоритет лонговый;
  far, part  12.01: фиксация части или всего лонга при отрыве far ATR над зелёной, снова в лонг у зелёной;
  add        04.08: добор одним лотом в районе зелёной после отрыва add_far ATR над ней; закрылись под зелёной — не добираем до следующего отрыва;
  max_blue   не из записок, замер where_lose3.py: вход только не дальше max_blue ATR от синей;
  stop       не из записок, замер where_lose3.py: стоп stop ATR 4ч от входа, снова в ту же сторону только после закрытия 4ч за зелёной в обратную.
Сделка: (i0, i1, p0, p1, сторона, тип, причина, вес). Всё на закрытых барах, цель и стоп — по уровню или открытию часа."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import ledger as lg  # noqa: E402
import state_map as sm  # noqa: E402
import words2 as w2  # noqa: E402

pd.set_option("display.width", 260, "display.max_columns", 40, "display.max_rows", 300)
DEF3 = dict(k=2, l_exit="G", l_align=True, s_align=True, s_core=True, l_counter=False, s_up=None, s_up_tgt="B4", s_up_w=1.0, far=None, part=1.0, add=False, add_far=3.0, band=0.25, tol=0.5, slope_h=24, max_blue=None, stop=None)
CUT = cw.T("2025-01-01")
# Его точки по запискам 06.11: (день UTC, действие, слова). Он назвал дни, не часы, допуск в recall шире
MARKS3 = [("2024-10-28", "L", "28 октября лонг"), ("2024-10-31", "xL", "держим до 31 октября"), ("2024-11-01", "S", "шорт примерно на 70"), ("2024-11-05", "L", "лонг от синей или над зелёной 5 ноября"), ("2024-11-15", "xL", "закрыл бы 15 ноября"),
          ("2025-01-02", "L", "над синей и зелёной, со 2-го"), ("2025-01-07", "xL", "лонг до 7-го"), ("2025-01-07", "S", "шорт 07"), ("2025-01-13", "xS", "шорт по 13"), ("2025-01-14", "L", "лонг с 14"), ("2025-01-19", "xL", "лонг до 19"), ("2025-02-01", "S", "шорт с 1 февраля"), ("2025-02-27", "xS", "отмены не вижу до 27"),
          ("2025-08-04", "L", "цветные вверх, над зелёной"), ("2025-08-07", "L", "лонг 115 тысяч"), ("2025-08-18", "S", "шорт 18 августа"), ("2025-08-22", "xS", "шорт до 22"), ("2025-08-24", "S", "перезаход 24"),
          ("2026-01-15", "xL", "лонг кончился 15 января")]


def run(a, **kw):
    P = {**DEF3, **kw}
    t, c, h, l, o, j = a["t"], a["c"], a["h"], a["l"], a["o"], a["j"]
    G, Y, R, B, B1, atr, F = a["f_G"], a["f_Y"], a["f_R"], a["f_B"], a["f_B1"], a["atr4"], a["f_close"]
    Bp, B1p = a["B4p"], np.r_[a["B1h"][0], a["B1h"][:-1]]
    rG, rY, rR, rB = a["f_run_G"], a["f_run_Y"], a["f_run_R"], a["f_run_B"]
    k, tol, sh = P["k"], P["tol"], P["slope_h"]
    runs = {"G": rG, "Y": rY, "R": rR}
    rex = runs[P["l_exit"]]
    legs, lots, side, tag, jp = [], [], 0, "", -1
    armed, wait_green, re_short, tgt, blk = False, False, False, None, 0

    def close_all(i, px, why):
        nonlocal lots, side, tag
        for i0, p0, w in lots:
            legs.append((i0, i, p0, float(px), side, tag, why, w))
        lots, side, tag = [], 0, ""

    def opn(i, s, tg, w=1.0):
        nonlocal lots, side, tag
        lots, side, tag = [[i, float(c[i]), w]], s, tg

    for i in range(a["i0"], len(t)):
        new4 = j[i] != jp
        jp = j[i]
        fc, g, y, r, b = F[i], G[i], Y[i], R[i], B[i]
        z = max(i - sh, 0)
        st_up, st_dn = g > y > r, g < y < r
        look_up, look_dn = g > G[z] and y > Y[z] and r > R[z], g < G[z] and y < Y[z] and r < R[z]
        l_ok = not P["l_align"] or (st_up if P["l_align"] == "stack" else st_up and look_up)
        s_ok = not P["s_align"] or (st_dn if P["s_align"] == "stack" else st_dn and look_dn)
        rg = rG[i]
        if blk * rg < 0:
            blk = 0
        if P["stop"] is not None and side != 0:
            lvs = lots[0][1] - side * P["stop"] * atr[lots[0][0]]
            if (side == 1 and l[i] <= lvs) or (side == -1 and h[i] >= lvs):
                blk = side
                close_all(i, min(lvs, o[i]) if side == 1 else max(lvs, o[i]), "стоп ATR")
                tgt = None
                continue
        if side == 1:
            lv_far = g + P["far"] * atr[i] if P["far"] is not None else None
            if tag == "к синей":
                lvl = Bp[i] * (1 - tol / 100)
                if h[i] >= lvl and lots[0][1] < lvl:
                    close_all(i, max(lvl, o[i]), "цель")
                    re_short = True
                    continue
                if new4 and rY[i] <= -k:
                    close_all(i, c[i], "под жёлтой")
                    re_short = True
            else:
                if lv_far is not None and h[i] >= lv_far and lots[0][1] < lv_far and not wait_green:
                    px = max(lv_far, o[i])
                    for lot in lots:
                        legs.append((lot[0], i, lot[1], float(px), 1, tag, "отрыв", lot[2] * P["part"]))
                        lot[2] *= 1 - P["part"]
                    wait_green = True
                    if P["part"] >= 1:
                        lots, side, tag = [], 0, ""
                        continue
                if P["add"] and h[i] >= g + P["add_far"] * atr[i]:
                    armed = True
                if new4 and rex[i] <= -k:
                    close_all(i, c[i], "под " + P["l_exit"])
                    armed = False
                elif (armed or wait_green) and c[i] < g:
                    armed, wait_green = False, False
                elif (armed or wait_green) and l[i] <= g + P["band"] * atr[i]:
                    if wait_green:
                        lots.append([i, float(c[i]), P["part"]])
                        wait_green = False
                    elif armed:
                        lots.append([i, float(c[i]), 1.0])
                    armed = False
        elif side == -1:
            if tgt is not None:
                lvl = (B1p[i] if tgt == "B1" else Bp[i]) * (1 + tol / 100)
                if l[i] <= lvl < lots[0][1]:
                    close_all(i, min(lvl, o[i]), "цель")
                    tgt, re_short = None, True
                    continue
            if new4 and rg >= k:
                close_all(i, c[i], "над G")
                tgt = None
        if side == 0 and wait_green:
            if c[i] < g:
                wait_green = False
            elif l[i] <= g + P["band"] * atr[i] and fc > b:
                opn(i, 1, "над синей")
                wait_green = False
                continue
        if side != 0 or not new4:
            continue
        near = P["max_blue"] is None or abs(fc - b) <= P["max_blue"] * atr[i]
        if fc > b:
            re_short = False
            if rg >= k and l_ok and not wait_green and rex[i] > -k and near and blk != 1:
                opn(i, 1, "над синей")
            elif P["s_up"] and runs[P["s_up"]][i] == -k:
                opn(i, -1, "от " + P["s_up"], P["s_up_w"])
                tgt = P["s_up_tgt"]
        else:
            if re_short and (rY[i] <= -k or rB[i] == -k) and fc < g:
                opn(i, -1, "перезаход")
                re_short = False
            elif P["s_core"] and rg <= -k and s_ok and near and blk != -1:
                opn(i, -1, "под синей")
                re_short = False
            elif P["l_counter"] and rg == k:
                opn(i, 1, "к синей")
                re_short = False
    if side != 0:
        close_all(len(t) - 1, c[-1], "конец")
    return legs


def stats(a, fm, legs, b=None):
    """Итог в % от номинала одной сделки с весом лота, просадка по часам на кривой всех лотов."""
    t = a["t"]
    if not legs:
        return {"n": 0, "итог": 0.0, "лонг": 0.0, "шорт": 0.0, "до_2025": 0.0, "с2025": 0.0, "просадка": 0.0}
    w = np.array([x[7] if len(x) > 7 else 1.0 for x in legs])
    r = np.array([w2.net(fm, x) for x in legs]) * w
    s = np.array([x[4] for x in legs])
    t0 = t[np.array([x[0] for x in legs])]
    eq, worst = np.zeros(len(t)), np.zeros(len(t))
    for wv in np.unique(w):
        if wv > 0:
            e, wo, _, _ = lg.equity(a, fm, [x[:5] for x, q in zip(legs, w) if q == wv])
            eq += e * wv
            worst += wo * wv
    b = a["i0"] if b is None else b
    return {"n": len(r), "итог": round(float(r.sum()), 1), "лонг": round(float(r[s == 1].sum()), 1), "шорт": round(float(r[s == -1].sum()), 1), "до_2025": round(float(r[t0 < CUT].sum()), 1), "с2025": round(float(r[t0 >= CUT].sum()), 1), "просадка": round(lg.drawdown(eq[b:], worst[b:], t[b:])[0] / lg.NOTIONAL * 100, 1)}


def recall(a, legs, tol_h=36):
    t = a["t"]
    rows = []
    for day, act, word in MARKS3:
        x = cw.T(day) + 12 * 3600
        side = 1 if act[-1] == "L" else -1
        cand = [(t[le[1] if act.startswith("x") else le[0]], le) for le in legs if le[4] == side]
        best = min(cand, key=lambda z: abs(z[0] - x))
        dh = (best[0] - x) / 3600
        rows.append({"день": day, "действие": act, "оператор": word, "автомат": sm.utc(best[0]), "разница_ч": round(float(dh)), "совпало": abs(dh) <= tol_h, "тип": best[1][5], "причина": best[1][6]})
    return pd.DataFrame(rows)
