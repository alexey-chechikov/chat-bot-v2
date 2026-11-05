"""Картинка участка 1: свечи 4ч и 1ч с линиями оператора, ноги автомата, отмеченные точки, расстояния, ширина пучка, объём."""
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

OUT = cw.HERE / "out"
SURFACE, INK, MUTED, GRID = "#131722", "#e5e7eb", "#9ca3af", "#262b38"
C_G, C_Y, C_R, C_B4, C_B1 = "#34d399", "#facc15", "#f87171", "#38bdf8", "#a5e3fd"
UP, DOWN = "#d1d5db", "#5b6472"
TINT_S, TINT_L = "#7f1d1d", "#14532d"

# номер, время закрытия (UTC), подпись, чья точка: о — из записки оператора, м — моя добавка, куда сдвинуть (+ вверх, − вниз)
POINTS = [
    (1, "2025-02-18 04:00", "м", 1), (2, "2025-02-21 16:00", "м", 1), (3, "2025-02-23 12:00", "о", 1),
    (4, "2025-02-24 16:00", "о", -1), (5, "2025-02-25 08:00", "о", -1), (6, "2025-02-27 12:00", "о", 1),
    (7, "2025-02-28 08:00", "о", -1), (8, "2025-02-28 16:00", "о", 1), (9, "2025-03-01 20:00", "о", -1),
    (10, "2025-03-02 18:00", "о", 1), (11, "2025-03-03 04:00", "о", -1), (12, "2025-03-04 04:00", "м", -1),
    (13, "2025-03-04 21:00", "м", -1), (14, "2025-03-06 06:00", "м", 1), (15, "2025-03-08 04:00", "м", 1),
    (16, "2025-03-10 00:00", "о", -1), (17, "2025-03-13 20:00", "м", -1)]


def num(t):
    return mdates.date2num(pd.to_datetime(t, unit="s"))


def candles(ax, b, sec):
    x = num(b.index.to_numpy() + sec / 2)
    w = sec / 86400 * 0.7
    up = (b["close"] >= b["open"]).to_numpy()
    ax.vlines(x, b["low"], b["high"], color=np.where(up, UP, DOWN), lw=0.6, zorder=2)
    ax.bar(x, (b["close"] - b["open"]).abs(), w, bottom=b[["open", "close"]].min(axis=1), color=np.where(up, UP, DOWN), lw=0, zorder=2)


def style(ax):
    ax.set_facecolor(SURFACE)
    ax.grid(axis="y", color=GRID, lw=0.6)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.yaxis.tick_right()


def shade_legs(ax, legs, ytext=None):
    for _, g in legs.iterrows():
        t0, t1 = g["t0"], g["t1"]
        ax.axvspan(num(t0), num(t1), color=TINT_S if g["сторона"] == "S" else TINT_L, alpha=0.28, lw=0, zorder=0)
        if ytext is not None and abs(g["сетка_$"]) >= 5:
            v = g["сетка_$"]
            ax.text(num((t0 + t1) / 2), ytext, f"{'+' if v > 0 else '−'}\\${abs(v):.0f}", color=INK, fontsize=9, ha="center", va="top", zorder=5)


def marks(ax, b, sec, pad):
    for n, t, who, sgn in POINTS:
        tt = cw.T(t)
        i = int(np.searchsorted(b["known"].to_numpy(), tt, side="left"))
        i = min(i, len(b) - 1)
        r = b.iloc[i]
        x = num(int(b.index[i]) + sec / 2)
        y = (r["high"] + pad) if sgn > 0 else (r["low"] - pad)
        mine = who == "м"
        ax.annotate(str(n), (x, y), color=INK if mine else "#111827", fontsize=8.5, fontweight="bold", ha="center", va="center", zorder=7,
                    bbox=dict(boxstyle="circle,pad=0.25", fc=SURFACE if mine else "#f9fafb", ec="#f9fafb", lw=1.1))


def main():
    m, h1, h4, d1, fund = cw.load()
    for b in (h1, h4):
        lines = b[["G", "Y", "R"]]
        b["width3"] = (lines.max(axis=1) - lines.min(axis=1)) / b["close"] * 100
    A, Z = cw.T("2025-02-15"), cw.T("2025-03-15")
    s4, s1 = h4[(h4.index >= A) & (h4.index < Z)], h1[(h1.index >= A) & (h1.index < Z)]
    legs = pd.read_csv(OUT / "segment1_legs_далеко_закрывать.csv")
    for c, d in (("открыта", "t0"), ("закрыта", "t1")):
        legs[d] = (pd.to_datetime("2025." + legs[c], format="%Y.%d.%m %H:%M").astype("int64") // 10**9
                   if legs[c].dtype == object else None)

    fig, axes = plt.subplots(5, 1, figsize=(16, 15), dpi=115, sharex=True, gridspec_kw={"height_ratios": [3.5, 2.8, 1.25, 1.05, 1.05], "hspace": 0.07})
    fig.patch.set_facecolor(SURFACE)
    ax4, ax1, axd, axw, axv = axes
    for ax in axes:
        style(ax)

    candles(ax4, s4, 14400)
    x4 = num(s4.index.to_numpy() + 7200)
    ax4.plot(x4, s4["G"], color=C_G, lw=1.6, label="зелёная TEMA50")
    ax4.plot(x4, s4["Y"], color=C_Y, lw=1.6, label="жёлтая TEMA100")
    ax4.plot(x4, s4["R"], color=C_R, lw=1.6, label="красная TEMA200")
    ax4.plot(x4, s4["B"], color=C_B4, lw=2.2, label="голубая 4ч EMA200")
    ax4.plot(x4, s4["B1"], color=C_B1, lw=1.2, ls=(0, (4, 2)), label="голубая 1ч EMA200")
    ax4.set_ylim(74500, 102500)
    shade_legs(ax4, legs, ytext=102000)
    marks(ax4, s4, 14400, 1250)
    ax4.legend(loc="lower left", ncol=5, frameon=False, labelcolor=INK, fontsize=9.5, handlelength=2.2)
    ax4.text(0.003, 0.975, "4ч", transform=ax4.transAxes, color=INK, fontsize=12, fontweight="bold", va="top")

    candles(ax1, s1, 3600)
    x1 = num(s1.index.to_numpy() + 1800)
    ax1.plot(x1, s1["G"], color=C_G, lw=1.1)
    ax1.plot(x1, s1["Y"], color=C_Y, lw=1.1)
    ax1.plot(x1, s1["R"], color=C_R, lw=1.1)
    ax1.plot(x1, s1["B4"], color=C_B4, lw=2.0)
    ax1.plot(x1, s1["B"], color=C_B1, lw=1.2, ls=(0, (4, 2)))
    ax1.set_ylim(75000, 103500)
    shade_legs(ax1, legs)
    marks(ax1, s1, 3600, 1050)
    ax1.text(0.003, 0.97, "1ч (те же цвета, линии своего таймфрейма; голубая 4ч — по закрытой 4ч)", transform=ax1.transAxes, color=INK, fontsize=11, fontweight="bold", va="top")

    for col, c, name in (("d_G", C_G, "до зелёной"), ("d_R", C_R, "до красной"), ("d_B", C_B4, "до голубой 4ч")):
        axd.plot(x4, s4[col], color=c, lw=1.4, label=name)
    axd.axhline(0, color=MUTED, lw=0.6)
    for lv in (-5, -12):
        axd.axhline(lv, color=MUTED, lw=0.8, ls=(0, (2, 3)))
    axd.set_ylim(-19, 17)
    axd.set_yticks([-12, -5, 0, 10])
    axd.legend(loc="upper right", ncol=3, frameon=False, labelcolor=INK, fontsize=9.5)
    axd.text(0.003, 0.96, "Расстояние цены 4ч до линий, %   (пунктир −5% и −12%)", transform=axd.transAxes, color=INK, fontsize=10.5, fontweight="bold", va="top")

    axw.plot(x4, s4["width"], color=INK, lw=1.4, label="все 4 линии")
    axw.plot(x4, s4["width3"], color=MUTED, lw=1.2, ls=(0, (4, 2)), label="только 3 TEMA")
    narrow = (s4["width_rank"] <= 0.15).to_numpy()
    axw.fill_between(x4, 0, 21, where=narrow, color="#60a5fa", alpha=0.22, lw=0, step="mid")
    axw.set_ylim(0, 21)
    axw.set_yticks([0, 5, 10, 15])
    axw.legend(loc="upper right", ncol=2, frameon=False, labelcolor=INK, fontsize=9.5)
    axw.text(0.003, 0.95, "Ширина пучка 4ч, %   (заливка — самые узкие 15% за 180 дней)", transform=axw.transAxes, color=INK, fontsize=10.5, fontweight="bold", va="top")

    up = (s4["close"] >= s4["open"]).to_numpy()
    axv.bar(x4, s4["vol_vs30"], 0.117, color=np.where(up, UP, DOWN), lw=0)
    axv.axhline(1, color=MUTED, lw=0.8, ls=(0, (2, 3)))
    flag = ((s4["vol_trend"] >= 1.5) & (s4["ret24"] <= -1)).to_numpy()
    axv.scatter(x4[flag], np.full(flag.sum(), 5.3), marker="v", s=22, color="#f9fafb", zorder=4)
    axv.set_ylim(0, 7)
    axv.set_yticks([0, 1, 2, 4])
    axv.text(0.003, 0.95, "Объём за сутки к медиане 30 дней, раз   (▼ — объём ×1.5+ к прошлым суткам при падении ≥1%)", transform=axv.transAxes, color=INK, fontsize=10.5, fontweight="bold", va="top")
    axv.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    axv.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    axv.set_xlim(num(A), num(Z) + 0.1)

    fig.suptitle("BTC 15.02–15.03.2025: слова оператора на закрытиях свечей — сетка +\\$59 при просадке −\\$56; лонг всё время +\\$68 при −\\$412",
                 color=INK, fontsize=14.5, fontweight="bold", x=0.015, ha="left", y=0.985)
    fig.text(0.015, 0.948, "Binance spot, сетка 0.6/1.4, ордер \\$100. Красная полоса — шорт-нога, зелёная — лонг-нога, сверху её итог, если он больше \\$5.\n"
             "Кружок с белой заливкой — точка из записки, контурный — моя добавка. Один участок, отобран глазами: это не проверка.",
             color=MUTED, fontsize=10.5)
    fig.subplots_adjust(left=0.015, right=0.955, top=0.94, bottom=0.03)
    fig.savefig(OUT / "segment1.png", facecolor=SURFACE)
    print(OUT / "segment1.png")


if __name__ == "__main__":
    main()
