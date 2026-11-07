"""Картинка для оператора: кривая BTC по простому правилу из его записок против индикатора A + 2/6, и сделки простого правила в его окнах."""
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
import state_map as sm  # noqa: E402
import words2 as w2  # noqa: E402
import words3 as w3  # noqa: E402
import words3_look as wl  # noqa: E402

pd.set_option("display.width", 220, "display.max_columns", 30, "display.max_rows", 200)
S0 = dict(l_align=False, s_align=False)
LINES = (("Индикатор A + 2/6", None, sc1.MUTED, 1.6), ("Выход под зелёной", S0, sc1.C_B4, 2.2), ("Выход под красной", {**S0, "l_exit": "R"}, "#e4572e", 2.2))
WINS = (("2024-10-14", "2024-11-25"), ("2024-12-30", "2025-02-17"), ("2025-08-04", "2025-09-22"), ("2025-10-27", "2025-11-28"), ("2026-01-12", "2026-02-23"), ("2026-02-23", "2026-04-06"))


def main():
    k, a, f = wl.series()[0]
    t = a["t"]
    b = a["i0"]
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.2), dpi=110, gridspec_kw={"width_ratios": [1.25, 1]})
    fig.patch.set_facecolor(sc1.SURFACE)
    cut = sm.T("2025-01-01")
    ib = int(np.searchsorted(t, cut))
    curves = {}
    for lab, kw, col, lw in LINES:
        legs = w2.run(a, **w2.MAIN26) if kw is None else w3.run(a, **kw)
        eq = lg.equity(a, f, [x[:5] for x in legs])[0] / lg.NOTIONAL * 100
        curves[lab] = eq
        axes[0].plot(sc1.num(t[b:]), eq[b:], color=col, lw=lw, zorder=3, label=f"{lab}: {eq[-1]:+.0f}")
        axes[1].plot(sc1.num(t[ib:]), eq[ib:] - eq[ib], color=col, lw=lw, zorder=3, label=f"{lab}: {eq[-1] - eq[ib]:+.0f}")
    for ax in axes:
        sc1.style(ax)
        ax.axhline(0, color=sc1.MUTED, lw=0.7, zorder=1)
        ax.legend(loc="lower right" if ax is axes[0] else "lower left", frameon=False, labelcolor=sc1.INK, fontsize=10)
    for x, z in WINS:
        axes[1].axvspan(sc1.num(sm.T(x)), sc1.num(sm.T(z)), color=sc1.C_B4, alpha=0.10, lw=0, zorder=0)
    axes[0].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    axes[0].xaxis.set_major_locator(mdates.YearLocator())
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%m.%y"))
    axes[1].xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    axes[1].set_xlim(sc1.num(t[ib]), sc1.num(t[-1]) + 40)
    axes[0].set_title("BTC, вся история: % от $1000 на сделку, с комиссией и фандингом", color=sc1.INK, fontsize=11, loc="left")
    axes[1].set_title("С 01.01.2025, с нуля. Голубым — твои окна", color=sc1.INK, fontsize=11, loc="left")
    fig.tight_layout()
    out = pos.OUT / "w3_curves.png"
    fig.savefig(out, bbox_inches="tight", facecolor=sc1.SURFACE)
    print(out, flush=True)
    legs = w3.run(a, **S0)
    rows = []
    for x in legs:
        if any(sm.T(p) <= t[x[0]] < sm.T(q) for p, q in WINS):
            rows.append({"вход": sm.utc(t[x[0]]), "выход": sm.utc(t[x[1]]), "с": "L" if x[4] == 1 else "S", "p0": round(x[2]), "p1": round(x[3]), "итог": round(w2.net(f, x), 2), "причина": x[6]})
    d = pd.DataFrame(rows)
    d.to_csv(pos.OUT / "w3_windows_simple.csv", index=False)
    print(d.to_string(index=False), flush=True)
    for k_ in (2, 3):
        rr = [x for x in w3.run(a, k=k_, **S0) if sm.T("2025-01-28") <= t[x[0]] < sm.T("2025-03-02")]
        print("k", k_, [(sm.utc(t[x[0]])[:11], sm.utc(t[x[1]])[:11], x[4], round(w2.net(f, x), 1)) for x in rr], flush=True)


if __name__ == "__main__":
    main()
