"""Где теряет простое правило на BTC и какие окна спорные. Разбивка убытка: сторона, длительность, фаза на входе, расстояние от зелёной, отданная прибыль, серии убытков.
Окна 28 дней, шаг 7, 2023–10.2026, размеченные оператором участки исключены. Категории: худший счёт, спор выхода R и G, спор с вариантом A + 2/6, цена прошла много, а правило нет, больше всего убыточных сделок."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import ledger as lg  # noqa: E402
import pos  # noqa: E402
import state_card as sc  # noqa: E402
import state_map as sm  # noqa: E402
import words2 as w2  # noqa: E402
import words3 as w3  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 40, "display.max_rows", 300)
S0 = dict(l_align=False, s_align=False)
MARKED = (("2024-10-14", "2025-05-15"), ("2025-08-04", "2025-09-22"), ("2025-11-28", "2026-04-06"), ("2026-06-09", "2026-07-22"), ("2026-09-29", "2026-11-07"))
DAYS = 28


def frame(a, fm, legs):
    t, h, l = a["t"], a["h"], a["l"]
    rows = []
    for x in legs:
        i0, i1, p0, p1, s = x[:5]
        hi = h[i0 + 1:i1 + 1].max() if i1 > i0 else p0
        lo = l[i0 + 1:i1 + 1].min() if i1 > i0 else p0
        mfe = ((hi / p0 - 1) if s == 1 else (1 - lo / p0)) * 100
        mae = ((lo / p0 - 1) if s == 1 else (1 - hi / p0)) * 100
        rows.append({"i0": i0, "i1": i1, "t0": t[i0], "год": pd.Timestamp(int(t[i0]), unit="s").year, "вход": sm.utc(t[i0]), "выход": sm.utc(t[i1]), "s": s, "p0": p0, "p1": p1, "r": w2.net(fm, x), "часов": i1 - i0, "mfe": mfe, "mae": mae,
                     "фаза": a["phase"][i0], "от_G": (a["f_close"][i0] - a["f_G"][i0]) / a["atr4"][i0], "флет": a["flat"][i0], "причина": x[6]})
    return pd.DataFrame(rows)


def block(d, lab):
    print(f"== {lab}: сделок {len(d)}, итог {d['r'].sum():+.1f}, плюсовых {d.loc[d['r'] > 0, 'r'].sum():+.1f}, минусовых {d.loc[d['r'] <= 0, 'r'].sum():+.1f}, доля плюсовых {(d['r'] > 0).mean() * 100:.0f}%", flush=True)
    g = d.groupby("s")["r"].agg(["count", "sum", "mean"]).round(2)
    print(g.to_string(), flush=True)
    dur = pd.cut(d["часов"], [-1, 24, 72, 168, 100000], labels=["до суток", "1–3 дня", "3–7 дней", "дольше недели"])
    print(d.groupby(dur, observed=True)["r"].agg(["count", "sum", "mean"]).round(2).to_string(), flush=True)
    print(d.groupby("фаза")["r"].agg(["count", "sum", "mean"]).round(2).sort_values("sum").to_string(), flush=True)
    far = pd.cut(d["s"] * d["от_G"], [-100, 0.5, 1, 2, 3, 100], labels=["до 0.5 ATR", "0.5–1", "1–2", "2–3", "дальше 3"])
    print(d.groupby([d["s"], far], observed=True)["r"].agg(["count", "sum", "mean"]).round(2).to_string(), flush=True)
    gave = d[(d["mfe"] >= 3) & (d["r"] <= 0)]
    print(f"был плюс ≥3%, закрыли в минус: {len(gave)} сделок, {gave['r'].sum():+.1f}, средний пик {gave['mfe'].mean():.1f}%", flush=True)
    win = d[d["r"] > 0]
    print(f"плюсовые отдали с пика: в среднем {(win['mfe'] - win['r']).mean():.1f}% при итоге {win['r'].mean():.1f}%", flush=True)
    never = d[d["mfe"] < 1]
    print(f"не дали и +1%: {len(never)} сделок, {never['r'].sum():+.1f}", flush=True)


def runs(d):
    rows, st, s = [], None, 0.0
    for k, r in enumerate(d["r"].to_numpy()):
        if r <= 0:
            st = k if st is None else st
            s += r
        elif st is not None:
            rows.append((s, k - st, d["вход"].iloc[st], d["выход"].iloc[k - 1]))
            st, s = None, 0.0
    return sorted(rows)[:6]


def windows(a, fm, cfgs):
    t, c, h, l = a["t"], a["c"], a["h"], a["l"]
    eq = {lab: lg.equity(a, fm, [x[:5] for x in legs])[0] / lg.NOTIONAL * 100 for lab, legs in cfgs.items()}
    fr = frame(a, fm, cfgs["R"])
    rows = []
    for st in pd.date_range("2023-01-02", "2026-10-08", freq="7D"):
        x, z = int(st.timestamp()), int(st.timestamp()) + DAYS * 86400
        if any(x < sm.T(q) and z > sm.T(p) for p, q in MARKED):
            continue
        k = np.where((t >= x) & (t < z))[0]
        if len(k) < 200:
            continue
        tr = fr[(fr["t0"] >= x) & (fr["t0"] < z)]
        row = {"с": st.strftime("%Y-%m-%d"), "по": pd.Timestamp(z, unit="s").strftime("%Y-%m-%d"), "ход_%": round((c[k[-1]] / c[k[0]] - 1) * 100, 1), "размах_%": round((h[k].max() / l[k].min() - 1) * 100, 1), "сделок": len(tr), "минусовых": int((tr["r"] <= 0).sum())}
        for lab in eq:
            row[lab] = round(eq[lab][k[-1]] - eq[lab][k[0]], 1)
        d = eq["R"][k] - np.maximum.accumulate(eq["R"][k])
        row["просадка_R"] = round(float(d.min()), 1)
        rows.append(row)
    return pd.DataFrame(rows)


def pick(d, key, n, used, asc=True):
    out = []
    for _, r in d.sort_values(key, ascending=asc).iterrows():
        x, z = sm.T(r["с"]), sm.T(r["по"])
        if any(x < q and z > p for p, q in used):
            continue
        out.append(r)
        used.append((x, z))
        if len(out) >= n:
            break
    return out


def main():
    a, fm, _ = sc.load_coin("BTC")
    legsR, legsG, legsA = w3.run(a, **S0, l_exit="R"), w3.run(a, **S0), w2.run(a, **w2.MAIN26)
    print("данные до", sm.utc(a["t"][-1]), flush=True)
    fr, fg = frame(a, fm, legsR), frame(a, fm, legsG)
    block(fr, "R вся история")
    block(fr[fr["год"] >= 2025], "R с 2025")
    block(fg[fg["год"] >= 2025], "G с 2025")
    print("годы R", fr.groupby("год")["r"].sum().round(1).to_dict(), flush=True)
    print("серии убытков R с 2023:", runs(fr[fr["год"] >= 2023]), flush=True)
    d = windows(a, fm, {"R": legsR, "G": legsG, "A": legsA})
    d["R-G"] = (d["R"] - d["G"]).round(1)
    d["R-A"] = (d["R"] - d["A"]).round(1)
    d["упущено"] = (d["ход_%"].abs() - d["R"]).round(1)
    d.to_csv(pos.OUT / "where_lose_windows.csv", index=False)
    show = ["с", "по", "ход_%", "размах_%", "сделок", "минусовых", "R", "G", "A", "просадка_R", "R-G", "R-A", "упущено"]
    for lab, key, asc in (("худший счёт R", "R", True), ("больше всего минусовых", "минусовых", False), ("R хуже G", "R-G", True), ("R лучше G", "R-G", False), ("R хуже A", "R-A", True), ("R лучше A", "R-A", False), ("упущено: цена прошла, правило нет", "упущено", False)):
        print("==", lab, flush=True)
        print(d.sort_values(key, ascending=asc).head(6)[show].to_string(index=False), flush=True)
    fr.to_csv(pos.OUT / "where_lose_trades_R.csv", index=False)


if __name__ == "__main__":
    main()
