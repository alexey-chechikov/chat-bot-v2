"""Участок 1 (BTC 15.02–15.03.2025): слова оператора как автомат на закрытиях, сетка 0.6/1.4 по ногам, замеры в точках.

Черновик правил (пороги — из первого просмотра таблицы участка, это НЕ проверка, а запись для будущей проверки на истории):
  открыть шорт: 4ч close ниже зелёной, ниже голубой 4ч и голубой 1ч, ранг ширины пучка (G,Y,R,B4) за 180 дней ≤ 0.15;
  держать, пока 4ч под зелёной; «далеко»: d_G ≤ −5% → закрыть; возврат к зелёной (−1% < d_G < 0) → снова шорт;
  4ч close выше зелёной → шорт не добирать (i_off), выше зелёной и жёлтой + 3 закрытия 1ч над красной → закрыть, лонг;
  лонг: цель — касание голубой 4ч (лимит); сломан (4ч под зелёной и жёлтой + 3 закрытия 1ч под красной) → закрыть, шорт
  (зеркало — моё дополнение, у оператора про лонг без цели ничего нет);
  после цели: первое 4ч-закрытие под голубой 4ч → шорт «от голубой», стоп — 4ч-закрытие над ней, «далеко» ещё и d_B ≤ −10%.
Сетка — gridk (живые издержки WEEX, ордер $100 ≈ живые 0.0012 BTC, потолок $6 000). Вход в следующую минуту после закрытия.
Выход: out/segment1_legs_*.csv, segment1_bars_1h.csv, segment1_bars_4h.csv, segment1_far.json, segment1.json."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402

gridk = cw.gridk
OUT = cw.HERE / "out"
OUT.mkdir(exist_ok=True)
A, Z = cw.T("2025-02-15"), cw.T("2025-03-15")
RANK_MAX, FAR_B, NEAR_G = 0.15, -10.0, -1.0
SIDE = {"S": -1, "L": 1}
DAY4 = 6


def automaton(h1, h4, far_g=-5.0, far=True, fast_long_exit=False, min_w3=0.0):
    """→ ноги (side, tag, t0, t1, why_open, why_close, p0, p1, t_off). Время — закрытие бара, действие с него.
    Варианты (мои, не оператора): fast_long_exit — лонг без цели закрывается на 3 закрытиях 1ч под красной, без флипа;
    min_w3 — флип/открытие по «над/под G+Y» не делать, пока три TEMA на 4ч уже этого % (внутри узкого пучка пересечения
    ничего не значат)."""
    legs, cur, covered, await_blue = [], None, False, False
    j_prev = -1
    k4 = h4["known"].to_numpy()
    idx = np.where((h1["known"].to_numpy() > A) & (h1["known"].to_numpy() <= Z))[0]
    t0_first = h1["known"].to_numpy()[idx[0]]
    for i in idx:
        r = h1.iloc[i]
        t = int(r["known"])
        j = int(np.searchsorted(k4, t, side="right") - 1)
        f = h4.iloc[j]
        fp = h4.iloc[int(np.searchsorted(k4, t - 3600, side="right") - 1)]   # 4ч, известный до начала этого часа
        new4 = j != j_prev
        j_prev = j
        d_g, d_b = float(f["d_G"]), float(f["d_B"])
        under_g, over_gy = f["close"] < f["G"], f["close"] > f["G"] and f["close"] > f["Y"]
        under_gy = f["close"] < f["G"] and f["close"] < f["Y"]
        r_over, r_under = r["run_R"] >= 3, r["run_R"] <= -3
        wide = f["width3"] >= min_w3
        narrow = f["width_rank"] <= RANK_MAX
        under_blues = f["close"] < f["B"] and f["close"] < f["B1"]

        def close(why, price):
            cur.update(t1=t, why_close=why, p1=float(price))
            legs.append(dict(cur))

        def open_(side, tag, why, price):
            return dict(side=side, tag=tag, t0=t, why_open=why, p0=float(price), t_off=None)

        if cur is not None and cur["side"] == "L":
            if r["high"] >= fp["B"]:                                     # цель — касание голубой 4ч
                close("цель: голубая 4ч", max(fp["B"], r["open"]))
                cur, await_blue = None, True
                continue
            if fast_long_exit and r_under:
                close("1ч под R, 3 закрытия", r["close"])
                cur = None
                continue
            if under_gy and r_under and wide:
                close("4ч под G+Y, 1ч под R", r["close"])
                cur = open_("S", "flip", "флип из лонга", r["close"])
                continue
        elif cur is not None and cur["side"] == "S":
            if cur["tag"] == "blue" and under_g:
                cur["tag"] = "blue>G"
            if cur["tag"] == "blue" and new4 and f["close"] > f["B"]:
                close("стоп: 4ч над голубой", r["close"])
                cur, await_blue = None, True                             # следующая попытка от той же голубой
                continue
            if far and new4 and (d_g <= far_g or (cur["tag"].startswith("blue") and d_b <= FAR_B)):
                close(f"далеко: d_G {d_g:.1f}%, d_B {d_b:.1f}%", r["close"])
                cur, covered = None, True
                continue
            if cur["tag"] != "blue":
                if new4 and f["close"] > f["G"] and cur["t_off"] is None:
                    cur["t_off"] = t                                     # пробили зелёную — не добираем
                if over_gy and r_over and wide:
                    close("4ч над G+Y, 1ч над R", r["close"])
                    cur = open_("L", "flip", "флип из шорта", r["close"])
                    continue
        if cur is None:
            if await_blue:
                if new4 and f["close"] < f["B"]:
                    cur, await_blue = open_("S", "blue", "от голубой 4ч", r["close"]), False
                elif new4 and f["a_B"] > 1:                              # ушли над голубую на ATR — шорта от неё нет
                    await_blue = False
            elif over_gy and r_over and f["run_Y"] <= 6 and t > t0_first and wide:
                cur, covered = open_("L", "fresh", "4ч над G+Y, 1ч над R", r["close"]), False
            elif covered and new4 and under_g and d_g > NEAR_G:
                cur, covered = open_("S", "reshort", f"возврат к зелёной: d_G {d_g:.2f}%", r["close"]), False
            elif covered and new4 and f["close"] > f["G"]:
                covered = False
            elif not covered and new4 and under_g and under_blues and narrow:
                cur = open_("S", "narrow", f"сужение: ранг {f['width_rank']:.2f}", r["close"])
    if cur is not None:
        close("конец участка", h1.iloc[idx[-1]]["close"])
    return legs


def green_flips(h4):
    """Контроль попроще: 4ч над зелёной — лонг, под зелёной — шорт, флип на каждом закрытии через линию."""
    s = h4[(h4["known"] > A) & (h4["known"] <= Z)]
    legs, cur = [], None
    for _, f in s.iterrows():
        side = "L" if f["close"] > f["G"] else "S"
        if cur is None or cur["side"] != side:
            if cur is not None:
                cur.update(t1=int(f["known"]), why_close="флип по зелёной", p1=float(f["close"]))
                legs.append(cur)
            cur = dict(side=side, tag="G4", t0=int(f["known"]), why_open="флип по зелёной", p0=float(f["close"]), t_off=None)
    f = s.iloc[-1]
    cur.update(t1=int(f["known"]), why_close="конец участка", p1=float(f["close"]))
    legs.append(cur)
    return legs


def grid_legs(mk, legs):
    out = []
    for g in legs:
        i0, i1 = mk.idx([g["t0"]])[0], mk.idx([g["t1"]])[0]
        off = None if g["t_off"] is None else mk.idx([g["t_off"]])
        r = mk.run(np.array([i0]), np.array([i1]), SIDE[g["side"]], i_off=off)[0]
        move = (g["p1"] / g["p0"] - 1) * 100 * SIDE[g["side"]]
        out.append({"сторона": g["side"], "тип": g["tag"], "открыта": cw.utc(g["t0"]), "закрыта": cw.utc(g["t1"]),
                    "цена_вх": round(g["p0"]), "цена_вых": round(g["p1"]), "ход_%": round(move, 2),
                    "сетка_$": round(float(r[0]), 2), "тейки_шт": int(r[8]), "лотов_на_выходе": int(r[9]),
                    "мешок_$": round(float(r[5]), 2), "просадка_$": round(float(r[6]), 2),
                    "пик_номинал_$": round(float(r[11])),
                    "почему_открыта": g["why_open"], "почему_закрыта": g["why_close"]})
    return pd.DataFrame(out)


def summary(tbl):
    cum = tbl["сетка_$"].cumsum().to_numpy()
    before = np.r_[0.0, cum[:-1]]
    worst = float((before + tbl["просадка_$"].to_numpy()).min())
    peak_before = np.maximum.accumulate(np.r_[0.0, cum])[:-1]
    dd = float((before + tbl["просадка_$"].to_numpy() - peak_before).min())      # от пика закрытых ног до дна внутри ноги
    return {"итог_$": round(float(cum[-1]), 2), "просадка_от_пика_$": round(dd, 2),
            "шорт_$": round(float(tbl.loc[tbl["сторона"] == "S", "сетка_$"].sum()), 2),
            "лонг_$": round(float(tbl.loc[tbl["сторона"] == "L", "сетка_$"].sum()), 2), "ног": len(tbl),
            "худшая_точка_$": round(min(worst, 0.0), 2), "тейки_шт": int(tbl["тейки_шт"].sum()),
            "пик_номинал_$": int(tbl["пик_номинал_$"].max()),
            "позиция_$1000_после_издержек_$": round(float((tbl["ход_%"] * 10 - 1.36).sum()), 1)}


def far_table(h4):
    """Как далеко и как часто, 4ч 2018–11.2026: эпизод — первое касание уровня после 5 дней без него.
    Возврат — первое закрытие выше зелёной (до 20 дней). Описание, не проверка сделки."""
    b = h4[h4.index >= cw.T("2018-01-01")]
    c, g, lo = b["close"].to_numpy(), b["G"].to_numpy(), b["low"].to_numpy()
    yrs = (b.index[-1] - b.index[0]) / (365.25 * 86400)
    fwd = {n: c[n:] / c[:-n] - 1 for n in (6, 8, 10, 14, 15)}
    res = {"баров_4ч": len(b), "лет": round(yrs, 2),
           "база_выше_через_N_баров_%": {str(n): round(float((v > 0).mean() * 100)) for n, v in fwd.items()},
           "база_медиана_через_N_баров_%": {str(n): round(float(np.median(v) * 100), 2) for n, v in fwd.items()}}
    for col, levels in (("d_G", (-3, -4, -5, -6, -8)), ("d_R", (-5, -8, -10, -12, -15)),
                        ("d_B", (-5, -8, -10, -12, -15, -17, -20)), ("d_Bo", (-5, -8, -10, -12))):
        x = b[col].to_numpy()
        row = {}
        for lv in levels:
            hit = x <= lv
            starts = np.where(hit & ~np.r_[False, hit[:-1]])[0]
            first = [s for k, s in enumerate(starts) if k == 0 or s - starts[k - 1] > 5 * DAY4]
            n_ret3, deeper, bars_ret, px_ret = 0, [], [], []
            for s in first:
                e = min(s + 20 * DAY4, len(b) - 1)
                back = np.where(c[s + 1:e + 1] >= g[s + 1:e + 1])[0]
                n = int(back[0]) + 1 if len(back) else None
                if n is not None:
                    bars_ret.append(n)
                    n_ret3 += n <= 3 * DAY4
                    px_ret.append((c[s + n] / c[s] - 1) * 100)
                end = s + (n if n is not None else 20 * DAY4)
                deeper.append((lo[s:min(end, len(b) - 1) + 1].min() / c[s] - 1) * 100)
            row[str(lv)] = {"доля_времени_%": round(float(hit.mean() * 100), 2), "эпизодов": len(first),
                            "в_год": round(len(first) / yrs, 1),
                            "вернулась_за_3_дня_%": round(n_ret3 / max(len(first), 1) * 100),
                            "баров_до_возврата_медиана": float(np.median(bars_ret)) if bars_ret else None,
                            "ещё_вниз_до_возврата_медиана_%": round(float(np.median(deeper)), 2) if deeper else None,
                            "ещё_вниз_худшие_10%": round(float(np.quantile(deeper, 0.1)), 2) if deeper else None,
                            "цена_на_возврате_к_цене_касания_медиана_%": round(float(np.median(px_ret)), 2) if px_ret else None,
                            "возврат_выше_цены_касания_%": round(float((np.array(px_ret) > 0).mean() * 100)) if px_ret else None}
        res[col] = row
    return res


def runs_of(b, mask, what):
    """Серии баров с условием в окне участка: начало, конец, цена, ход за 3 и 5 дней после начала серии."""
    k24 = 6 if (b.index[1] - b.index[0]) == 14400 else 24
    pos = np.where(mask.to_numpy())[0]
    if not len(pos):
        return []
    groups = np.split(pos, np.where(np.diff(pos) > 1)[0] + 1)
    out = []
    for g in groups:
        s, e = g[0], g[-1]
        if not A <= b.index[s] < Z:
            continue
        cl = float(b["close"].iloc[s])
        row = {"что": what, "с": cw.utc(int(b["known"].iloc[s])), "по": cw.utc(int(b["known"].iloc[e])), "баров": len(g),
               "цена": round(cl)}
        for days in (3, 5):
            w = b.iloc[s + 1:s + 1 + days * k24]
            row[f"макс_вверх_{days}д_%"] = round((float(w["high"].max()) / cl - 1) * 100, 1)
            row[f"макс_вниз_{days}д_%"] = round((float(w["low"].min()) / cl - 1) * 100, 1)
        out.append(row)
    return out


def point_row(h1, h4, name, t):
    """Все замеры на закрытии часа t (1ч) и последней закрытой 4ч."""
    r = h1[h1["known"] == t].iloc[0]
    j = int(np.searchsorted(h4["known"].to_numpy(), t, side="right") - 1)
    f = h4.iloc[j]
    return {"точка": name, "t_закр": cw.utc(t), "1ч_close": round(float(r["close"])),
            "4ч_бар_закр": cw.utc(int(f["known"])), "4ч_close": round(float(f["close"])),
            "4ч_d_G": round(float(f["d_G"]), 2), "4ч_a_G": round(float(f["a_G"]), 2), "4ч_d_Y": round(float(f["d_Y"]), 2),
            "4ч_d_R": round(float(f["d_R"]), 2), "4ч_d_B": round(float(f["d_B"]), 2), "4ч_a_B": round(float(f["a_B"]), 2),
            "4ч_d_B1": round(float(f["d_Bo"]), 2), "4ч_width": round(float(f["width"]), 2),
            "4ч_width3": round(float(f["width3"]), 2), "4ч_rank": round(float(f["width_rank"]), 2),
            "4ч_slope_B": round(float(f["slope_B"]), 2), "4ч_slope_G": round(float(f["slope_G"]), 2),
            "4ч_run_G": int(f["run_G"]), "4ч_run_Y": int(f["run_Y"]), "4ч_run_B": int(f["run_B"]),
            "4ч_vol30": round(float(f["vol_vs30"]), 2), "4ч_volT": round(float(f["vol_trend"]), 2), "4ч_ret24": round(float(f["ret24"]), 2),
            "1ч_d_G": round(float(r["d_G"]), 2), "1ч_d_R": round(float(r["d_R"]), 2), "1ч_d_B": round(float(r["d_B"]), 2),
            "1ч_d_B4": round(float(r["d_Bo"]), 2), "1ч_width": round(float(r["width"]), 2), "1ч_rank": round(float(r["width_rank"]), 2),
            "1ч_run_R": int(r["run_R"]), "1ч_run_B": int(r["run_B"]), "1ч_run_B4": int(r["run_Bo"])}


POINTS = [("сужение ложное 17.02", "2025-02-17 16:00"), ("сужение ложное 19.02", "2025-02-19 04:00"),
          ("первая под всеми", "2025-02-21 20:00"), ("полотно 22.02", "2025-02-22 12:00"), ("полотно 24.02", "2025-02-24 12:00"),
          ("пробой вниз", "2025-02-24 16:00"), ("далеко 1", "2025-02-25 08:00"), ("возврат к G", "2025-02-27 12:00"),
          ("далеко 2 дно", "2025-02-28 08:00"), ("пробили G", "2025-02-28 16:00"), ("над Y4 + R1", "2025-03-01 20:00"),
          ("1ч над голубой", "2025-03-02 17:00"), ("цель голубая 4ч", "2025-03-02 18:00"), ("шорт от голубой", "2025-03-03 04:00"),
          ("далеко d_B-10", "2025-03-04 04:00"), ("лонг-2", "2025-03-04 21:00"), ("лонг-2 пик", "2025-03-06 06:00"),
          ("лонг-2 выход", "2025-03-08 04:00"), ("далеко 3", "2025-03-10 00:00"), ("дно 11.03", "2025-03-11 04:00"),
          ("узко 13.03", "2025-03-13 20:00"), ("узко 14.03", "2025-03-14 04:00")]


def main():
    m, h1, h4, d1, fund = cw.load()
    mk = gridk.Market(m["ts"].to_numpy(), m["open"].to_numpy(), m["high"].to_numpy(), m["low"].to_numpy(),
                      m["close"].to_numpy(), fund)
    for b in (h1, h4):
        lines = b[["G", "Y", "R"]]
        b["width3"] = (lines.max(axis=1) - lines.min(axis=1)) / b["close"] * 100
    res = {}
    for tag, kw in (("далеко_закрывать", {"far": True}), ("держать_без_далеко", {"far": False})):
        tbl = grid_legs(mk, automaton(h1, h4, **kw))
        tbl.to_csv(OUT / f"segment1_legs_{tag}.csv", index=False)
        print(tag, "\n", tbl.drop(columns=["почему_открыта"]).to_string(index=False))
        res[tag] = summary(tbl)
    res["варианты"] = {}
    for tag, kw in (("выход лонга по 1ч", {"fast_long_exit": True}), ("без флипа в пучке <1%", {"min_w3": 1.0}),
                    ("оба", {"fast_long_exit": True, "min_w3": 1.0})):
        tbl = grid_legs(mk, automaton(h1, h4, **kw))
        tbl.to_csv(OUT / f"segment1_legs_вариант_{tag.replace(' ', '_')}.csv", index=False)
        print(tag, "\n", tbl.drop(columns=["почему_открыта"]).to_string(index=False))
        res["варианты"][tag] = summary(tbl)
    res["соседи_далеко_d_G"] = {}
    for fg in (-3.0, -4.0, -4.5, -5.0, -5.5, -6.0, -7.0):
        res["соседи_далеко_d_G"][str(fg)] = summary(grid_legs(mk, automaton(h1, h4, far_g=fg)))
    tbl = grid_legs(mk, green_flips(h4))
    tbl.to_csv(OUT / "segment1_legs_зелёная.csv", index=False)
    res["флип_по_зелёной_4ч"] = summary(tbl)
    i0, i1 = mk.idx([A + 3600])[0], mk.idx([Z])[0]
    for nm, side in (("всё время лонг", 1), ("всё время шорт", -1)):
        r = mk.run(np.array([i0]), np.array([i1]), side)[0]
        res[nm] = {"итог_$": round(float(r[0]), 2), "тейки_$": round(float(r[1]), 2), "мешок_$": round(float(r[5]), 2),
                   "просадка_$": round(float(r[6]), 2), "лотов": int(r[9])}
    print(json.dumps(res, ensure_ascii=False, indent=1))
    keep = ["known", "open", "high", "low", "close", "volume", "G", "Y", "R", "B", "atr"]
    d = [f"{p}_{n}" for p in ("d", "a", "slope", "run") for n in ("G", "Y", "R", "B", "Bo")]
    extra = ["width", "width2", "width3", "width_atr", "width_rank", "ret24", "ret72", "vol_vs30", "vol_trend", "range_pct", "atr_pct"]
    for nm, b, other in (("1h", h1, "B4"), ("4h", h4, "B1")):
        s = b[(b.index >= A) & (b.index < Z)][keep + [other] + d + extra].copy()
        s.insert(0, "t_utc", pd.to_datetime(s.index, unit="s"))
        s.round(3).to_csv(OUT / f"segment1_bars_{nm}.csv", index=False)
    pts = pd.DataFrame([point_row(h1, h4, n, cw.T(t)) for n, t in POINTS])
    pts.to_csv(OUT / "segment1_points.csv", index=False)
    pd.set_option("display.width", 250, "display.max_columns", 50)
    print(pts.iloc[:, :17].to_string(index=False))
    print(pts.iloc[:, [0, 1] + list(range(17, pts.shape[1]))].to_string(index=False))
    far = far_table(h4)
    (OUT / "segment1_far.json").write_text(json.dumps(far, ensure_ascii=False, indent=1))
    rows = []
    for col, x in far.items():
        if col.startswith("d_"):
            for lv, v in x.items():
                rows.append({"мера": col, "порог": lv, **v})
    print(pd.DataFrame(rows).to_string(index=False))
    print({k: v for k, v in far.items() if k.startswith("база")})
    # серии: дивергенция объёма и сужение
    runs = []
    runs += runs_of(h4, (h4["vol_trend"] >= 1.5) & (h4["ret24"] <= -1), "объём ×1.5+ на падении ≥1% за сутки (4ч)")
    runs += runs_of(h4, (h4["width_rank"] <= RANK_MAX) & (h4["close"] < h4["B"]) & (h4["close"] < h4["B1"]) & (h4["close"] < h4["G"]),
                    "сужение + под двумя голубыми + под зелёной (4ч)")
    runs += runs_of(h1, (h1["width_rank"] <= RANK_MAX) & (h1["close"] < h1["B"]) & (h1["close"] < h1["B4"]) & (h1["close"] < h1["G"]),
                    "то же на 1ч")
    rr = pd.DataFrame(runs)
    rr.to_csv(OUT / "segment1_runs.csv", index=False)
    print(rr.to_string(index=False))
    # полотно: диапазон цены 22–24.02
    s = h4[(h4["known"] > cw.T("2025-02-21 20:00")) & (h4["known"] <= cw.T("2025-02-24 12:00"))]
    res["полотно"] = {"high": float(s["high"].max()), "low": float(s["low"].min()),
                      "ширина_%": round((float(s["high"].max()) / float(s["low"].min()) - 1) * 100, 2)}
    print(res["полотно"])
    (OUT / "segment1.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
