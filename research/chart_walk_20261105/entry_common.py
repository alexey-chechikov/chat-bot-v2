"""Что общего у прибыльных входов автомата: показатели в словах оператора на момент входа (всё только из закрытых баров) против итога сделки. Сделки не выбрасываются.
Расстояния и наклоны в ATR 4ч, чтобы монеты были сравнимы. Для каждого показателя: корреляция рангов с итогом и суммы по третям внутри ряда; устойчивость — совпал ли знак на четырёх рядах и трёх отрезках BTC."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import gpt_check as gc  # noqa: E402
import ledger as lg  # noqa: E402
import pos  # noqa: E402
import words as wd  # noqa: E402

pd.set_option("display.width", 260, "display.max_columns", 40, "display.max_rows", 300)
DAY = 24


def load_all():
    m, h1, h4, d1, fund = cw.load()
    del m
    a, _ = gc.er.prep(h1, h4, d1, fund)
    wd.add_runs(a)
    m2, h1e, h4e, d1e, fe = pd.read_pickle(gc.er.ETH_PKL)
    del m2
    h1e, h4e = cw.features(h1e, h4e, 1), cw.features(h4e, h1e, 4)
    e, _ = gc.er.prep(h1e, h4e, d1e, fe)
    wd.add_runs(e)
    bs, fbs = gc.load_bitstamp()
    wd.add_runs(bs)
    xr, fx = gc.load_xrp()
    wd.add_runs(xr)
    return [("BTC", a, lg.funding_marks(a, fund)), ("ETH", e, lg.funding_marks(e, fe)), ("Bitstamp", bs, lg.funding_marks(bs, fbs)), ("XRP", xr, lg.funding_marks(xr, fx))]


def extras(a):
    """Почасовые показатели: кросс зелёной и жёлтой за 10 дней, максимум и минимум 30 дней."""
    n = len(a["c"])
    if "x_cross" in a:
        return a
    sgn = np.sign(a["f_G"] - a["f_Y"])
    ch = np.r_[0, (sgn[1:] != sgn[:-1]).astype(int)]
    cs = np.cumsum(ch)
    a["x_cross"] = cs - np.r_[np.zeros(min(10 * DAY, n)), cs[:-10 * DAY]] if n > 10 * DAY else cs
    h = pd.Series(a["h"])
    l = pd.Series(a["l"])
    a["x_hi30"] = h.rolling(30 * DAY, min_periods=DAY).max().to_numpy()
    a["x_lo30"] = l.rolling(30 * DAY, min_periods=DAY).min().to_numpy()
    return a


def lag(x, i, k):
    return x[max(i - k, 0)]


def frame(coin, a, fm, legs):
    extras(a)
    t, c = a["t"], a["c"]
    i0s = np.array([x[0] for x in legs])
    rows = []
    for k, x in enumerate(legs):
        i0, i1, p0, p1, s, tag, why = x
        m, f, u = lg.trade_cash(fm, x[:5])
        atr = a["atr4"][i0]
        px = a["f_close"][i0]
        G, Y, R, B, B1 = a["f_G"][i0], a["f_Y"][i0], a["f_R"][i0], a["f_B"][i0], a["f_B1"][i0]
        R1 = a["R1"][i0]
        h, l = a["h"][i0 + 1:i1 + 1], a["l"][i0 + 1:i1 + 1]
        hi, lo = (h.max(), l.min()) if len(h) else (p0, p0)
        rows.append({"coin": coin, "i0": i0, "i1": i1, "t0": t[i0], "год": pd.Timestamp(int(t[i0]), unit="s").year, "s": s, "тип": tag.split(",")[0], "причина": why.split(":")[0], "p0": p0, "p1": p1,
                     "r": (m - f - u) / lg.NOTIONAL * 100, "часов": i1 - i0, "mfe": (s * ((hi if s == 1 else lo) / p0 - 1)) * 100, "atr_pct": atr / c[i0] * 100, "mfe_atr": s * ((hi if s == 1 else lo) - p0) / atr,
                     "от_G": (px - G) / atr, "от_Y": (px - Y) / atr, "от_R": (px - R) / atr, "от_B4": (px - B) / atr, "от_B1": (c[i0] - B1) / atr, "от_R1": (c[i0] - R1) / atr,
                     "G_Y": (G - Y) / atr, "Y_R": (Y - R) / atr, "G_R": (G - R) / atr, "R_B4": (R - B) / atr, "B1_B4": (B1 - B) / atr,
                     "накл_G": (G - lag(a["f_G"], i0, DAY)) / atr, "накл_Y": (Y - lag(a["f_Y"], i0, DAY)) / atr, "накл_R": (R - lag(a["f_R"], i0, DAY)) / atr, "накл_B4": (B - lag(a["f_B"], i0, 5 * DAY)) / atr, "накл_B1": (B1 - lag(a["f_B1"], i0, DAY)) / atr,
                     "ход_5д": (c[i0] - lag(c, i0, 5 * DAY)) / atr, "ход_30д": (c[i0] - lag(c, i0, 30 * DAY)) / atr, "от_макс30": (c[i0] - a["x_hi30"][i0]) / atr, "от_мин30": (c[i0] - a["x_lo30"][i0]) / atr,
                     "adx": a["f_adx"][i0], "ширина_ранг": a["f_width_rank"][i0], "кросс_GY_10д": a["x_cross"][i0], "сделок_10д": int(((i0s < i0) & (i0s >= i0 - 10 * DAY)).sum()), "часов_после_прошлой": (i0 - legs[k - 1][1]) if k else 999})
    return pd.DataFrame(rows)


def stability(d, feats):
    """Знак связи показателя с итогом на каждом ряду и отрезке BTC, суммы по третям."""
    rows = []
    for side, nm in ((1, "лонг"), (-1, "шорт")):
        ds = d[d["s"] == side]
        for ft in feats:
            row = {"сторона": nm, "показатель": ft}
            signs = []
            for coin, g in ds.groupby("coin"):
                rho = g[ft].rank().corr(g["r"].rank())
                row[coin] = round(rho, 3)
                signs.append(np.sign(rho))
            bt = ds[ds["coin"] == "BTC"]
            for lab, lo, hi in (("A", 0, 2022), ("B", 2022, 2025), ("C", 2025, 2100)):
                gg = bt[(bt["год"] >= lo) & (bt["год"] < hi)]
                row[lab] = round(gg[ft].rank().corr(gg["r"].rank()), 3)
            row["совпало_рядов"] = int(max(sum(1 for x in signs if x > 0), sum(1 for x in signs if x < 0)))
            row["мин_модуль"] = round(min(abs(row[c]) for c in ("BTC", "ETH", "Bitstamp", "XRP")), 3)
            row["средн"] = round(np.mean([row[c] for c in ("BTC", "ETH", "Bitstamp", "XRP")]), 3)
            rows.append(row)
    return pd.DataFrame(rows)


def terciles(d, ft, side):
    ds = d[d["s"] == side].copy()
    out = {}
    for coin, g in ds.groupby("coin"):
        q = g[ft].rank(pct=True)
        out[coin] = (round(g.loc[q <= 1 / 3, "r"].sum()), round(g.loc[(q > 1 / 3) & (q <= 2 / 3), "r"].sum()), round(g.loc[q > 2 / 3, "r"].sum()))
    return out


def winners(d):
    """Лучшая четверть против худшей: медианы показателей, отдельно лонг и шорт, все ряды вместе, ранги внутри ряда."""
    rows = []
    feats = [c for c in d.columns if c not in ("coin", "i0", "i1", "t0", "год", "s", "тип", "причина", "p0", "p1", "r", "часов", "mfe", "mfe_atr")]
    for side, nm in ((1, "лонг"), (-1, "шорт")):
        ds = d[d["s"] == side].copy()
        ds["q"] = ds.groupby("coin")["r"].rank(pct=True)
        top, bot = ds[ds["q"] >= .75], ds[ds["q"] <= .25]
        for ft in feats:
            rows.append({"сторона": nm, "показатель": ft, "лучшие": round(top[ft].median(), 2), "все": round(ds[ft].median(), 2), "худшие": round(bot[ft].median(), 2)})
    return pd.DataFrame(rows)


def main():
    series = load_all()
    frames = [frame(coin, a, fm, wd.run(a)) for coin, a, fm in series]
    d = pd.concat(frames, ignore_index=True)
    d.to_csv(pos.OUT / "entry_common_trades.csv", index=False)
    feats = ["atr_pct", "от_G", "от_Y", "от_R", "от_B4", "от_B1", "от_R1", "G_Y", "Y_R", "G_R", "R_B4", "B1_B4", "накл_G", "накл_Y", "накл_R", "накл_B4", "накл_B1", "ход_5д", "ход_30д", "от_макс30", "от_мин30", "adx", "ширина_ранг", "кросс_GY_10д", "сделок_10д", "часов_после_прошлой"]
    st = stability(d, feats)
    st.to_csv(pos.OUT / "entry_common_stability.csv", index=False)
    print(st.sort_values(["сторона", "средн"]).to_string(index=False), flush=True)
    w = winners(d)
    w.to_csv(pos.OUT / "entry_common_winners.csv", index=False)
    print(w.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
