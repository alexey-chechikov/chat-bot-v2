"""Только биткоин. Карта ситуаций при входе (задание оператора: сколько дней над такой-то линией, как выстроены линии, куда смотрят, на каком расстоянии, какая последовательность пересечений) и размер по силе сигнала с весом только по прошлым сделкам.
Сделки: простое правило R без фильтра и с постоянным размером, BTC Binance 2018–2026 и Bitstamp 2014–17. Закрепление за линией — 2 закрытия 4ч, дни считаются от последнего закрепления, короткие проколы их не сбрасывают. Устойчиво = один знак среднего в 2018–21, 2022–26 и на Bitstamp, в каждом не меньше 8 сделок."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import btc_lab as bl  # noqa: E402
import plus as pl  # noqa: E402
import state_map as sm  # noqa: E402

pd.set_option("display.width", 230, "display.max_columns", 30, "display.max_rows", 200, "display.max_colwidth", 40)
OUT = bl.OUT
LINES = (("G", "f_run_G"), ("Y", "f_run_Y"), ("R", "f_run_R"), ("B", "f_run_B"))
BD = [-1, 1, 3, 7, 14, 30, 60, 100000]
LD = ["до 1", "1–3", "3–7", "7–14", "14–30", "30–60", "60+"]
BA = [-1000, 0, 0.5, 1, 2, 3, 5, 8, 1000]
LA = ["против", "0–0.5", "0.5–1", "1–2", "2–3", "3–5", "5–8", "8+"]


def flips(a):
    """Часов с последнего закрепления за каждой линией и сторона закрепления; список событий для последовательности."""
    j = a["j"]
    n = len(j)
    new4 = np.r_[True, j[1:] != j[:-1]]
    out = {}
    events = []
    for nm, col in LINES:
        r = a[col]
        st, side = np.zeros(n), np.zeros(n)
        last, cur = 0, 0
        for i in range(n):
            if new4[i] and abs(r[i]) == 2:
                last, cur = i, int(np.sign(r[i]))
                events.append((i, nm + ("+" if cur > 0 else "−")))
            st[i], side[i] = i - last, cur
        out[nm] = (st / 24, side)
    events.sort()
    return out, events


def feats(a, f, legs, name):
    fl, ev = flips(a)
    ei = np.array([e[0] for e in ev])
    rk, _ = pl.layer(a)
    F, G, Y, R, B, atr = a["f_close"], a["f_G"], a["f_Y"], a["f_R"], a["f_B"], a["atr4"]
    rows = []
    prev_r, prev_end = 0.0, -1
    for x in legs:
        i, s = x[0], x[4]
        r = pl.unit(f, [x])[0][0]
        z = max(i - 24, 0)
        order = "".join(q for _, q in sorted(((G[i], "G"), (Y[i], "Y"), (R[i], "R")), reverse=True))
        look = int(s * (G[i] - G[z]) > 0) + int(s * (Y[i] - Y[z]) > 0) + int(s * (R[i] - R[z]) > 0)
        k = int(np.searchsorted(ei, i, side="right"))
        seq = " ".join(e[1] for e in ev[max(k - 3, 0):k])
        row = {"ряд": name, "t0": sm.utc(a["t"][i]), "год": pd.Timestamp(int(a["t"][i]), unit="s").year, "s": s, "r": r, "часов": x[1] - i, "порядок": order, "смотрят_по_сделке": look, "последовательность": seq,
               "наклон_синей": s * a["s_b4"][i], "разброс": (max(G[i], Y[i], R[i]) - min(G[i], Y[i], R[i])) / atr[i], "ранг_V": rk[i], "пауза_ч": i - prev_end if prev_end >= 0 else 9999, "прошлая": "плюс" if prev_r > 0 else "минус"}
        for nm, _ in LINES:
            st, sd = fl[nm]
            row["дней_" + nm] = st[i] if sd[i] == s else 0.0
        for nm, v in (("G", G), ("Y", Y), ("R", R), ("B", B)):
            row["от_" + nm] = s * (F[i] - v[i]) / atr[i]
        rows.append(row)
        prev_r, prev_end = r, x[1]
    return pd.DataFrame(rows)


def table(d, col, bins=None, labels=None, min_each=8):
    g = pd.cut(d[col], bins, labels=labels) if bins is not None else d[col]
    rows = []
    for k in (labels if labels is not None else sorted(d[col].dropna().unique())):
        m = g == k
        if not m.any():
            continue
        q = d[m]
        a1, a2, a3 = q[(q["ряд"] == "BTC") & (q["год"] <= 2021)], q[(q["ряд"] == "BTC") & (q["год"] >= 2022)], q[q["ряд"] == "Bitstamp"]
        btc = q[q["ряд"] == "BTC"]
        means = [z["r"].mean() if len(z) else np.nan for z in (a1, a2, a3)]
        ok = all(len(z) >= min_each for z in (a1, a2, a3))
        rows.append({"признак": col, "значение": str(k), "n_BTC": len(btc), "плюс_%": round((btc["r"] > 0).mean() * 100) if len(btc) else 0, "сумма_BTC": round(btc["r"].sum(), 1), "ср_18–21": round(means[0], 2), "ср_22–26": round(means[1], 2), "ср_Bitstamp": round(means[2], 2), "n_18–21/22–26/Bs": f"{len(a1)}/{len(a2)}/{len(a3)}", "устойчиво": ("+" if ok and min(means) > 0 else "−" if ok and max(means) < 0 else "")})
    return pd.DataFrame(rows)


def maps(d):
    res = {}
    for s, nm in ((1, "ЛОНГ"), (-1, "ШОРТ")):
        q = d[d["s"] == s]
        parts = [table(q, "дней_B", BD, LD), table(q, "дней_Y", BD, LD), table(q, "дней_R", BD, LD), table(q, "порядок"), table(q, "смотрят_по_сделке"), table(q, "наклон_синей", [-1000, -2, -0.5, 0.5, 2, 1000], ["<−2", "−2…−0.5", "плоско", "0.5…2", ">2"]), table(q, "от_G", BA, LA), table(q, "от_Y", BA, LA), table(q, "от_R", BA, LA), table(q, "от_B", BA, LA), table(q, "разброс", [-1, 1, 2, 3, 5, 1000], ["до 1", "1–2", "2–3", "3–5", "5+"]), table(q, "ранг_V", [-1, 0.2, 0.4, 0.6, 0.8, 2], ["0–20", "20–40", "40–60", "60–80", "80–100"]), table(q, "пауза_ч", [-1, 12, 48, 168, 720, 100000], ["до 12ч", "12–48ч", "2–7д", "7–30д", "30д+"]), table(q, "прошлая")]
        t = pd.concat(parts, ignore_index=True)
        t.insert(0, "сторона", nm)
        res[nm] = t
    return res


def walk(trades, cls, g0=2020):
    """Вес по силе класса только по прошлым годам. Прошлое: BTC и Bitstamp до начала года. Вес = средний итог класса (со сжатием к общему среднему) / общее среднее, в пределах 0.25–2. Если общее среднее не больше нуля, вес 1."""
    d = trades.copy()
    d["c"] = cls
    d["w"] = 1.0
    for y in sorted(d.loc[(d["ряд"] == "BTC") & (d["год"] >= g0), "год"].unique()):
        past = d[(d["ряд"] == "Bitstamp") | (d["год"] < y)]
        g = past["r"].mean()
        if g <= 0:
            continue
        m = (past.groupby("c")["r"].sum() + 20 * g) / (past.groupby("c")["r"].size() + 20)
        w = (m / g).clip(0.25, 2.0)
        k = (d["ряд"] == "BTC") & (d["год"] == y)
        d.loc[k, "w"] = d.loc[k, "c"].map(w).fillna(1.0)
    return d["w"].to_numpy()


def eval_w(a, f, legs, w, from_year=2020):
    t0 = pd.to_datetime(a["t"][[x[0] for x in legs]], unit="s").year
    m = t0 >= from_year
    lg2 = [(*x[:7], float(q)) for x, q, ok in zip(legs, w, m) if ok]
    if not lg2:
        return {}
    avg = float(np.mean([x[7] for x in lg2]))
    lg2 = [(*x[:7], x[7] / avg) for x in lg2]
    st = pl.stats(a, f, lg2)
    return {"итог": st["итог"], "просадка": st["просадка"], "отн": st["отн"], "с2025": st["с2025"], "n": st["n"]}


def main():
    (a, f, lay), (b, fb, layb) = bl.load()
    la = bl.run(a, lay, rank_th=None, size=False, cut=bl.CUT)
    lb = bl.run(b, layb, rank_th=None, size=False)
    d = pd.concat([feats(a, f, la, "BTC"), feats(b, fb, lb, "Bitstamp")], ignore_index=True)
    d.to_csv(OUT / "btc_map_trades.csv", index=False)
    res = maps(d)
    allt = pd.concat(res.values(), ignore_index=True)
    allt.to_csv(OUT / "btc_map.csv", index=False)
    show = ["значение", "n_BTC", "плюс_%", "сумма_BTC", "ср_18–21", "ср_22–26", "ср_Bitstamp", "n_18–21/22–26/Bs", "устойчиво"]
    for nm, t in res.items():
        for ft in ("дней_B", "порядок", "смотрят_по_сделке", "наклон_синей", "от_R", "ранг_V"):
            print(f"== {nm} {ft}", flush=True)
            print(t[t["признак"] == ft][show].to_string(index=False), flush=True)
        print(f"== {nm}: все устойчивые значения", flush=True)
        print(t[t["устойчиво"] != ""][["признак", *show]].sort_values("ср_22–26").to_string(index=False), flush=True)
    q = d[d["ряд"] == "BTC"]
    for s, nm in ((1, "ЛОНГ"), (-1, "ШОРТ")):
        g = q[q["s"] == s].groupby("последовательность")["r"].agg(["size", "sum", "mean"]).round(2)
        g = g[g["size"] >= 12].sort_values("mean")
        print(f"== {nm}: последние 3 закрепления перед входом, не меньше 12 сделок", flush=True)
        print(pd.concat([g.head(5), g.tail(5)]).drop_duplicates().to_string(), flush=True)
    btc = d[d["ряд"] == "BTC"].reset_index(drop=True)
    bk = pd.cut(d["дней_B"], BD, labels=LD).astype(str)
    side = d["s"].map({1: "L", -1: "S"})
    classes = {"сторона": side, "сторона и дни за синей": side + bk, "сторона и порядок": side + d["порядок"], "сторона, дни, порядок": side + bk + d["порядок"], "сторона и ранг V": side + pd.cut(d["ранг_V"], [-1, 0.2, 0.4, 0.6, 0.8, 2]).astype(str), "сторона, ранг V, смотрят": side + pd.cut(d["ранг_V"], [-1, 0.2, 0.4, 0.6, 0.8, 2]).astype(str) + d["смотрят_по_сделке"].astype(str), "сторона и расстояние до красной": side + pd.cut(d["от_R"], BA, labels=LA).astype(str)}
    rows = [{"вес": "постоянный", **eval_w(a, f, la, np.ones(len(la)))}]
    _, W = lay
    vol = np.array([W[x[0]] for x in la])
    rows.append({"вес": "от волатильности (Вин)", **eval_w(a, f, la, vol)})
    nb = len(la)
    for lab, c in classes.items():
        w = walk(d, c)[:nb]
        rows.append({"вес": "по прошлому: " + lab, **eval_w(a, f, la, w)})
        rows.append({"вес": "по прошлому и волатильность: " + lab, **eval_w(a, f, la, w * vol)})
    print("== размер по силе сигнала, вес только по прошлым годам, поток простого правила R, 2020–2026, средний вес приведён к 1", flush=True)
    print(pd.DataFrame(rows).to_string(index=False), flush=True)
    pd.DataFrame(rows).to_csv(OUT / "btc_rank_weights.csv", index=False)

    all_rules = {"cs": 1.0, "csyr": 1.0, "lby": 1.0, "lbg": 1.0, "fbl": 1.0, "fbs": 1.0}
    rows = []
    for lab, kw in (("все правила, выход шорта над G", {}), ("все правила, выход шорта над Y", {"sx": "Y"})):
        lg_a = bl.run(a, lay, rank_th=None, size=False, cut=bl.CUT, rules=all_rules, **kw)
        lg_b = bl.run(b, layb, rank_th=None, size=False, rules=all_rules, **kw)
        tr = pd.DataFrame([{"ряд": "BTC", "год": pd.Timestamp(int(a["t"][x[0]]), unit="s").year, "r": pl.unit(f, [x])[0][0]} for x in lg_a] + [{"ряд": "Bitstamp", "год": pd.Timestamp(int(b["t"][x[0]]), unit="s").year, "r": pl.unit(fb, [x])[0][0]} for x in lg_b])
        tags = pd.Series([x[5] for x in lg_a] + [x[5] for x in lg_b])
        w = walk(tr, tags)[:len(lg_a)]
        vol2 = np.array([W[x[0]] for x in lg_a])
        rows.append({"поток": lab, "вес": "постоянный", **eval_w(a, f, lg_a, np.ones(len(lg_a)))})
        rows.append({"поток": lab, "вес": "по силе правила, только прошлое", **eval_w(a, f, lg_a, w)})
        rows.append({"поток": lab, "вес": "по силе правила и волатильность", **eval_w(a, f, lg_a, w * vol2)})
    base = bl.run(a, lay, rank_th=None, size=False, cut=bl.CUT)
    rows.append({"поток": "простое правило R", "вес": "постоянный", **eval_w(a, f, base, np.ones(len(base)))})
    k1 = bl.run(a, lay, cut=bl.CUT)
    rows.append({"поток": "Простое+", "вес": "его вес", **eval_w(a, f, k1, np.array([x[7] for x in k1]))})
    print("== много правил с весом по силе правила, 2020–2026", flush=True)
    print(pd.DataFrame(rows).to_string(index=False), flush=True)
    pd.DataFrame(rows).to_csv(OUT / "btc_rank_rules.csv", index=False)


if __name__ == "__main__":
    main()
