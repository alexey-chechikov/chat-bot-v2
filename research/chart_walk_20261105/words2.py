"""Автомат «слова» версия 2: записки 4–6 (окна 28.11.25–02.01.26, 09.06–21.07.26, 29.09–05.11.26), каждая правка выключателем. Все выключатели выключены — ровно words.run, это проверяется.
Каждая сделка: вход, цель, отмена. Флет — за скобками: сделки в нём помечаются и считаются отдельно, правил флета пока нет.

Выключатели:
  xl       лонг «к голубой» закрывается при закреплении 4ч под зелёной (2 закрытия) и 3 закрытиях 1ч под красной, жёлтая не нужна;
  sflip    шорт после такого выхода: цель красная 4ч с запасом, отмена — 2 закрытия над зелёной, если она над жёлтой, иначе над жёлтой; достигли цели — ждём сетап;
  sblue    шорт от голубой: красная ниже входа — цель красная и отмена над жёлтой; красная выше входа — отмена 2 закрытия над красной;
  above    лонг над голубыми после сильного роста (зелёная выше жёлтой и красной минимум на above ATR) закрывается как xl, шорт с целью голубая 1ч;
  long_red после выхода лонга по xl следующий лонг «к голубой» только после касания красной 4ч;
  xs_r     шорт под голубой при красной выше входа закрывается над красной 4ч, а не над G+Y и 1ч R;
  x01_all  подтверждённый оператором выход на лонгах «над голубыми» и «снова над жёлтой»: add — вместе с прежними выходами, only — вместо них;
  s_stop, s_tp  стоп и тейк шорта в ATR 4ч от входа, s_after=covered — после них нужен новый возврат к зелёной, none — обычные входы;
  l_stop   аварийный стоп лонга в ATR 4ч от входа;
  no_passed не открывать лонг «к голубой», если цена уже у цели;
  lab      для контроля: готовая метка часов разрешает шорты вместо описания, gate="lab"."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import ledger as lg  # noqa: E402
import pos  # noqa: E402
import words as wd  # noqa: E402

pd.set_option("display.width", 260, "display.max_columns", 40, "display.max_rows", 300)
DEF2 = {**wd.DEF, "xl": False, "sflip": False, "sblue": False, "above": None, "long_red": False, "xs_r": False, "tol_r": 0.5, "gate": None, "slope_d": 5, "x01_all": None, "s_stop": None, "s_tp": None, "s_after": "none", "lab": None, "l_stop": None, "stop_at": None, "out": None, "no_passed": False}
MAIN = {"gate": "shorts"}  # вариант A из PREREG_portrait.md: прошёл вторую проверку; выходы записок 4–6 (xl, sflip, sblue) её не прошли. Оператор 05.11: лонги вне описания предварительно половиной объёма, half_long.py
OFF = {}
MAIN26 = {**MAIN, "s_stop": 2.0, "s_tp": 6.0, "s_after": "covered"}  # настройки индикатора по умолчанию: вариант A и шорт 2/6 ATR, gpt_r3_sweep.py
SHORT_TGT = ("к красной", "к голубой 1ч")
DAY = 24


def in_portrait(a, i, s, slope_d=5):
    """Прибыльный вход в его словах. Лонг: над обеими голубыми, голубая 4ч растёт за 5 дней. Шорт: цветные смешаны, либо цветные вверх, цена под обеими голубыми, голубая падает."""
    fc, g, y, r, b, b1 = a["f_close"][i], a["f_G"][i], a["f_Y"][i], a["f_R"][i], a["f_B"][i], a["f_B1"][i]
    rising = b > a["f_B"][max(i - slope_d * DAY, 0)]
    if s == 1:
        return bool(fc > b and fc > b1 and rising)
    up, down = g > y > r, g < y < r
    if not up and not down:
        return True
    return bool(up and fc < b and fc < b1 and not rising)


def allow(a, i, s, tag, mode, slope_d=5):
    """Что открывать в режиме портрета. portrait — только описание; portrait+l1 — плюс лонг к голубой, кроме G<Y<R; portrait+s1 — плюс шорт к красной; full — и то и другое.
    against — открываем всё, кроме входа против всей картины: лонг при G<Y<R и падающей голубой 4ч; шорт при растущей голубой 4ч и выстроенных цветных.
    shorts — лонги все, шорты только в описании и шорт к красной под голубой 4ч (блок лонгов провалился на новых монетах: +287, плюс на 7 из 10)."""
    if mode == "shorts":
        if s == 1:
            return True
        return in_portrait(a, i, -1, slope_d) or (tag == "к красной" and bool(a["f_close"][i] < a["f_B"][i]))
    if mode == "against":
        g, y, r = a["f_G"][i], a["f_Y"][i], a["f_R"][i]
        rising = a["f_B"][i] > a["f_B"][max(i - slope_d * DAY, 0)]
        if s == 1:
            return not (g < y < r and not rising)
        return not (rising and (g > y > r or g < y < r))
    if in_portrait(a, i, s, slope_d):
        return True
    if mode in ("portrait+l1", "full") and s == 1 and tag == "к голубой":
        return not (a["f_G"][i] < a["f_Y"][i] < a["f_R"][i])
    if mode in ("portrait+s1", "full") and s == -1 and tag == "к красной":
        return bool(a["f_close"][i] < a["f_B"][i])
    return False
# Записки 4–6: (закрытие UTC, действие, слова). Точное время — по событиям линий marks2_events_*.csv; там, где он назвал только день, допуск шире
MARKS2 = [("2025-11-29 08:00", "xL", "4ч под зелёной, 1ч под красной"), ("2025-11-29 08:00", "S", "шорт при тех же условиях, цель красная"), ("2025-12-01 03:00", "xS", "цель красная 4ч"),
          ("2025-12-02 17:00", "L", "1ч вышли над голубой, цель голубая 4ч"), ("2025-12-05 00:00", "xL", "4ч под зелёной, 1ч под красной"),
          ("2026-06-11 08:00", "xS", "закрепились над красной 4ч"), ("2026-06-11 08:00", "L", "над красной 4ч, лонг"), ("2026-06-16 20:00", "xL", "первое закрепление под зелёной, 1ч под красной"), ("2026-06-16 20:00", "S", "шорт, цель красная"),
          ("2026-07-01 20:00", "L", "закрепились над 59, лонг"), ("2026-07-05 23:00", "xL", "цель голубая 4ч"),
          ("2026-09-23 12:00", "S", "под зелёной и 1ч под красной, цель голубая 1ч"), ("2026-10-29 16:00", "S", "шорт от голубой 29.10"), ("2026-11-04 12:00", "xS", "закрепились над красной"), ("2026-11-04 17:00", "S", "шорт от голубой 04.11")]


def run(a, **kw):
    P = {**DEF2, **kw}
    t, c, h, l, o, j = a["t"], a["c"], a["h"], a["l"], a["o"], a["j"]
    legs, cur, covered, await_blue, jp, wait_red, need_red = [], None, False, False, -1, False, False
    Rp = np.r_[a["f_R"][0], a["f_R"][:-1]]
    B1p = np.r_[a["B1h"][0], a["B1h"][:-1]]

    def close(i, px, why):
        legs.append((cur[0], i, cur[1], float(px), cur[2], cur[3], why))

    def opn(i, s, tag, tgt=None):
        if P["no_passed"] and s == 1 and tag == "к голубой" and c[i] >= a["f_B"][i] * (1 - P["tol"] / 100):
            return None                                 # цель уже пройдена к сигналу: сделки к ней нет
        if P["gate"] == "lab":
            if s == -1 and not P["lab"][i]:
                return None
        elif P["gate"] is not None and not allow(a, i, s, tag, P["gate"], P["slope_d"]):
            return None
        return [i, float(c[i]), s, tag, tgt]

    for i in range(a["i0"], len(t)):
        if P["stop_at"] is not None and i > P["stop_at"]:
            break
        new4 = j[i] != jp
        jp = j[i]
        fc, g, y, r, b, b1 = a["f_close"][i], a["f_G"][i], a["f_Y"][i], a["f_R"][i], a["f_B"][i], a["f_B1"][i]
        over_gy, under_gy = fc > g and fc > y, fc < g and fc < y
        r_over, r_under = a["run_R"][i] >= P["k1"], a["run_R"][i] <= -P["k1"]
        over_bl, under_bl = fc > b and fc > b1, fc < b and fc < b1
        d_g, d_b = a["f_d_G"][i], a["f_d_B"][i]
        ry, rr, rg = a["f_run_Y"][i], a["f_run_R"][i], a["f_run_G"][i]
        if need_red and (l[i] <= Rp[i] * (1 + P["tol_r"] / 100) or fc > b):
            need_red = False
        g_under = rg <= -P["k4"] and r_under
        if cur is not None and cur[2] == 1:
            tag = cur[3]
            if P["l_stop"] is not None:
                lv = cur[1] - P["l_stop"] * a["atr4"][cur[0]]
                if l[i] <= lv:
                    close(i, min(lv, o[i]), "стоп ATR")
                    cur = None
                    continue
            if tag == "к голубой":
                lvl = a["B4p"][i] * (1 - P["tol"] / 100)
                if h[i] >= lvl and cur[1] < lvl:
                    close(i, max(lvl, o[i]), "цель")
                    cur, await_blue = None, True
                    continue
                if (g_under if P["xl"] else (under_gy and r_under)):
                    close(i, c[i], "под G, 1ч под R" if P["xl"] else "под G+Y, 1ч под R")
                    if P["long_red"] and P["xl"] and c[i] > Rp[i]:
                        need_red = True
                    if P["sflip"] and Rp[i] < c[i]:
                        cur = opn(i, -1, "к красной", "R")
                    else:
                        cur = opn(i, -1, "перекладка")
                    continue
            elif tag in ("над голубыми", "снова над жёлтой"):
                if P["above"] is not None and g_under and cur[4] == "strong":
                    close(i, c[i], "после роста: под G, 1ч под R")
                    cur = opn(i, -1, "к голубой 1ч", "B1") if B1p[i] < c[i] else None
                    continue
                if P["x01_all"] and g_under:
                    close(i, c[i], "X01: под G, 1ч под R")
                    cur = None
                    continue
                if P["x01_all"] == "only":
                    pass
                elif tag == "над голубыми" and new4 and ry <= -P["k4"]:
                    close(i, c[i], "2 закрытия под жёлтой")
                    cur = None
                elif tag == "снова над жёлтой" and new4 and rr <= -P["k4"]:
                    close(i, c[i], "2 закрытия под красной")
                    cur = None
                elif P["above"] is not None and cur is not None and cur[4] != "strong" and (g - y) >= P["above"] * a["atr4"][i] and (g - r) >= P["above"] * a["atr4"][i]:
                    cur[4] = "strong"
        elif cur is not None:
            tag = cur[3]
            if P["s_stop"] is not None:
                atr0 = a["atr4"][cur[0]]
                up, dn = cur[1] + P["s_stop"] * atr0, cur[1] - P["s_tp"] * atr0
                if h[i] >= up or l[i] <= dn:                    # оба в одном часе — порядок неизвестен, считаем стоп
                    if h[i] >= up:
                        close(i, max(up, o[i]), "стоп ATR")
                    else:
                        close(i, min(dn, o[i]), "тейк ATR")
                    cur, covered = None, P["s_after"] == "covered"
                    continue
            if tag in SHORT_TGT or (tag.startswith("от голубой") and cur[4] == "R"):
                lvl = (B1p[i] if cur[4] == "B1" else Rp[i]) * (1 + P["tol_r"] / 100)
                if l[i] <= lvl < cur[1]:
                    close(i, min(lvl, o[i]), "цель")
                    cur, wait_red = None, True
                    continue
                # «закрепление над зелёной, если она над жёлтой, иначе над жёлтой» = 2 закрытия над обеими. От голубой вход бывает уже над жёлтой, поэтому отмена — событие: второе закрытие над ней после возврата под неё
                stop = (rg >= P["k4"] and ry >= P["k4"]) if tag in SHORT_TGT else ry == P["k4"]
                if new4 and stop:
                    close(i, c[i], "отмена")
                    cur, wait_red = None, tag in SHORT_TGT
                    continue
            if tag.startswith("от голубой") and P["sblue"] and cur[4] == "над красной" and new4 and rr >= P["k4"]:
                close(i, c[i], "над красной")
                cur = None
                continue
            if tag == "от голубой" and new4 and fc > b:
                close(i, c[i], "стоп над голубой")
                cur, await_blue = None, True
                continue
            if tag == "от голубой" and fc < g and not P["sblue"]:
                cur[3] = tag = "от голубой, под зелёной"
            if (tag.startswith("от голубой") or tag in SHORT_TGT) and new4 and (d_g <= P["far_g"] or d_b <= P["far_b"]):
                close(i, c[i], "далеко")
                cur, covered = None, True
                continue
            if tag in ("под голубой", "перекладка", "снова шорт", "от голубой, под зелёной", "под красной"):
                if new4 and d_g <= P["far_g"]:
                    close(i, c[i], "далеко")
                    cur, covered = None, True
                    continue
                if P["xs_r"] and r > y:
                    if new4 and rr >= P["k4"]:
                        close(i, c[i], "над красной 4ч")
                        cur = opn(i, 1, "к голубой" if fc < b else "над голубыми")
                        continue
                elif over_gy and r_over:
                    close(i, c[i], "над G+Y, 1ч над R")
                    cur = opn(i, 1, "к голубой" if fc < b else "над голубыми")
                    continue
            if tag == "над голубыми" and new4 and rg >= 1 and a["run_B1"][i] >= P["k1"]:
                close(i, c[i], "над зелёной и голубой 1ч")
                cur = None
        if cur is not None:
            continue
        if await_blue:
            if new4 and fc < b:
                if P["sblue"]:
                    cur = opn(i, -1, "от голубой", "R" if Rp[i] < c[i] else "над красной")
                else:
                    cur = opn(i, -1, "от голубой")
                await_blue = False
                continue
            if new4 and (a["f_a_B"][i] > 1 or (over_bl and a["f_stack"][i] == 1 and over_gy)):
                await_blue = False
            else:
                continue
        if fc < b:
            if over_gy and r_over and not need_red:
                cur, covered, wait_red = opn(i, 1, "к голубой"), False, False
            elif wait_red:
                if new4 and rr == -P["k4"]:
                    cur, wait_red = opn(i, -1, "под красной"), False
            elif new4 and covered and fc < g and d_g > P["near_g"]:
                cur, covered = opn(i, -1, "снова шорт"), False
            elif new4 and covered and fc > g:
                covered = False
            elif new4 and not covered and under_gy and under_bl:
                cur = opn(i, -1, "под голубой")
        elif new4 and ry == 1 and over_bl:
            cur, wait_red = opn(i, 1, "снова над жёлтой"), False
        elif new4 and over_bl and a["f_stack"][i] == 1 and over_gy:
            cur, wait_red = opn(i, 1, "над голубыми"), False
        elif new4 and (rr == -P["k4"] if P["event_short"] else rr <= -P["k4"]):
            cur, wait_red = opn(i, -1, "над голубыми"), False
    if P["out"] is not None:
        P["out"].update(cur=cur, covered=covered, await_blue=await_blue, wait_red=wait_red, need_red=need_red)
    if cur is not None and P["stop_at"] is None:
        close(len(t) - 1, c[-1], "конец")
    return legs


def net(fm, x):
    m, f, u = lg.trade_cash(fm, x[:5])
    return (m - f - u) / lg.NOTIONAL * 100


def periods(a, fm, legs):
    """До 2025 — данные, которых записки 4–6 не видели; 2025–26 — окна, из которых записки взяты."""
    t = a["t"]
    d = pd.DataFrame([{"t0": t[x[0]], "s": x[4], "r": net(fm, x)} for x in legs])
    cut = cw.T("2025-01-01")
    return {"n": len(d), "итог": round(d["r"].sum()), "лонг": round(d.loc[d["s"] == 1, "r"].sum()), "шорт": round(d.loc[d["s"] == -1, "r"].sum()), "до_2025": round(d.loc[d["t0"] < cut, "r"].sum()), "2025–26": round(d.loc[d["t0"] >= cut, "r"].sum())}


def recall2(a, legs, tol_h=12):
    t = a["t"]
    rows = []
    for ts, act, word in MARKS2:
        x = cw.T(ts)
        side = 1 if act[-1] == "L" else -1
        cand = [(t[le[1] if act.startswith("x") else le[0]], le) for le in legs if le[4] == side]
        best = min(cand, key=lambda z: abs(z[0] - x))
        dh = (best[0] - x) / 3600
        rows.append({"время": ts[2:], "действие": act, "оператор": word, "автомат_ч": round(float(dh), 1), "тип": best[1][5], "совпало": abs(dh) <= tol_h})
    return pd.DataFrame(rows)
