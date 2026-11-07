"""Вторая часть: сделки простого правила в выбранных спорных окнах и признаки на входе, по которым видно, где короткие убытки: разброс цветных, наклон синей, пауза после прошлой сделки, итог прошлой сделки. BTC и ETH, замер, не проверка. И картинка окон."""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import ledger as lg  # noqa: E402
import pos  # noqa: E402
import segment1_chart as sc1  # noqa: E402
import state_card as sc  # noqa: E402
import state_map as sm  # noqa: E402
import where_lose as wl  # noqa: E402
import words2 as w2  # noqa: E402
import words3 as w3  # noqa: E402
import words3_look as wlook  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 40, "display.max_rows", 300)
S0 = wl.S0
WINS = ((1, "2024-03-18", "2024-04-29"), (2, "2023-05-15", "2023-06-19"), (3, "2023-12-18", "2024-01-29"), (4, "2024-08-05", "2024-09-09"), (5, "2023-08-28", "2023-09-28"), (6, "2026-08-24", "2026-09-28"), (7, "2025-10-27", "2025-11-28"), (8, "2024-02-12", "2024-03-18"), (9, "2025-05-19", "2025-07-14"), (10, "2026-04-06", "2026-06-08"))


def features(a, fm, legs):
    d = wl.frame(a, fm, legs)
    i0 = d["i0"].to_numpy()
    atr = a["atr4"][i0]
    d["разброс"] = (np.maximum.reduce([a["f_G"][i0], a["f_Y"][i0], a["f_R"][i0]]) - np.minimum.reduce([a["f_G"][i0], a["f_Y"][i0], a["f_R"][i0]])) / atr
    d["наклон_синей"] = np.abs(a["s_b4"][i0])
    d["от_синей"] = np.abs(a["f_close"][i0] - a["f_B"][i0]) / atr
    prev_end = np.r_[-1000, d["i1"].to_numpy()[:-1]]
    d["пауза"] = i0 - prev_end
    d["прошлая"] = np.r_[0.0, d["r"].to_numpy()[:-1]]
    return d


def table(d, col, bins, labels):
    b = pd.cut(d[col], bins, labels=labels)
    g = d.groupby(b, observed=True)
    return g.agg(n=("r", "size"), итог=("r", "sum"), на_сделку=("r", "mean"), до_суток=("часов", lambda x: round((x <= 24).mean() * 100))).round(2)


def main():
    a, fm, _ = sc.load_coin("BTC")
    t, c, h, l = a["t"], a["c"], a["h"], a["l"]
    legsR, legsG, legsA = w3.run(a, **S0, l_exit="R"), w3.run(a, **S0), w2.run(a, **w2.MAIN26)
    eq = {lab: lg.equity(a, fm, [x[:5] for x in legs])[0] / lg.NOTIONAL * 100 for lab, legs in (("R", legsR), ("G", legsG), ("A", legsA))}
    fr = wl.frame(a, fm, legsR)
    rows = []
    for n, x, z in WINS:
        X, Z = sm.T(x), sm.T(z)
        k = np.where((t >= X) & (t < Z))[0]
        tr = fr[(fr["t0"] >= X) & (fr["t0"] < Z)]
        rows.append({"№": n, "с": x, "по": z, "ход_%": round((c[k[-1]] / c[k[0]] - 1) * 100, 1), "размах_%": round((h[k].max() / l[k].min() - 1) * 100, 1), "сделок": len(tr), "минус": int((tr["r"] <= 0).sum()), "R": round(eq["R"][k[-1]] - eq["R"][k[0]], 1), "G": round(eq["G"][k[-1]] - eq["G"][k[0]], 1), "A": round(eq["A"][k[-1]] - eq["A"][k[0]], 1)})
        print(f"--- окно {n} {x} – {z}", flush=True)
        print(tr[["вход", "выход", "s", "p0", "p1", "r", "mfe", "часов", "фаза"]].round(2).to_string(index=False), flush=True)
    d = pd.DataFrame(rows)
    d.to_csv(pos.OUT / "where_lose_picked.csv", index=False)
    print(d.to_string(index=False), flush=True)
    for k, ax, f in wlook.series()[:2]:
        fe = features(ax, f, w3.run(ax, **S0, l_exit="R"))
        print("==", k, "R, вся история", flush=True)
        print("разброс цветных, ATR", table(fe, "разброс", [-1, 1, 2, 3, 5, 8, 1000], ["до 1", "1–2", "2–3", "3–5", "5–8", ">8"]).to_string(), flush=True)
        print("наклон синей за 5 дней, ATR", table(fe, "наклон_синей", [-1, 1, 2, 4, 8, 1000], ["до 1", "1–2", "2–4", "4–8", ">8"]).to_string(), flush=True)
        print("от синей, ATR", table(fe, "от_синей", [-1, 1, 2, 4, 8, 1000], ["до 1", "1–2", "2–4", "4–8", ">8"]).to_string(), flush=True)
        print("пауза после прошлой сделки, ч", table(fe, "пауза", [-1, 0, 12, 48, 168, 100000], ["сразу", "до 12", "12–48", "2–7 дней", ">7 дней"]).to_string(), flush=True)
        fe["после"] = np.where(fe["прошлая"] > 0, "после плюсовой", "после минусовой")
        print(fe.groupby(["s", "после"])["r"].agg(["size", "sum", "mean"]).round(2).to_string(), flush=True)
    fig, axes = plt.subplots(2, 1, figsize=(14, 6.6), dpi=110, sharex=True, gridspec_kw={"height_ratios": [1.5, 1]})
    fig.patch.set_facecolor(sc1.SURFACE)
    m = t >= sm.T("2023-01-01")
    ax = axes[0]
    sc1.style(ax)
    ax.plot(sc1.num(t[m]), c[m], color=sc1.INK, lw=1.1, zorder=3)
    top = c[m].max() * 1.05
    for x, z, _ in sm.WINDOWS + (("2024-10-14", "2025-02-20", ""), ("2025-08-04", "2025-09-22", ""), ("2026-01-03", "2026-04-06", "")):
        ax.axvspan(sc1.num(sm.T(x)), sc1.num(sm.T(z)), color=sc1.MUTED, alpha=0.14, lw=0, zorder=1)
        axes[1].axvspan(sc1.num(sm.T(x)), sc1.num(sm.T(z)), color=sc1.MUTED, alpha=0.14, lw=0, zorder=1)
    for n, x, z in WINS:
        for q in axes:
            q.axvspan(sc1.num(sm.T(x)), sc1.num(sm.T(z)), color=sc1.C_B4, alpha=0.24, lw=0, zorder=1)
        ax.text(sc1.num((sm.T(x) + sm.T(z)) / 2), top, str(n), color=sc1.INK, fontsize=12, fontweight="bold", ha="center", va="top", zorder=5)
    ax.set_ylim(c[m].min() * 0.9, top * 1.02)
    ax.set_title("BTC: новые окна (голубые, с номерами). Серые уже разобраны", color=sc1.INK, fontsize=11, loc="left")
    ax = axes[1]
    sc1.style(ax)
    i0 = int(np.argmax(m))
    ax.plot(sc1.num(t[m]), eq["R"][m] - eq["R"][i0], color="#e4572e", lw=1.8, zorder=3, label="Простое, выход под красной")
    ax.plot(sc1.num(t[m]), eq["G"][m] - eq["G"][i0], color=sc1.C_B4, lw=1.4, zorder=3, label="Простое, выход под зелёной")
    ax.plot(sc1.num(t[m]), eq["A"][m] - eq["A"][i0], color=sc1.MUTED, lw=1.2, zorder=3, label="Вариант A + 2/6")
    ax.legend(loc="upper left", frameon=False, labelcolor=sc1.INK, fontsize=10)
    ax.set_title("Счёт с 01.2023: % от $1000 на сделку", color=sc1.INK, fontsize=11, loc="left")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m.%y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax.set_xlim(sc1.num(t[m][0]), sc1.num(t[m][-1]))
    fig.tight_layout()
    out = pos.OUT / "where_lose.png"
    fig.savefig(out, bbox_inches="tight", facecolor=sc1.SURFACE)
    print(out, flush=True)


if __name__ == "__main__":
    main()
