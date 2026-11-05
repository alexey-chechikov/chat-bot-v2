"""Картинки автомата под портрет: сделки в трёх окнах, которые оператор разобрал, и кривая счёта против прошлой версии на четырёх рядах."""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import entry_common as ec  # noqa: E402
import gpt_check as gc  # noqa: E402
import ledger as lg  # noqa: E402
import pos  # noqa: E402
import segment1_chart as sc  # noqa: E402
import words as wd  # noqa: E402
import words2 as w2  # noqa: E402
import words_chart as wc  # noqa: E402

ROWS = (("2025-11-22", "2026-01-05", 82500, 95500, 3), ("2026-06-05", "2026-07-22", 57000, 68000, 3), ("2026-09-20", "2026-11-06", 75500, 88500, 3))


def screens(a, fm, legs, h4):
    fig, axes = plt.subplots(3, 1, figsize=(17, 15), dpi=110, gridspec_kw={"hspace": 0.13})
    fig.patch.set_facecolor(sc.SURFACE)
    t = a["t"]
    for ax, (x0, x1, y0, y1, step) in zip(axes, ROWS):
        sc.style(ax)
        A, Z = cw.T(x0), cw.T(x1)
        s4 = h4[(h4.index >= A) & (h4.index < Z)]
        sc.candles(ax, s4, 14400)
        xx = sc.num(s4.index.to_numpy() + 7200)
        for col, c, lw, ls, nm in (("G", sc.C_G, 1.3, "-", "зелёная"), ("Y", sc.C_Y, 1.3, "-", "жёлтая"), ("R", sc.C_R, 1.3, "-", "красная"), ("B", sc.C_B4, 2.1, "-", "голубая 4ч"), ("B1", sc.C_B1, 1.1, (0, (4, 2)), "голубая 1ч")):
            ax.plot(xx, s4[col], color=c, lw=lw, ls=ls, label=nm)
        lab_n = 0
        for x in legs:
            t0, t1 = t[x[0]], t[x[1]]
            if t1 < A or t0 >= Z:
                continue
            ax.axvspan(sc.num(max(t0, A)), sc.num(min(t1, Z)), color=sc.TINT_L if x[4] == 1 else sc.TINT_S, alpha=0.30, lw=0, zorder=0)
            if t0 >= A:
                ax.scatter(sc.num(t0), x[2], marker="^" if x[4] == 1 else "v", s=70, color=wc.C_L if x[4] == 1 else wc.C_S, edgecolor="#0b0e14", lw=0.7, zorder=6)
            if t1 < Z:
                ax.scatter(sc.num(t1), x[3], marker="x", s=38, color=sc.INK, lw=1.3, zorder=6)
            r = w2.net(fm, x)
            if abs(r) >= 1.5 and t0 >= A and t1 < Z:
                ax.text(sc.num((t0 + t1) / 2), y1 - (y1 - y0) * (0.012 + 0.03 * (lab_n % 2)), f"{r:+.1f}", color=sc.INK, fontsize=8.5, ha="center", va="top", zorder=7)
                lab_n += 1
        for ts, _, _ in w2.MARKS2:
            tt = cw.T(ts)
            if A <= tt < Z:
                i = int(np.searchsorted(t, tt))
                ax.scatter(sc.num(tt), a["c"][i], s=170, facecolors="none", edgecolors="#f9fafb", lw=1.4, zorder=5)
        ax.set_ylim(y0, y1)
        ax.set_xlim(sc.num(A), sc.num(Z))
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=step))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    axes[0].legend(loc="lower right", ncol=5, frameon=False, labelcolor=sc.INK, fontsize=9.5, handlelength=2.2)
    axes[0].set_title("BTC 4ч, твои три окна: вариант A (лонги все, шорты по описанию, выходы прошлые). ▲ лонг, ▼ шорт, × выход, белый круг — твоё действие из записки, числа — сделка в %", color=sc.INK, fontsize=12, loc="left", pad=10)
    fig.savefig(pos.OUT / "words2_windows.png", bbox_inches="tight", facecolor=sc.SURFACE)


def equity(series):
    fig, axes = plt.subplots(2, 2, figsize=(15, 8.5), dpi=110, gridspec_kw={"hspace": 0.28, "wspace": 0.1})
    fig.patch.set_facecolor(sc.SURFACE)
    for ax, (nm, a, fm) in zip(axes.ravel(), series):
        sc.style(ax)
        i0 = a["i0"]
        x = sc.num(a["t"][i0::24])
        old = lg.equity(a, fm, [q[:5] for q in wd.run(a)])[0]
        new = lg.equity(a, fm, [q[:5] for q in w2.run(a, **w2.MAIN)])[0]
        ax.plot(x, old[i0::24] / lg.NOTIONAL * 100, color=sc.MUTED, lw=1.3, label="было")
        ax.plot(x, new[i0::24] / lg.NOTIONAL * 100, color=sc.C_B4, lw=2.0, label="стало")
        ax.axhline(0, color=sc.MUTED, lw=0.7)
        dd = lambda e: lg.drawdown(e[i0:], e[i0:], a["t"][i0:])[0] / lg.NOTIONAL * 100
        ax.set_title(f"{nm}: {old[-1] / lg.NOTIONAL * 100:+.0f} → {new[-1] / lg.NOTIONAL * 100:+.0f}, просадка {dd(old):.0f} → {dd(new):.0f}", color=sc.INK, fontsize=12, loc="left")
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    axes[0][0].legend(loc="upper left", frameon=False, labelcolor=sc.INK, fontsize=10)
    fig.suptitle("Кривая счёта: было и вариант A (шорты только по описанию прибыльных входов), % номинала входа (1% = \\$10), издержки и фандинг учтены", color=sc.INK, fontsize=13, x=0.125, ha="left", y=0.96)
    fig.savefig(pos.OUT / "words2_equity.png", bbox_inches="tight", facecolor=sc.SURFACE)


def main():
    m, h1, h4, d1, fund = cw.load()
    del m
    a, h4f = gc.er.prep(h1, h4, d1, fund)
    wd.add_runs(a)
    fm = lg.funding_marks(a, fund)
    screens(a, fm, w2.run(a, **w2.MAIN), h4f)
    series = ec.load_all()
    equity([("BTC 2018–26", series[0][1], series[0][2]), ("ETH 2018–26", series[1][1], series[1][2]), ("BTC Bitstamp 2014–17", series[2][1], series[2][2]), ("XRP 2020–26", series[3][1], series[3][2])])


if __name__ == "__main__":
    main()
