"""C. Автомат v1 позициями на всю историю: типы сделок, причины закрытия, контроль, MFE и MAE, тейки и стопы. Правила — PREREG_positions.md."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import pos  # noqa: E402
import rules  # noqa: E402

pd.set_option("display.width", 250, "display.max_columns", 40, "display.max_rows", 200)
T0 = cw.T("2018-01-01")


def legs_frame(a, legs):
    t = a["t"]
    d = pd.DataFrame(legs)
    d["i0"] = np.searchsorted(t, d["t0"].to_numpy())
    d["i1"] = np.searchsorted(t, d["t1"].to_numpy())
    d["s"] = d["side"].map({"L": 1, "S": -1})
    d["pnl"] = d["s"] * (d["p1"] / d["p0"] - 1) * 100 - pos.COST - d["s"] * (a["F"][d["i1"]] - a["F"][d["i0"]])
    d["per"] = pos.period_of(d["t0"].to_numpy())
    d["why"] = d["why_close"].str.split(":").str[0]
    return d


def mfe_mae(a, d):
    mfe, mae, atr = [], [], []
    for r in d.itertuples():
        h = a["h"][r.i0 + 1:r.i1 + 1]
        l = a["l"][r.i0 + 1:r.i1 + 1]
        if len(h) == 0:
            mfe.append(0.0)
            mae.append(0.0)
        elif r.s == 1:
            mfe.append((h.max() / r.p0 - 1) * 100)
            mae.append((l.min() / r.p0 - 1) * 100)
        else:
            mfe.append((1 - l.min() / r.p0) * 100)
            mae.append((1 - h.max() / r.p0) * 100)
        atr.append(a["atr4"][r.i0] / a["c"][r.i0] * 100)
    d = d.copy()
    d["mfe"], d["mae"], d["atr"] = mfe, mae, atr
    return d


def manage(a, r, k_stop, m_tp):
    """Результат сделки при стопе k ATR и тейке m ATR от входа. В одном часе стоп раньше. Выход иначе — как у правила."""
    atr = a["atr4"][r.i0] / a["c"][r.i0]
    h = a["h"][r.i0 + 1:r.i1 + 1]
    l = a["l"][r.i0 + 1:r.i1 + 1]
    o = a["o"][r.i0 + 1:r.i1 + 1]
    s = r.s
    n = len(h)
    st_i, tp_i = n, n
    if k_stop is not None and n:
        lv = r.p0 * (1 - s * k_stop * atr)
        hit = (l <= lv) if s == 1 else (h >= lv)
        if hit.any():
            st_i = int(np.argmax(hit))
    if m_tp is not None and n:
        lvt = r.p0 * (1 + s * m_tp * atr)
        hit = (h >= lvt) if s == 1 else (l <= lvt)
        if hit.any():
            tp_i = int(np.argmax(hit))
    if st_i <= tp_i and st_i < n:
        px = min(lv, o[st_i]) if s == 1 else max(lv, o[st_i])
        i_ex = r.i0 + 1 + st_i
    elif tp_i < n:
        px = max(lvt, o[tp_i]) if s == 1 else min(lvt, o[tp_i])
        i_ex = r.i0 + 1 + tp_i
    else:
        px, i_ex = r.p1, r.i1
    return s * (px / r.p0 - 1) * 100 - pos.COST - s * (a["F"][i_ex] - a["F"][r.i0])


def group_table(a, d, key):
    rows = []
    for (side, k), g in d.groupby(["side", key]):
        st = pos.stats(g["pnl"].to_numpy())
        real = {p: float(g.loc[g["per"] == p, "pnl"].sum()) for p in pos.PER}
        ctl = pos.control_fixed(a, g["i0"].to_numpy(), (g["i1"] - g["i0"]).to_numpy(), int(g["s"].iloc[0]), n_rep=999)
        rk = pos.rank_row(real, ctl)
        doubt = rk["всё"]["лучше_случайного_%"] < 90 or sum(rk[p]["сумма_%"] < 0 for p in pos.PER) >= 2
        rows.append({"сторона": side, "тип": k, "n": st["n"], "среднее_%": st["среднее_%"], "медиана_%": st["медиана_%"], "плюс_%": st["плюс_%"], "сумма_%": st["сумма_%"], "просадка_%": pos.max_dd(g["pnl"].to_numpy()),
                     "A_%": rk["A"]["сумма_%"], "B_%": rk["B"]["сумма_%"], "C_%": rk["C"]["сумма_%"], "лучше_случайного_%": rk["всё"]["лучше_случайного_%"], "случайные_медиана_%": rk["всё"]["случайные_медиана_%"],
                     "сомнительная": bool(doubt)})
    return pd.DataFrame(rows)


def main():
    a, h1, h4, d1, fund = pos.load()
    t_end = int(a["t"][-1])
    d = legs_frame(a, rules.run(a, T0, t_end))
    d = mfe_mae(a, d)
    d.to_csv(pos.OUT / "history_v1_legs.csv", index=False)
    print("v1 позициями, всего сделок", len(d), pos.stats(d["pnl"].to_numpy()), "просадка", pos.max_dd(d["pnl"].to_numpy()))
    print({p: round(float(d.loc[d["per"] == p, "pnl"].sum()), 1) for p in pos.PER}, "лонг", round(float(d.loc[d["s"] == 1, "pnl"].sum()), 1), "шорт", round(float(d.loc[d["s"] == -1, "pnl"].sum()), 1))
    t1 = group_table(a, d, "tag")
    t2 = group_table(a, d, "why")
    t1.to_csv(pos.OUT / "history_v1_types.csv", index=False)
    t2.to_csv(pos.OUT / "history_v1_exits.csv", index=False)
    print(t1.to_string(index=False))
    print(t2.to_string(index=False))
    # MFE и MAE по типам: плюсовые против минусовых
    rows = []
    for (side, tag), g in d.groupby(["side", "tag"]):
        w = g[g["pnl"] > 0]
        los = g[g["pnl"] <= 0]
        rows.append({"сторона": side, "тип": tag, "n": len(g), "ATR_%": round(float(g["atr"].median()), 2), "MFE_медиана_%": round(float(g["mfe"].median()), 2), "MFE_q75_%": round(float(g["mfe"].quantile(.75)), 2),
                     "MAE_медиана_%": round(float(g["mae"].median()), 2), "MAE_плюсовых_q25_%": round(float(w["mae"].quantile(.25)), 2) if len(w) else None,
                     "MFE_минусовых_медиана_%": round(float(los["mfe"].median()), 2) if len(los) else None, "минусовых_с_MFE≥2%_%": round(float((los["mfe"] >= 2).mean() * 100), 1) if len(los) else None,
                     "часов_медиана": float((g["i1"] - g["i0"]).median())})
    t3 = pd.DataFrame(rows)
    t3.to_csv(pos.OUT / "history_v1_mfe.csv", index=False)
    print(t3.to_string(index=False))
    # тейки и стопы по типам
    rows = []
    for (side, tag), g in d.groupby(["side", "tag"]):
        if len(g) < 30:
            continue
        for k in (None, 1.0, 1.5, 2.0, 3.0):
            for m in (None, 1.0, 2.0, 3.0, 5.0):
                v = np.array([manage(a, r, k, m) for r in g.itertuples()])
                per = g["per"].to_numpy()
                rows.append({"сторона": side, "тип": tag, "стоп_ATR": k if k else 0, "тейк_ATR": m if m else 0, "n": len(g), "среднее_%": round(float(v.mean()), 3), "плюс_%": round(float((v > 0).mean() * 100), 1),
                             "сумма_%": round(float(v.sum()), 1), "просадка_%": pos.max_dd(v), "A_%": round(float(v[per == "A"].sum()), 1), "B_%": round(float(v[per == "B"].sum()), 1), "C_%": round(float(v[per == "C"].sum()), 1)})
    t4 = pd.DataFrame(rows)
    t4.to_csv(pos.OUT / "history_v1_tp_sl.csv", index=False)
    for (side, tag), g in t4.groupby(["сторона", "тип"]):
        print(side, tag)
        print(g.pivot(index="стоп_ATR", columns="тейк_ATR", values="сумма_%").to_string())
    # цель с допуском позициями
    rows = []
    for tol in (0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0):
        x = legs_frame(a, rules.run(a, T0, t_end, tol=tol))
        lng = x[x["s"] == 1]
        hit = lng["why"] == "цель"
        rows.append({"допуск_%": tol, "сделок": len(x), "всего_%": round(float(x["pnl"].sum()), 1), "просадка_%": pos.max_dd(x["pnl"].to_numpy()), "A_%": round(float(x.loc[x["per"] == "A", "pnl"].sum()), 1),
                     "B_%": round(float(x.loc[x["per"] == "B", "pnl"].sum()), 1), "C_%": round(float(x.loc[x["per"] == "C", "pnl"].sum()), 1), "лонгов": len(lng), "до_цели": int(hit.sum()),
                     "лонг_цель_%": round(float(lng.loc[hit, "pnl"].sum()), 1), "лонг_остальные_%": round(float(lng.loc[~hit, "pnl"].sum()), 1), "шорт_%": round(float(x.loc[x["s"] == -1, "pnl"].sum()), 1)})
    t5 = pd.DataFrame(rows)
    t5.to_csv(pos.OUT / "history_v1_tol.csv", index=False)
    print(t5.to_string(index=False))


if __name__ == "__main__":
    main()
