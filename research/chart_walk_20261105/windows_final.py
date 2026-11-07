"""Окна на разметку оператору: замеры и обзорная картинка. На картинке нет сделок автомата: он размечает вслепую."""
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
import gpt_r3_check as gr  # noqa: E402
import ledger as lg  # noqa: E402
import pos  # noqa: E402
import segment1_chart as sc1  # noqa: E402
import state_card as sc  # noqa: E402
import state_map as sm  # noqa: E402
import words2 as w2  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 30)
WINS = ((1, "2026-02-23", "2026-04-06"), (2, "2026-01-12", "2026-02-23"), (3, "2025-08-04", "2025-09-22"), (4, "2024-12-30", "2025-02-17"), (5, "2025-10-27", "2025-11-28"), (6, "2024-10-14", "2024-11-25"))


def main():
    a, fm, _ = sc.load_coin("BTC")
    legs = w2.run(a, **w2.MAIN26)
    t, c, h, l = a["t"], a["c"], a["h"], a["l"]
    eq = lg.equity(a, fm, [x[:5] for x in legs])[0] / lg.NOTIONAL * 100
    i0 = np.array([x[0] for x in legs])
    r = np.array([w2.net(fm, x) for x in legs])
    side = np.array([x[4] for x in legs])
    p = gr.paired(a, fm, legs)
    cnt = np.zeros(len(t))
    np.add.at(cnt, i0, 1)
    saw = pd.Series(cnt).rolling(240, min_periods=1).sum().to_numpy() >= 6
    rows = []
    for n, x, z in WINS:
        X, Z = sm.T(x), sm.T(z)
        w = (t >= X) & (t < Z)
        k = np.where(w)[0]
        tr = (t[i0] >= X) & (t[i0] < Z)
        pk = (p["t0"] >= X) & (p["t0"] < Z)
        rows.append({"№": n, "с": x, "по": z, "счёт": round(eq[k[-1]] - eq[k[0]], 1), "просадка": round((eq[k] - np.maximum.accumulate(eq[k])).min(), 1), "сделок": int(tr.sum()), "лонг": round(r[tr & (side == 1)].sum(), 1), "шорт": round(r[tr & (side == -1)].sum(), 1), "серое_%": round(((a["flat"] == 2) | saw)[w].mean() * 100), "ход_%": round((c[k[-1]] / c[k[0]] - 1) * 100, 1), "размах_%": round((h[k].max() / l[k].min() - 1) * 100, 1), "x01": round((p["новый"] - p["старый"])[pk].sum(), 1)})
    d = pd.DataFrame(rows)
    d.to_csv(pos.OUT / "windows_final.csv", index=False)
    print(d.to_string(index=False), flush=True)

    fig, ax = plt.subplots(figsize=(14, 5), dpi=110)
    fig.patch.set_facecolor(sc1.SURFACE)
    sc1.style(ax)
    m = t >= sm.T("2024-09-01")
    ax.plot(sc1.num(t[m]), c[m], color=sc1.INK, lw=1.1, zorder=3)
    top = c[m].max() * 1.04
    for x, z, _ in sm.WINDOWS:
        ax.axvspan(sc1.num(sm.T(x)), sc1.num(sm.T(z)), color=sc1.MUTED, alpha=0.16, lw=0, zorder=1)
    for n, x, z in WINS:
        ax.axvspan(sc1.num(sm.T(x)), sc1.num(sm.T(z)), color=sc1.C_B4, alpha=0.26, lw=0, zorder=1)
        ax.text(sc1.num((sm.T(x) + sm.T(z)) / 2), top, str(n), color=sc1.INK, fontsize=13, fontweight="bold", ha="center", va="top", zorder=5)
    ax.set_ylim(c[m].min() * 0.95, top * 1.01)
    ax.set_xlim(sc1.num(t[m][0]), sc1.num(t[m][-1]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m.%y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.set_title("BTC: окна на разметку (голубые, с номерами). Серые — уже разобраны. Сделок автомата на картинке нет", color=sc1.INK, fontsize=11, loc="left")
    out = pos.OUT / "windows_final.png"
    fig.savefig(out, bbox_inches="tight", facecolor=sc1.SURFACE)
    print(out, flush=True)


if __name__ == "__main__":
    main()
