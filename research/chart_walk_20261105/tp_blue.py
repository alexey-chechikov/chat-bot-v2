"""A. Сколько не хватало до голубой 4ч, тейки и стопы для лонга к голубой (и шорта к ней сверху). Правила — PREREG_positions.md."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import pos  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 40, "display.max_rows", 300)
YS = [5, 3, 2, 1.5, 1, 0.75, 0.5, 0.25, 0, -0.5, -1]
FR = [0.5, 0.75, 0.9, 1.0]
LIM = 30 * 24
ROOM = 1.0


def make_arrays(a, side):
    """Приводим к лонгу: side=−1 — зеркало цен (шорт к голубой сверху считается как лонг на 1/цена)."""
    if side == 1:
        return {k: a[k] for k in ("o", "h", "l", "c", "B4p")} | {"brk": (a["f_close"] < a["f_G"]) & (a["f_close"] < a["f_Y"]) & (a["run_R"] <= -3)}
    return {"o": 1 / a["o"], "h": 1 / a["l"], "l": 1 / a["h"], "c": 1 / a["c"], "B4p": 1 / a["B4p"],
            "brk": (a["f_close"] > a["f_G"]) & (a["f_close"] > a["f_Y"]) & (a["run_R"] >= 3)}


def events(a, side, kind, x):
    """Первое событие и следующее — только после конца прошлого ХОДА (brk или 30 дней), а не сделки: при стопе S2 или S3 прошлая сделка может быть ещё открыта.
    Сделки могут перекрываться, BTC до 3, ETH до 5. С одной позицией — ledger.trades_b(single=True). x — столбцы make_arrays."""
    room = (x["B4p"] / x["c"] - 1) * 100
    if side == 1:
        if kind == "L1":
            cond = (a["f_close"] > a["f_G"]) & (a["f_close"] > a["f_Y"]) & (a["f_run_Y"] >= 1) & (a["f_run_Y"] <= 6) & (a["run_R"] >= 3)
        else:
            cond = (a["c"] > a["B1h"]) & (a["f_close"] > a["f_Y"])
    else:
        if kind == "L1":
            cond = (a["f_close"] < a["f_G"]) & (a["f_close"] < a["f_Y"]) & (a["f_run_Y"] <= -1) & (a["f_run_Y"] >= -6) & (a["run_R"] <= -3)
        else:
            cond = (a["c"] < a["B1h"]) & (a["f_close"] < a["f_Y"])
    cond = cond & (room >= ROOM)
    cand = np.where(cond & (np.arange(len(cond)) >= a["i0"]))[0]
    brk = x["brk"]
    ev = []
    last_end = -1
    n = len(cond)
    for i in cand:
        if i <= last_end:
            continue
        w = brk[i + 1:min(i + 1 + LIM, n)]
        k = int(np.argmax(w)) if w.any() else len(w) - 1
        end = i + 1 + k
        ev.append(i)
        last_end = end
    return np.array(ev)


def run_one(x, a, i, side):
    """Ход от входа i до конца: максимум, дошла ли до голубой, недолёт."""
    n = len(x["c"])
    w_end = min(i + 1 + LIM, n)
    brk = x["brk"][i + 1:w_end]
    k = int(np.argmax(brk)) if brk.any() else len(brk) - 1
    e = i + 1 + k
    hi = x["h"][i + 1:e + 1]
    blue = x["B4p"][i + 1:e + 1]
    entry = x["c"][i]
    gap = (blue / hi - 1) * 100                                       # + не хватает, − перелёт
    j = int(np.argmax(hi))
    closest = float(gap.min())
    d0 = (x["B4p"][i] / entry - 1) * 100
    return {"i": i, "e": e, "вход": float(entry), "путь_%": float(d0), "недолёт_%": closest, "доля_пути": float((hi.max() - entry) / (x["B4p"][i] - entry)),
            "часов_до_макс": j + 1, "минус_до_конца_%": float((x["l"][i + 1:e + 1].min() / entry - 1) * 100), "ход_конец_%": float((x["c"][e] / entry - 1) * 100),
            "atr_%": float(a["atr4"][i] / a["c"][i] * 100), "до_макс_низ_%": float((x["l"][i + 1:i + 2 + j].min() / entry - 1) * 100)}


def hist_row(u: np.ndarray) -> dict:
    return {f"≤{y}": round(float((u <= y).mean() * 100), 1) for y in YS}


def outcomes(a, x, starts, side, stop):
    """Для каждого входа: результат каждого тейка при данном стопе. → dict имя → массив %. Издержки и фандинг учтены."""
    n = len(x["c"])
    names = ["без_тейка"] + [f"y{y}" for y in YS] + [f"f{f}" for f in FR]
    out = {k: np.full(len(starts), np.nan) for k in names}
    atr = a["atr4"]
    fund = a["F"]
    lo4 = None
    for q, i in enumerate(starts):
        e_lim = min(i + 1 + LIM, n)
        entry = x["c"][i]
        h, l, o, c, b = x["h"][i + 1:e_lim], x["l"][i + 1:e_lim], x["o"][i + 1:e_lim], x["c"][i + 1:e_lim], x["B4p"][i + 1:e_lim]
        if len(h) == 0:
            continue
        if stop == "S0":
            st_i = int(np.argmax(x["brk"][i + 1:e_lim])) if x["brk"][i + 1:e_lim].any() else len(h) - 1
            st_px = c[st_i]
        else:
            if stop == "S1":
                lvl = entry * (1 - 1.5 * atr[i] / a["c"][i])
            elif stop == "S2":
                lvl = entry * (1 - 3.0 * atr[i] / a["c"][i])
            else:
                lvl = x["l"][max(i - 23, 0):i + 1].min() * (1 - 0.25 * atr[i] / a["c"][i])
            hit = l <= lvl
            if hit.any():
                st_i = int(np.argmax(hit))
                st_px = min(lvl, o[st_i])
            else:
                st_i, st_px = len(h) - 1, c[-1]

        def res(idx, px):
            # цены шорта зеркальные (1/цена): entry/px = p1/p0, поэтому доход шорта 1 − p1/p0
            ret = (px / entry - 1) * 100 if side == 1 else (1 - entry / px) * 100
            f0, f1 = fund[i], fund[i + 1 + idx]
            return ret - pos.COST - side * (f1 - f0)

        out["без_тейка"][q] = res(st_i, st_px)
        for y in YS:
            lv = b * (1 - y / 100)
            if lv[0] <= entry * 1.002:                                # тейк ниже входа — такой сделки нет
                continue
            ok = h[:st_i + 1] >= lv[:st_i + 1]
            if ok.any():
                t_i = int(np.argmax(ok))
                if t_i < st_i or (t_i == st_i and stop == "S0"):
                    px = max(lv[t_i], o[t_i])
                    out[f"y{y}"][q] = res(t_i, px)
                    continue
            out[f"y{y}"][q] = res(st_i, st_px)
        path = x["B4p"][i] - entry
        for f in FR:
            lv = entry + f * path
            ok = h[:st_i + 1] >= lv
            if ok.any():
                t_i = int(np.argmax(ok))
                if t_i < st_i or (t_i == st_i and stop == "S0"):
                    out[f"f{f}"][q] = res(t_i, max(lv, o[t_i]))
                    continue
            out[f"f{f}"][q] = res(st_i, st_px)
    return out


def main():
    a, h1, h4, d1, fund = pos.load()
    t = a["t"]
    res = {}
    rows_tp = []
    for side, sname in ((1, "лонг"), (-1, "шорт")):
        x = make_arrays(a, side)
        room = (x["B4p"] / x["c"] - 1) * 100
        for kind in ("L1", "L2"):
            ev = events(a, side, kind, x)
            rr = pd.DataFrame([run_one(x, a, i, side) for i in ev])
            per = pos.period_of(t[ev])
            rr["период"] = per
            rr["t"] = [pos.utc_full(t[i]) for i in ev]
            rr.to_csv(pos.OUT / f"tp_blue_runs_{sname}_{kind}.csv", index=False)
            u = rr["недолёт_%"].to_numpy()
            u_a = u / rr["atr_%"].to_numpy()
            miss = u[u > 0]
            head = {"сторона": sname, "событие": kind, "n": len(rr), "путь_медиана_%": round(float(rr["путь_%"].median()), 2), "дошли_%": round(float((u <= 0).mean() * 100), 1),
                    "недолёт_медиана_%": round(float(np.median(miss)), 2), "недолёт_q25_%": round(float(np.quantile(miss, .25)), 2), "недолёт_q75_%": round(float(np.quantile(miss, .75)), 2),
                    "недолёт_в_ATR_медиана": round(float(np.median(u_a[u > 0])), 2), "доля_пути_медиана_недолёт": round(float(rr.loc[u > 0, "доля_пути"].median()), 2)}
            print(head)
            print("дошла не дальше чем за y% до голубой (доля, %):", hist_row(u))
            bins = [0, .25, .5, 1, 1.5, 2, 3, 5, 8, 100]
            h, _ = np.histogram(miss, bins=bins)
            print("гистограмма недолёта, %:", {f"{bins[i]}–{bins[i+1]}": int(h[i]) for i in range(len(h))})
            print("по периодам дошли:", {p: (int((per == p).sum()), round(float((u[per == p] <= 0).mean() * 100), 1) if (per == p).any() else None) for p in pos.PER})
            res[f"{sname}_{kind}"] = {"голова": head, "доля_по_y": hist_row(u), "гист": {f"{bins[i]}–{bins[i+1]}": int(h[i]) for i in range(len(h))}}
            # тейки и стопы, контроль: случайный вход в том же периоде с тем же запасом до голубой
            pool_all = np.where((room >= ROOM) & (np.arange(len(room)) >= a["i0"]))[0]
            rng = np.random.default_rng(20261105)
            pool_s = rng.choice(pool_all, size=min(6000, len(pool_all)), replace=False)
            pool_s.sort()
            pp = pos.period_of(t[pool_s])
            for stop in ("S0", "S1", "S2", "S3"):
                real = outcomes(a, x, ev, side, stop)
                ctrl = outcomes(a, x, pool_s, side, stop)
                for nm, v in real.items():
                    ok = ~np.isnan(v)
                    if ok.sum() < 20:
                        continue
                    row = {"сторона": sname, "событие": kind, "стоп": stop, "тейк": nm, **{k: pos.stats(v[ok])[k] for k in ("n", "среднее_%", "медиана_%", "плюс_%", "сумма_%", "худшая_%", "ди_низ", "ди_верх")},
                           "просадка_%": pos.max_dd(v[ok])}
                    # по периодам и контроль
                    c = ctrl[nm]
                    tot_ctl = np.zeros(999)
                    tot_real = 0.0
                    for p in pos.PER:
                        vp = v[ok & (per == p)]
                        row[f"{p}_сумма"] = round(float(vp.sum()), 1)
                        row[f"{p}_n"] = len(vp)
                        cp = c[(pp == p) & ~np.isnan(c)]
                        if len(vp) and len(cp):
                            tot_ctl += cp[rng.integers(0, len(cp), size=(999, len(vp)))].sum(axis=1)
                            tot_real += vp.sum()
                    row["лучше_случайного_%"] = round(float((tot_ctl < tot_real).mean() * 100), 1)
                    row["случайные_медиана_%"] = round(float(np.median(tot_ctl)), 1)
                    rows_tp.append(row)
    tp = pd.DataFrame(rows_tp)
    tp.to_csv(pos.OUT / "tp_blue_table.csv", index=False)
    show = ["сторона", "событие", "стоп", "тейк", "n", "среднее_%", "плюс_%", "сумма_%", "просадка_%", "худшая_%", "A_сумма", "B_сумма", "C_сумма", "ди_низ", "лучше_случайного_%", "случайные_медиана_%"]
    print(tp[(tp["сторона"] == "лонг")][show].to_string(index=False))
    print(tp[(tp["сторона"] == "шорт") & (tp["стоп"].isin(["S0", "S2"]))][show].to_string(index=False))
    (pos.OUT / "tp_blue.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    # все максимумы зигзага относительно голубой и ложных линий
    zig_density(h4)


def zigzag(hi, lo, th):
    """Точки разворота по максимумам и минимумам: (индекс, тип +1 максимум / −1 минимум)."""
    piv, d, ext_i = [], 0, 0
    ext_h, ext_l = hi[0], lo[0]
    for i in range(1, len(hi)):
        if d == 0:
            ext_h, ext_l = max(ext_h, hi[i]), min(ext_l, lo[i])
            if hi[i] / ext_l - 1 >= th:
                d = 1
                piv.append((int(np.argmin(lo[:i + 1])), -1))
                ext_h, ext_i = hi[i], i
            elif 1 - lo[i] / ext_h >= th:
                d = -1
                piv.append((int(np.argmax(hi[:i + 1])), 1))
                ext_l, ext_i = lo[i], i
            continue
        if d == 1:
            if hi[i] >= ext_h:
                ext_h, ext_i = hi[i], i
            elif 1 - lo[i] / ext_h >= th:
                piv.append((ext_i, 1))
                d, ext_l, ext_i = -1, lo[i], i
        else:
            if lo[i] <= ext_l:
                ext_l, ext_i = lo[i], i
            elif hi[i] / ext_l - 1 >= th:
                piv.append((ext_i, -1))
                d, ext_h, ext_i = 1, hi[i], i
    return piv


def zig_density(h4):
    b = h4[h4.index >= cw.T("2018-01-01")]
    hi, lo, B = b["high"].to_numpy(), b["low"].to_numpy(), b["B"].to_numpy()
    piv = zigzag(hi, lo, 0.05)
    highs = np.array([i for i, k in piv if k == 1])
    lows = np.array([i for i, k in piv if k == -1])
    bins = np.arange(-10, 10.5, 1.0)
    d_h = (hi[highs] / B[highs] - 1) * 100
    d_l = (lo[lows] / B[lows] - 1) * 100
    hh, _ = np.histogram(d_h, bins=bins)
    hl, _ = np.histogram(d_l, bins=bins)
    print("зигзаг 5%: максимумов", len(highs), "минимумов", len(lows))
    print("максимумы относительно голубой 4ч, %:", {f"{bins[i]:+.0f}…{bins[i+1]:+.0f}": int(hh[i]) for i in range(len(hh))})
    print("минимумы относительно голубой 4ч, %:", {f"{bins[i]:+.0f}…{bins[i+1]:+.0f}": int(hl[i]) for i in range(len(hl))})
    # максимумы в полосе ±w% вокруг линии: голубая против ложных линий ±3/±5%
    out = {}
    for w in (0.5, 1.0):
        out[str(w)] = {}
        for sh in (-5, -3, 0, 3, 5):
            line = B * (1 + sh / 100)
            out[str(w)][str(sh)] = {"макс": int((np.abs(hi[highs] / line[highs] - 1) * 100 <= w).sum()), "мин": int((np.abs(lo[lows] / line[lows] - 1) * 100 <= w).sum())}
    print("точки зигзага в полосе вокруг линии (сдвиг 0 — голубая):", json.dumps(out, ensure_ascii=False))
    pd.DataFrame({"от": bins[:-1], "до": bins[1:], "максимумы": hh, "минимумы": hl}).to_csv(pos.OUT / "tp_blue_zig.csv", index=False)
    (pos.OUT / "tp_blue_zig.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
