"""Почему шорты автомата «слова» в минусе: те же сделки, ничего не выбрасывается. Откуда итог, что было внутри минусовых сделок (MFE, MAE), где был вход, сколько отдано на выходе,
и что будет, если менять только выход. Выход-версия считает те же входы: следующий вход не сдвигается, поэтому это оценка, а не новый прогон автомата."""
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

pd.set_option("display.width", 260, "display.max_columns", 40, "display.max_rows", 200)
BLUE = {"от голубой": "от голубой", "от голубой, под зелёной": "от голубой"}


def frame(a, fm, legs):
    rows = []
    for x in legs:
        if x[4] != -1:
            continue
        i0, i1, p0, p1, s, tag, why = x
        move, fee, fund = lg.trade_cash(fm, x[:5])
        h, l = a["h"][i0 + 1:i1 + 1], a["l"][i0 + 1:i1 + 1]
        lo, hi = (l.min(), h.max()) if len(h) else (p0, p0)
        atr = a["atr4"][i0] / a["c"][i0] * 100
        rows.append({"i0": i0, "i1": i1, "вход": pos.utc_full(a["t"][i0])[:-3], "выход": pos.utc_full(a["t"][i1])[:-3], "год": pd.Timestamp(int(a["t"][i0]), unit="s").year, "тип": BLUE.get(tag, tag), "причина": why.split(":")[0],
                     "цена_входа": round(p0), "цена_выхода": round(p1), "r": (move - fee - fund) / lg.NOTIONAL * 100, "ход": move / lg.NOTIONAL * 100, "издержки": fee / lg.NOTIONAL * 100, "фандинг": -fund / lg.NOTIONAL * 100,
                     "mfe": (1 - lo / p0) * 100, "mae": (1 - hi / p0) * 100, "часов": i1 - i0, "atr": atr, "mfe_atr": (1 - lo / p0) * 100 / atr, "d_G": a["f_d_G"][i0], "d_B": a["f_d_B"][i0], "отскок": (p1 / lo - 1) * 100})
    return pd.DataFrame(rows)


def inside(d):
    rows = []
    for k, g in [("все", d)] + list(d.groupby("тип")):
        m = g[g["r"] <= 0]
        rows.append({"тип": k, "n": len(g), "плюс_%": round((g["r"] > 0).mean() * 100), "итог": round(g["r"].sum(), 1), "минусовых": len(m), "их_сумма": round(m["r"].sum(), 1), "средний_минус": round(m["r"].mean(), 2),
                     "шло_в_плюс_медиана_%": round(m["mfe"].median(), 2), "против_медиана_%": round(m["mae"].median(), 2), "часов_медиана": round(m["часов"].median()), "был_плюс≥1%": round((m["mfe"] >= 1).mean() * 100), "был_плюс≥2%": round((m["mfe"] >= 2).mean() * 100), "был_плюс≥1ATR": round((m["mfe_atr"] >= 1).mean() * 100)})
    return pd.DataFrame(rows)


def by_reason(d):
    rows = []
    for k, g in d.groupby("причина"):
        rows.append({"причина": k, "n": len(g), "итог": round(g["r"].sum(), 1), "среднее": round(g["r"].mean(), 2), "лучший_ход_медиана_%": round(g["mfe"].median(), 2), "отскок_от_минимума_на_выходе_%": round(g["отскок"].median(), 2), "часов_медиана": round(g["часов"].median())})
    return pd.DataFrame(rows)


def entry_place(d):
    rows = []
    for nm, col, bins in (("от зелёной на входе, %", "d_G", [-100, -3, -1.5, -0.5, 100]), ("от голубой 4ч на входе, %", "d_B", [-100, -8, -3, 0, 3, 8, 100])):
        g = d.groupby(pd.cut(d[col], bins), observed=True)["r"].agg(["size", "sum", "mean"]).round(2)
        g.insert(0, "мера", nm)
        rows.append(g.reset_index(drop=False).rename(columns={col: "полоса"}))
    return pd.concat(rows)


def exit_only(a, fm, legs, k_stop, m_tp):
    """Те же шорты, тот же выход, но раньше него стоп k ATR и тейк m ATR от входа. В одном часе стоп раньше."""
    out = []
    for x in legs:
        if x[4] != -1:
            continue
        i0, i1, p0, p1, s = x[:5]
        atr = a["atr4"][i0] / a["c"][i0]
        h, l, o = a["h"][i0 + 1:i1 + 1], a["l"][i0 + 1:i1 + 1], a["o"][i0 + 1:i1 + 1]
        n = len(h)
        st_i, tp_i = n, n
        if k_stop is not None and n:
            lv = p0 * (1 + k_stop * atr)
            hit = h >= lv
            st_i = int(np.argmax(hit)) if hit.any() else n
        if m_tp is not None and n:
            lt = p0 * (1 - m_tp * atr)
            hit = l <= lt
            tp_i = int(np.argmax(hit)) if hit.any() else n
        if st_i <= tp_i and st_i < n:
            tr = (i0, i0 + 1 + st_i, p0, max(lv, o[st_i]), -1)
        elif tp_i < n:
            tr = (i0, i0 + 1 + tp_i, p0, min(lt, o[tp_i]), -1)
        else:
            tr = (i0, i1, p0, p1, -1)
        m, f, u = lg.trade_cash(fm, tr)
        out.append((m - f - u) / lg.NOTIONAL * 100)
    return float(np.sum(out))


def main():
    m, h1, h4, d1, fund = cw.load()
    del m
    a, _ = gc.er.prep(h1, h4, d1, fund)
    wd.add_runs(a)
    fma = lg.funding_marks(a, fund)
    legs = wd.run(a)
    d = frame(a, fma, legs)
    d.drop(columns=["i0", "i1"]).round(2).to_csv(pos.OUT / "words_shorts_all.csv", index=False)
    print("BTC шорты: сделок", len(d), "ход", round(d["ход"].sum(), 1), "издержки", round(d["издержки"].sum(), 1), "фандинг получен", round(d["фандинг"].sum(), 1), "итог", round(d["r"].sum(), 1), "| плюсовых", int((d["r"] > 0).sum()), round(d.loc[d["r"] > 0, "r"].sum(), 1), "| минусовых", int((d["r"] <= 0).sum()), round(d.loc[d["r"] <= 0, "r"].sum(), 1), flush=True)
    print(inside(d).to_string(index=False), flush=True)
    print(by_reason(d).to_string(index=False), flush=True)
    print(entry_place(d).to_string(index=False), flush=True)
    print(d.groupby("год")["r"].agg(["size", "sum"]).round(1).T.to_string(), flush=True)
    worst = d.nsmallest(15, "r")[["вход", "выход", "тип", "причина", "цена_входа", "цена_выхода", "r", "mfe", "mae", "часов", "d_G", "d_B"]].round(2)
    print(worst.to_string(index=False), flush=True)
    worst.to_csv(pos.OUT / "words_shorts_worst.csv", index=False)
    m2, h1e, h4e, d1e, fe = pd.read_pickle(gc.er.ETH_PKL)
    del m2
    h1e, h4e = cw.features(h1e, h4e, 1), cw.features(h4e, h1e, 4)
    e, _ = gc.er.prep(h1e, h4e, d1e, fe)
    wd.add_runs(e)
    bs, fbs = gc.load_bitstamp()
    wd.add_runs(bs)
    xr, fx = gc.load_xrp()
    wd.add_runs(xr)
    series = [("BTC", a, fma), ("ETH", e, lg.funding_marks(e, fe)), ("Bitstamp", bs, lg.funding_marks(bs, fbs)), ("XRP", xr, lg.funding_marks(xr, fx))]
    rows = []
    for k, tp in ((None, None), (None, 2), (None, 3), (None, 4), (None, 6), (3, None), (2, None), (3, 3), (3, 4), (3, 6), (2, 3), (2, 4), (2, 6)):
        row = {"стоп_ATR": k or "нет", "тейк_ATR": tp or "нет"}
        for nm, x, f in series:
            row[nm] = round(exit_only(x, f, wd.run(x), k, tp), 1)
        rows.append(row)
    t = pd.DataFrame(rows)
    t.to_csv(pos.OUT / "words_shorts_exits.csv", index=False)
    print(t.to_string(index=False), flush=True)
    for nm, x, f in series:
        dd = frame(x, f, wd.run(x))
        print(nm, inside(dd).iloc[:1][["n", "плюс_%", "итог", "минусовых", "их_сумма", "шло_в_плюс_медиана_%", "против_медиана_%", "был_плюс≥1%", "был_плюс≥2%", "был_плюс≥1ATR"]].to_dict("records"), flush=True)


if __name__ == "__main__":
    main()
