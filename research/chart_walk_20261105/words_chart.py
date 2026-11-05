"""Картинки автомата «слова оператора»: сделки на его трёх скринах и кривая счёта на четырёх рядах."""
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
import cw_data as cw  # noqa: E402
import gpt_check as gc  # noqa: E402
import ledger as lg  # noqa: E402
import pos  # noqa: E402
import segment1_chart as sc  # noqa: E402
import words as wd  # noqa: E402

ROWS = (("2025-02-20", "2025-03-22", 75500, 101000), ("2025-03-20", "2025-04-22", 73500, 96000), ("2025-04-18", "2025-05-15", 83000, 107500))
C_L, C_S = "#4ade80", "#fb7185"


def net(fm, x):
    m, f, u = lg.trade_cash(fm, x[:5])
    return (m - f - u) / lg.NOTIONAL * 100


def screens(a, fm, legs, h4):
    fig, axes = plt.subplots(3, 1, figsize=(17, 15), dpi=110, gridspec_kw={"hspace": 0.13})
    fig.patch.set_facecolor(sc.SURFACE)
    t = a["t"]
    for ax, (x0, x1, y0, y1) in zip(axes, ROWS):
        sc.style(ax)
        A, Z = cw.T(x0), cw.T(x1)
        s4 = h4[(h4.index >= A) & (h4.index < Z)]
        sc.candles(ax, s4, 14400)
        xx = sc.num(s4.index.to_numpy() + 7200)
        for col, c, lw, ls, nm in (("G", sc.C_G, 1.3, "-", "зелёная"), ("Y", sc.C_Y, 1.3, "-", "жёлтая"), ("R", sc.C_R, 1.3, "-", "красная"), ("B", sc.C_B4, 2.1, "-", "голубая 4ч"), ("B1", sc.C_B1, 1.1, (0, (4, 2)), "голубая 1ч")):
            ax.plot(xx, s4[col], color=c, lw=lw, ls=ls, label=nm)
        for x in legs:
            t0, t1 = t[x[0]], t[x[1]]
            if t1 < A or t0 >= Z:
                continue
            ax.axvspan(sc.num(max(t0, A)), sc.num(min(t1, Z)), color=sc.TINT_L if x[4] == 1 else sc.TINT_S, alpha=0.30, lw=0, zorder=0)
            if t0 >= A:
                ax.scatter(sc.num(t0), x[2], marker="^" if x[4] == 1 else "v", s=70, color=C_L if x[4] == 1 else C_S, edgecolor="#0b0e14", lw=0.7, zorder=6)
            if t1 < Z:
                ax.scatter(sc.num(t1), x[3], marker="x", s=38, color=sc.INK, lw=1.3, zorder=6)
            r = net(fm, x)
            if abs(r) >= 1.0 and t0 >= A and t1 < Z:
                ax.text(sc.num((t0 + t1) / 2), y1 - (y1 - y0) * 0.012, f"{r:+.1f}", color=sc.INK, fontsize=8.5, ha="center", va="top", zorder=7)
        for ts, _, _ in wd.MARKS:
            tt = cw.T(ts)
            if A <= tt < Z:
                i = int(np.searchsorted(t, tt))
                ax.scatter(sc.num(tt), a["c"][i], s=170, facecolors="none", edgecolors="#f9fafb", lw=1.4, zorder=5)
        ax.set_ylim(y0, y1)
        ax.set_xlim(sc.num(A), sc.num(Z))
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    axes[0].legend(loc="lower right", ncol=5, frameon=False, labelcolor=sc.INK, fontsize=9.5, handlelength=2.2)
    axes[0].set_title("BTC 4ч: сделки автомата по твоим словам. ▲ лонг, ▼ шорт, × выход, белый круг — твоё действие из записок, числа — результат сделки в %", color=sc.INK, fontsize=12, loc="left", pad=10)
    fig.savefig(pos.OUT / "words_screens.png", bbox_inches="tight", facecolor=sc.SURFACE)


def equity(series):
    fig, axes = plt.subplots(2, 2, figsize=(15, 8.5), dpi=110, gridspec_kw={"hspace": 0.28, "wspace": 0.1})
    fig.patch.set_facecolor(sc.SURFACE)
    for ax, (nm, a, fm, legs) in zip(axes.ravel(), series):
        sc.style(ax)
        eq, _, _, _ = lg.equity(a, fm, [x[:5] for x in legs])
        i0 = a["i0"]
        x = sc.num(a["t"][i0::24])
        y = eq[i0::24] / lg.NOTIONAL * 100
        ax.plot(x, y, color=sc.C_B4, lw=1.8)
        ax.axhline(0, color=sc.MUTED, lw=0.7)
        ax.fill_between(x, y, 0, color=sc.C_B4, alpha=0.10, lw=0)
        ax.set_title(f"{nm}: {len(legs)} сделок, итог {eq[-1] / lg.NOTIONAL * 100:+.0f}%", color=sc.INK, fontsize=12, loc="left")
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.suptitle("Кривая счёта по твоим словам, все сделки, \\$1000 на вход, издержки и фандинг учтены, % номинала входа (1% = \\$10)", color=sc.INK, fontsize=13, x=0.125, ha="left", y=0.96)
    fig.savefig(pos.OUT / "words_equity.png", bbox_inches="tight", facecolor=sc.SURFACE)


def main():
    m, h1, h4, d1, fund = cw.load()
    del m
    a, h4f = gc.er.prep(h1, h4, d1, fund)
    wd.add_runs(a)
    fm = lg.funding_marks(a, fund)
    legs = wd.run(a)
    screens(a, fm, legs, h4f)
    m2, h1e, h4e, d1e, fe = pd.read_pickle(gc.er.ETH_PKL)
    del m2
    h1e, h4e = cw.features(h1e, h4e, 1), cw.features(h4e, h1e, 4)
    e, _ = gc.er.prep(h1e, h4e, d1e, fe)
    wd.add_runs(e)
    bs, fbs = gc.load_bitstamp()
    wd.add_runs(bs)
    xr, fx = gc.load_xrp()
    wd.add_runs(xr)
    equity([("BTC 2018–2026", a, fm, legs), ("ETH 2018–2026", e, lg.funding_marks(e, fe), wd.run(e)), ("BTC Bitstamp 2014–2017, новые годы", bs, lg.funding_marks(bs, fbs), wd.run(bs)), ("XRP 2020–2026, новая монета", xr, lg.funding_marks(xr, fx), wd.run(xr))])


if __name__ == "__main__":
    main()
