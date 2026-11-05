"""Сводка правил для передачи GPT: одни и те же определения на BTC и ETH, позициями.
1) лонг к голубой: фильтры мелкий уход и ADX против случайного подмножества тех же сделок;
2) пересечение зелёной после мелкого ухода как отдельное правило, тейк 3 ATR и стоп 1.5 ATR, соседи точным списком, контроль;
3) правило над голубыми на ETH; 4) типы сделок v1 и перекладки по одной линии на обеих монетах; 5) закрытие шорта по «далеко».
Фильтры и пороги взяты из журнала после просмотра истории, поэтому это отбор на той же истории: проверка — периоды, ETH и будущие данные."""
from __future__ import annotations

import json
import sys
from collections import namedtuple
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import history_v1 as hv  # noqa: E402
import journal as jr  # noqa: E402
import pos  # noqa: E402
import rule5  # noqa: E402
import rules  # noqa: E402
import tp_blue as tb  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 40, "display.max_rows", 300)
ETH_PKL = Path("/private/tmp/claude-501/-Users-alexeychechikov/85655d8a-c366-454b-bd04-314adf4588cf/scratchpad/mr/bars_5cee39b1d0e5b669_d02bb3475692fe5d.pkl")
Leg = namedtuple("Leg", "i0 i1 p0 p1 s")
LIM5D = 120


def prep(h1, h4, d1, fund):
    h4 = jr.add_extra(h4.copy(), d1, fund)
    a = rules.prepare(h1, h4)
    t = a["t"]
    f = np.zeros(len(t))
    np.add.at(f, np.clip(np.searchsorted(t, fund.index.to_numpy(), side="left"), 0, len(t) - 1), fund.to_numpy())
    a["F"] = np.cumsum(f) * 100
    a["atr4"] = h4["atr"].to_numpy()[a["j"]]
    a["R1"], a["B1h"], a["run_B1"] = h1["R"].to_numpy(), h1["B"].to_numpy(), h1["run_B"].to_numpy()
    a["i0"] = int(np.searchsorted(t, cw.T("2018-01-01")))
    a["f_adx"] = h4["adx"].to_numpy()[a["j"]]
    a["f_far30"] = h4["d_G"].abs().shift(1).rolling(30).max().to_numpy()[a["j"]]
    a["f_run_G"] = h4["run_G"].to_numpy()[a["j"]]
    a["f_run_G_prev"] = h4["run_G"].shift(1).to_numpy()[a["j"]]
    return a, h4


def per_sums(v, per):
    return {p: round(float(v[per == p].sum()), 1) for p in pos.PER}


def l1_filters(a, coin):
    t = a["t"]
    x = tb.make_arrays(a, 1)
    ev = tb.events(a, 1, "L1", x)
    per = pos.period_of(t[ev])
    far, adx = a["f_far30"][ev], a["f_adx"][ev]
    masks = {"все": np.ones(len(ev), bool), "уход ≤3%": far <= 3, "уход ≤4%": far <= 4, "уход ≤5%": far <= 5, "уход >5%": far > 5, "ADX ≤20": adx <= 20, "ADX ≤25": adx <= 25, "ADX >30": adx > 30, "уход ≤4% и ADX ≤25": (far <= 4) & (adx <= 25)}
    rng = np.random.default_rng(20261105)
    rows = []
    tb.FR = [0.4, 0.5]
    for stop in ("S2", "S3"):
        out = tb.outcomes(a, x, ev, 1, stop)["f0.5"]
        for nm, m in masks.items():
            v = out[m]
            if len(v) < 10:
                continue
            se = v.std(ddof=1) / np.sqrt(len(v))
            ctl = out[rng.integers(0, len(out), size=(999, len(v)))].mean(axis=1)
            rows.append({"монета": coin, "стоп": stop, "фильтр": nm, "n": len(v), "среднее_%": round(float(v.mean()), 3), "плюс_%": round(float((v > 0).mean() * 100), 1), "сумма_%": round(float(v.sum()), 1), "просадка_%": pos.max_dd(v), **per_sums(v, per[m]),
                         "ди_низ": round(float(v.mean() - 1.96 * se), 3), "лучше_подмножества_%": round(float((ctl < v.mean()).mean() * 100), 1)})
    return pd.DataFrame(rows)


def green_cross(a, coin):
    """Первое закрытие 4ч через зелёную после минимум 3 закрытий с другой стороны. Тейк и стоп в ATR 4ч от входа, предел 5 дней."""
    t = a["t"]
    n = len(t)
    jp = np.r_[-1, a["j"][:-1]]
    new4 = a["j"] != jp
    above = a["f_close"] > a["f_B"]
    rows = []
    rng = np.random.default_rng(20261105)
    per_all = pos.period_of(t)
    idx_all = np.arange(n)
    for side, nm in ((1, "лонг"), (-1, "шорт")):
        ev_mask = new4 & (idx_all >= a["i0"]) & ((a["f_run_G"] == side) & (a["f_run_G_prev"] * side <= -3))
        ev = idx_all[ev_mask]
        ev = ev[ev + LIM5D < n]
        pool = rng.choice(idx_all[(idx_all >= a["i0"]) & (idx_all + LIM5D < n)], size=6000, replace=False)
        far, adx = a["f_far30"][ev], a["f_adx"][ev]
        cfgs = [("все", np.ones(len(ev), bool), 3, 1.5)]
        for th in (2, 2.5, 3, 3.5, 4, 5):
            cfgs.append((f"уход ≤{th}%", far <= th, 3, 1.5))
        cfgs.append(("уход >5%", far > 5, 3, 1.5))
        for th in (20, 25, 30):
            cfgs.append((f"ADX ≤{th}", adx <= th, 3, 1.5))
        cfgs.append(("ADX >30", adx > 30, 3, 1.5))
        cfgs.append(("уход ≤3%, ADX ≤25", (far <= 3) & (adx <= 25), 3, 1.5))
        cfgs.append(("уход ≤3%, над голубой 4ч", (far <= 3) & above[ev], 3, 1.5))
        cfgs.append(("уход ≤3%, под голубой 4ч", (far <= 3) & ~above[ev], 3, 1.5))
        for m_tp, k_st in ((2, 1), (2, 1.5), (3, 1), (4, 1.5), (4, 2), (5, 2)):
            cfgs.append((f"уход ≤3%, тейк {m_tp}, стоп {k_st}", far <= 3, m_tp, k_st))
        cache = {}
        for nm_f, m, m_tp, k_st in cfgs:
            evm = ev[m]
            if len(evm) < 15:
                continue
            v = np.array([hv.manage(a, Leg(i, i + LIM5D, a["c"][i], a["c"][i + LIM5D], side), k_st, m_tp) for i in evm])
            key = (m_tp, k_st)
            if key not in cache:
                cache[key] = np.array([hv.manage(a, Leg(i, i + LIM5D, a["c"][i], a["c"][i + LIM5D], side), k_st, m_tp) for i in pool])
            pv = cache[key]
            per = per_all[evm]
            ab = above[evm]
            tot = np.zeros(999)
            for p in pos.PER:
                for st in (True, False):
                    cnt = int(((per == p) & (ab == st)).sum())
                    if cnt == 0:
                        continue
                    cp = pv[(per_all[pool] == p) & (above[pool] == st)]
                    tot += cp[rng.integers(0, len(cp), size=(999, cnt))].sum(axis=1)
            se = v.std(ddof=1) / np.sqrt(len(v))
            rows.append({"монета": coin, "сторона": nm, "фильтр": nm_f, "тейк": m_tp, "стоп": k_st, "n": len(v), "среднее_%": round(float(v.mean()), 3), "плюс_%": round(float((v > 0).mean() * 100), 1), "сумма_%": round(float(v.sum()), 1), "просадка_%": pos.max_dd(v), **per_sums(v, per),
                         "ди_низ": round(float(v.mean() - 1.96 * se), 3), "лучше_случайного_%": round(float((tot < v.sum()).mean() * 100), 1), "случайные_медиана_%": round(float(np.median(tot)), 1)})
    return pd.DataFrame(rows)


def types_v1(a, h4, coin):
    t_end = int(a["t"][-1])
    d = hv.legs_frame(a, rules.run(a, hv.T0, t_end))
    d["тип"] = d["tag"].replace({"blue>G": "blue"})
    fc, fb, fb1 = a["f_close"], a["f_B"], a["f_B1"]
    i0 = d["i0"].to_numpy()
    d["зона"] = np.where((fc[i0] < fb[i0]) & (fc[i0] < fb1[i0]), "под обеими", np.where((fc[i0] > fb[i0]) & (fc[i0] > fb1[i0]), "над обеими", "между"))
    t1 = hv.group_table(a, d, "тип")
    t1.insert(0, "монета", coin)
    d["тип_зона"] = d["тип"] + " " + d["зона"]
    t2 = hv.group_table(a, d[d["тип"].isin(["flip"])], "тип_зона")
    t2.insert(0, "монета", coin)
    rows = []
    for nm, g in (("все", d), ("шорт", d[d["s"] == -1]), ("лонг", d[d["s"] == 1])):
        rows.append({"монета": coin, "что": nm, "n": len(g), "среднее_%": round(float(g["pnl"].mean()), 3), "сумма_%": round(float(g["pnl"].sum()), 1), "просадка_%": pos.max_dd(g["pnl"].to_numpy()), **{p: round(float(g.loc[g["per"] == p, "pnl"].sum()), 1) for p in pos.PER}})
    for col, lab in (("G", "перекладка по зелёной 4ч"), ("Y", "перекладка по жёлтой 4ч"), ("B", "перекладка по голубой 4ч")):
        x = hv.legs_frame(a, rules.flips(h4, hv.T0, t_end, col))
        rows.append({"монета": coin, "что": lab, "n": len(x), "среднее_%": round(float(x["pnl"].mean()), 3), "сумма_%": round(float(x["pnl"].sum()), 1), "просадка_%": pos.max_dd(x["pnl"].to_numpy()), **{p: round(float(x.loc[x["per"] == p, "pnl"].sum()), 1) for p in pos.PER}})
    for kw, lab in (({"far": False}, "шорты автомата без закрытия по далеко"), ({"far_g": -4.0}, "шорты, далеко −4%"), ({}, "шорты, далеко −5%"), ({"far_g": -6.0}, "шорты, далеко −6%"), ({"far_g": -7.0}, "шорты, далеко −7%")):
        x = hv.legs_frame(a, rules.run(a, hv.T0, t_end, **kw))
        x = x[x["s"] == -1]
        rows.append({"монета": coin, "что": lab, "n": len(x), "среднее_%": round(float(x["pnl"].mean()), 3), "сумма_%": round(float(x["pnl"].sum()), 1), "просадка_%": pos.max_dd(x["pnl"].to_numpy()), **{p: round(float(x.loc[x["per"] == p, "pnl"].sum()), 1) for p in pos.PER}})
    return t1, t2, pd.DataFrame(rows)


def rule5_eth(a, coin):
    rows = []
    c, fc = a["c"], a["f_close"]
    for side, st in ((1, (c > a["B1h"]) & (fc > a["f_Y"])), (-1, (c < a["B1h"]) & (fc < a["f_Y"]))):
        for filt in ("над", "под"):
            row, *_ = rule5.evaluate(a, "голубая 1ч + жёлтая 4ч", st, side, 3, filt)
            rows.append({"монета": coin, "сторона": "лонг" if side == 1 else "шорт", **{k: row[k] for k in ("вход", "n", "среднее_%", "плюс_%", "сумма_%", "просадка_%", "A_%", "B_%", "C_%", "всё_лучше_%", "случайные_медиана_%", "ди_низ")}})
    return pd.DataFrame(rows)


def main():
    m, h1, h4, d1, fund = cw.load()
    del m
    a, h4b = prep(h1, h4, d1, fund)
    m2, h1e, h4e, d1e, fe = pd.read_pickle(ETH_PKL)
    del m2
    h1e, h4e = cw.features(h1e, h4e, 1), cw.features(h4e, h1e, 4)
    e, h4ee = prep(h1e, h4e, d1e, fe)
    res = {}
    f = pd.concat([l1_filters(a, "BTC"), l1_filters(e, "ETH")])
    f.to_csv(pos.OUT / "entry_l1_filters.csv", index=False)
    print(f.to_string(index=False))
    g = pd.concat([green_cross(a, "BTC"), green_cross(e, "ETH")])
    g.to_csv(pos.OUT / "entry_green_cross.csv", index=False)
    print(g.to_string(index=False))
    r5 = pd.concat([rule5_eth(a, "BTC"), rule5_eth(e, "ETH")])
    r5.to_csv(pos.OUT / "entry_rule5_coins.csv", index=False)
    print(r5.to_string(index=False))
    tt, tz, tr = [], [], []
    for x, b, coin in ((a, h4b, "BTC"), (e, h4ee, "ETH")):
        t1, t2, t3 = types_v1(x, b, coin)
        tt.append(t1)
        tz.append(t2)
        tr.append(t3)
    tt, tz, tr = pd.concat(tt), pd.concat(tz), pd.concat(tr)
    tt.to_csv(pos.OUT / "entry_types.csv", index=False)
    tz.to_csv(pos.OUT / "entry_types_zones.csv", index=False)
    tr.to_csv(pos.OUT / "entry_flips_far.csv", index=False)
    print(tt.to_string(index=False))
    print(tz.to_string(index=False))
    print(tr.to_string(index=False))


if __name__ == "__main__":
    main()
