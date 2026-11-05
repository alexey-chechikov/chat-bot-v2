"""Правила оператора как автомат на закрытиях (черновик для разбора участков, потом — проверка на всей истории).

База (параметры по умолчанию) — ровно автомат участка 1 (segment1.py), сверка: tests в segment2.py печатает совпадение ног.
Опции из записки 2 (05.11): tol — цель «голубая 4ч» с допуском, % («отбитие от голубой на 93 400»);
blue_tp_r1 — шорт от голубой закрывается на касании красной 1ч («цель уже до красной на часе»);
long_hold — над обеими голубыми при G>Y>R цели нет, лонг держим («приоритет лонг, 3 цветные выстроились вверх»);
mirror_narrow — лонг от сужения над двумя голубыми (зеркало правила участка 1, моё);
knot — «кагал»: при ранге ширины ≤ knot_rank и цене внутри линий: "flat" — всё закрыть и ждать, "two" — две сетки;
выход — 4ч закрытие за всеми пятью линиями (G, Y, R, голубая 4ч, голубая 1ч), сторона по направлению выхода.
Мои опции участка 1: fast_long_exit — выход лонга на 3 закрытиях 1ч под красной; min_w3 — не перекладываться в узких TEMA.
Версия 2 (после участка 2, ещё НЕ проверена на новом участке):
cross_only=N — выход и перекладка по жёлтой 4ч только на свежем пересечении, не позже N свечей 4ч («пока не пробиваем и не закрепляемся»);
priority — над обеими голубыми при G>Y>R и цене над G+Y шорт закрывается и открывается лонг без цели, шорт там не открывается,
выход из такого лонга — в ноль; под голубой 4ч перекладка в шорт как раньше («пересекаем голубую — приоритет лонг»);
entry_under — шорт, если 4ч под зелёной, жёлтой и обеими голубыми и позиции нет («закрепляемся под голубой, держим»)."""
from __future__ import annotations

import numpy as np
import pandas as pd

DEF = dict(rank_max=0.15, far=True, far_g=-5.0, far_b=-10.0, far_r=None, near_g=-1.0, tol=0.0, fast_long_exit=False, min_w3=0.0,
           blue_tp_r1=False, long_hold=False, mirror_narrow=False, knot=None, knot_rank=0.30, cross_only=0, priority=False,
           entry_under=False)
SIDE = {"S": -1, "L": 1}


def prepare(h1: pd.DataFrame, h4: pd.DataFrame) -> dict:
    """Столбцы на каждый час: своё 1ч + последняя закрытая 4ч; prev — что было известно до начала этого часа."""
    for b in (h1, h4):
        lines = b[["G", "Y", "R"]]
        b["width3"] = (lines.max(axis=1) - lines.min(axis=1)) / b["close"] * 100
        b["stack"] = np.where((b["G"] > b["Y"]) & (b["Y"] > b["R"]), 1, np.where((b["G"] < b["Y"]) & (b["Y"] < b["R"]), -1, 0))
    k1, k4 = h1["known"].to_numpy(), h4["known"].to_numpy()
    j = np.clip(np.searchsorted(k4, k1, side="right") - 1, 0, None)
    jp = np.clip(np.searchsorted(k4, k1 - 3600, side="right") - 1, 0, None)
    a = {"t": k1, "o": h1["open"].to_numpy(), "h": h1["high"].to_numpy(), "l": h1["low"].to_numpy(), "c": h1["close"].to_numpy(),
         "run_R": h1["run_R"].to_numpy(), "R1p": np.r_[np.nan, h1["R"].to_numpy()[:-1]], "j": j, "B4p": h4["B"].to_numpy()[jp]}
    for col in ("close", "G", "Y", "R", "B", "B1", "d_G", "d_R", "d_B", "a_B", "run_Y", "width_rank", "width3", "stack"):
        a["f_" + col] = h4[col].to_numpy()[j]
    return a


def run(a: dict, t_from: int, t_to: int, **kw) -> list[dict]:
    """Ноги: side (L/S/B), tag, t0, t1, why_open, why_close, p0, p1, t_off. Время — закрытие бара, действие с него."""
    P = {**DEF, **kw}
    t = a["t"]
    idx = np.where((t > t_from) & (t <= t_to))[0]
    legs, cur, covered, await_blue, in_knot = [], None, False, False, False
    j_prev = -1

    def close(i, why, price):
        cur.update(t1=int(t[i]), why_close=why, p1=float(price))
        legs.append(dict(cur))

    def open_(i, side, tag, why, price):
        return dict(side=side, tag=tag, t0=int(t[i]), why_open=why, p0=float(price), t_off=None)

    for i in idx:
        j = a["j"][i]
        new4 = j != j_prev
        j_prev = j
        fc, fg, fy, fr, fb, fb1 = (a["f_" + n][i] for n in ("close", "G", "Y", "R", "B", "B1"))
        d_g, d_b, d_r = a["f_d_G"][i], a["f_d_B"][i], a["f_d_R"][i]
        c, hi, lo, op = a["c"][i], a["h"][i], a["l"][i], a["o"][i]
        under_g, over_gy, under_gy = fc < fg, fc > fg and fc > fy, fc < fg and fc < fy
        r_over, r_under = a["run_R"][i] >= 3, a["run_R"][i] <= -3
        wide = a["f_width3"][i] >= P["min_w3"]
        narrow = a["f_width_rank"][i] <= P["rank_max"]
        under_blues, over_blues = fc < fb and fc < fb1, fc > fb and fc > fb1
        over_all, under_all = fc > max(fg, fy, fr, fb, fb1), fc < min(fg, fy, fr, fb, fb1)

        if P["knot"]:
            if in_knot:
                if new4 and (over_all or under_all):
                    if cur is not None:
                        close(i, "выход из кагала", c)
                    cur = open_(i, "L" if over_all else "S", "breakout", "выход из кагала", c)
                    in_knot = covered = await_blue = False
                continue
            if new4 and a["f_width_rank"][i] <= P["knot_rank"] and not over_all and not under_all:
                if cur is not None:
                    close(i, "вход в кагал", c)
                cur = open_(i, "B", "knot", "кагал: две сетки", c) if P["knot"] == "two" else None
                in_knot, covered, await_blue = True, False, False
                continue

        n_cross = P["cross_only"]
        fresh_up = n_cross == 0 or a["f_run_Y"][i] <= n_cross
        fresh_dn = n_cross == 0 or a["f_run_Y"][i] >= -n_cross
        long_zone = P["priority"] and over_blues and a["f_stack"][i] == 1 and over_gy
        if long_zone and new4:
            if cur is not None and cur["side"] == "S":
                close(i, "приоритет лонг: над голубыми", c)
                cur = None
            if cur is None:
                cur = open_(i, "L", "над голубыми", "приоритет лонг: над голубыми, G>Y>R", c)
                covered = await_blue = False
                continue

        if cur is not None and cur["side"] == "L":
            hold = P["long_hold"] and over_blues and a["f_stack"][i] == 1
            target = a["B4p"][i] * (1 - P["tol"] / 100)
            if hold:
                cur["tag"] = "над голубыми"
            elif cur["tag"] != "над голубыми" and hi >= target and cur["p0"] < target:
                close(i, "цель: голубая 4ч", max(target, op))
                cur, await_blue = None, True
                continue
            if P["fast_long_exit"] and r_under:
                close(i, "1ч под R, 3 закрытия", c)
                cur = None
                continue
            if under_gy and r_under and wide and fresh_dn:
                close(i, "4ч под G+Y, 1ч под R", c)
                cur = open_(i, "S", "flip", "флип из лонга", c) if not (P["priority"] and fc > fb) else None
                continue
        elif cur is not None and cur["side"] == "S":
            is_blue = cur["tag"].startswith("blue")
            if P["blue_tp_r1"] and is_blue and lo <= a["R1p"][i] < cur["p0"]:
                close(i, "цель: красная 1ч", min(a["R1p"][i], op))
                cur, covered = None, True
                continue
            if cur["tag"] == "blue" and under_g:
                cur["tag"] = "blue>G"
            if cur["tag"] == "blue" and new4 and fc > fb:
                close(i, "стоп: 4ч над голубой", c)
                cur, await_blue = None, True
                continue
            far_hit = d_g <= P["far_g"] or (is_blue and d_b <= P["far_b"]) or (P["far_r"] is not None and d_r <= P["far_r"])
            if P["far"] and new4 and far_hit:
                close(i, f"далеко: d_G {d_g:.1f}%, d_R {d_r:.1f}%, d_B {d_b:.1f}%", c)
                cur, covered = None, True
                continue
            if cur["tag"] != "blue":
                if new4 and fc > fg and cur["t_off"] is None:
                    cur["t_off"] = int(t[i])
                if over_gy and r_over and wide and fresh_up:
                    close(i, "4ч над G+Y, 1ч над R", c)
                    cur = open_(i, "L", "flip", "флип из шорта", c)
                    continue
        if cur is None:
            if await_blue:
                if new4 and fc < fb:
                    cur, await_blue = open_(i, "S", "blue", "от голубой 4ч", c), False
                elif new4 and a["f_a_B"][i] > 1:
                    await_blue = False
            elif over_gy and r_over and a["f_run_Y"][i] <= 6 and t[i] > t[idx[0]] and wide:
                cur, covered = open_(i, "L", "fresh", "4ч над G+Y, 1ч над R", c), False
            elif covered and new4 and under_g and d_g > P["near_g"]:
                cur, covered = open_(i, "S", "reshort", f"возврат к зелёной: d_G {d_g:.2f}%", c), False
            elif covered and new4 and fc > fg:
                covered = False
            elif not covered and new4 and under_g and under_blues and narrow:
                cur = open_(i, "S", "narrow", f"сужение: ранг {a['f_width_rank'][i]:.2f}", c)
            elif P["entry_under"] and not covered and new4 and under_gy and under_blues:
                cur = open_(i, "S", "под всеми", "4ч под G+Y и голубыми", c)
            elif P["mirror_narrow"] and not covered and new4 and fc > fg and over_blues and narrow:
                cur = open_(i, "L", "narrow", f"сужение над голубыми: ранг {a['f_width_rank'][i]:.2f}", c)
    if cur is not None:
        close(idx[-1], "конец окна", a["c"][idx[-1]])
    return legs


def flips(h4: pd.DataFrame, t_from: int, t_to: int, col: str) -> list[dict]:
    """Контроль: 4ч над линией col — лонг, под ней — шорт, перекладка на каждом закрытии через линию."""
    s = h4[(h4["known"] > t_from) & (h4["known"] <= t_to)]
    legs, cur = [], None
    for _, f in s.iterrows():
        side = "L" if f["close"] > f[col] else "S"
        if cur is None or cur["side"] != side:
            if cur is not None:
                cur.update(t1=int(f["known"]), why_close=f"перекладка по {col}", p1=float(f["close"]))
                legs.append(cur)
            cur = dict(side=side, tag=col, t0=int(f["known"]), why_open=f"перекладка по {col}", p0=float(f["close"]), t_off=None)
    f = s.iloc[-1]
    cur.update(t1=int(f["known"]), why_close="конец окна", p1=float(f["close"]))
    legs.append(cur)
    return legs


def grid_legs(mk, legs: list[dict], utc) -> pd.DataFrame:
    """Сетка 0.6/1.4 на каждой ноге (gridk, ордер $100). Сторона B — две сетки, итог — сумма, потолок на сторону как у одной."""
    out = []
    for g in legs:
        i0, i1 = mk.idx([g["t0"]])[0], mk.idx([g["t1"]])[0]
        off = None if g["t_off"] is None else mk.idx([g["t_off"]])
        sides = (1, -1) if g["side"] == "B" else (SIDE[g["side"]],)
        rr = [mk.run(np.array([i0]), np.array([i1]), s, i_off=off)[0] for s in sides]
        tot = np.sum(rr, axis=0)
        move = 0.0 if g["side"] == "B" else (g["p1"] / g["p0"] - 1) * 100 * SIDE[g["side"]]
        out.append({"сторона": g["side"], "тип": g["tag"], "t0": g["t0"], "t1": g["t1"], "открыта": utc(g["t0"]), "закрыта": utc(g["t1"]),
                    "цена_вх": round(g["p0"]), "цена_вых": round(g["p1"]), "ход_%": round(move, 2), "сетка_$": round(float(tot[0]), 2),
                    "тейки_шт": int(tot[8]), "лотов_на_выходе": int(tot[9]), "мешок_$": round(float(tot[5]), 2),
                    "просадка_$": round(float(sum(r[6] for r in rr)), 2), "пик_номинал_$": round(float(sum(r[11] for r in rr))),
                    "почему_открыта": g["why_open"], "почему_закрыта": g["why_close"]})
    return pd.DataFrame(out)


def summary(tbl: pd.DataFrame) -> dict:
    if tbl.empty:
        return {"итог_$": 0.0, "просадка_от_пика_$": 0.0, "ног": 0, "шорт_$": 0.0, "лонг_$": 0.0, "две_$": 0.0}
    cum = tbl["сетка_$"].cumsum().to_numpy()
    before = np.r_[0.0, cum[:-1]]
    peak = np.maximum.accumulate(np.r_[0.0, cum])[:-1]
    dd = float((before + tbl["просадка_$"].to_numpy() - peak).min())
    part = lambda s: round(float(tbl.loc[tbl["сторона"] == s, "сетка_$"].sum()), 2)  # noqa: E731
    pos = tbl[tbl["сторона"] != "B"]
    return {"итог_$": round(float(cum[-1]), 2), "просадка_от_пика_$": round(dd, 2), "ног": len(tbl), "шорт_$": part("S"), "лонг_$": part("L"),
            "две_$": part("B"), "пик_номинал_$": int(tbl["пик_номинал_$"].max()),
            "позиция_$1000_$": round(float((pos["ход_%"] * 10 - 1.36).sum()), 1)}
