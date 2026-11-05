"""Картинка участка 2: те же панели, ноги — правила участка 1 без изменений."""
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
import segment1_chart as sc  # noqa: E402

OUT = cw.HERE / "out"
POINTS = [(1, "2025-03-06 06:00", "о", 1), (2, "2025-03-11 20:00", "о", 1), (3, "2025-03-14 04:00", "м", -1), (4, "2025-03-20 01:00", "о", 1),
          (5, "2025-03-22 12:00", "о", -1), (6, "2025-03-26 08:00", "м", 1), (7, "2025-03-28 08:00", "о", -1), (8, "2025-04-01 16:00", "о", 1),
          (9, "2025-04-03 00:00", "м", -1), (10, "2025-04-05 16:00", "о", 1), (11, "2025-04-09 20:00", "о", 1), (12, "2025-04-12 16:00", "о", 1),
          (13, "2025-04-19 12:00", "м", -1), (14, "2025-04-26 20:00", "м", -1)]


def main():
    m, h1, h4, d1, fund = cw.load()
    for b in (h1, h4):
        lines = b[["G", "Y", "R"]]
        b["width3"] = (lines.max(axis=1) - lines.min(axis=1)) / b["close"] * 100
    A, Z = cw.T("2025-03-05"), cw.T("2025-05-05")
    s4, s1 = h4[(h4.index >= A) & (h4.index < Z)], h1[(h1.index >= A) & (h1.index < Z)]
    legs = pd.read_csv(OUT / "segment2_legs_v1.csv")
    legs = legs[legs["t1"] > A].copy()
    legs["t0"] = legs["t0"].clip(lower=A)
    sc.POINTS[:] = POINTS

    fig, axes = plt.subplots(5, 1, figsize=(17, 15), dpi=112, sharex=True, gridspec_kw={"height_ratios": [3.5, 2.8, 1.25, 1.05, 1.05], "hspace": 0.07})
    fig.patch.set_facecolor(sc.SURFACE)
    ax4, ax1, axd, axw, axv = axes
    for ax in axes:
        sc.style(ax)

    sc.candles(ax4, s4, 14400)
    x4 = sc.num(s4.index.to_numpy() + 7200)
    ax4.plot(x4, s4["G"], color=sc.C_G, lw=1.5, label="зелёная TEMA50")
    ax4.plot(x4, s4["Y"], color=sc.C_Y, lw=1.5, label="жёлтая TEMA100")
    ax4.plot(x4, s4["R"], color=sc.C_R, lw=1.5, label="красная TEMA200")
    ax4.plot(x4, s4["B"], color=sc.C_B4, lw=2.2, label="голубая 4ч EMA200")
    ax4.plot(x4, s4["B1"], color=sc.C_B1, lw=1.2, ls=(0, (4, 2)), label="голубая 1ч EMA200")
    ax4.set_ylim(71500, 101500)
    sc.shade_legs(ax4, legs, ytext=101000)
    sc.marks(ax4, s4, 14400, 1300)
    ax4.legend(loc="lower right", ncol=5, frameon=False, labelcolor=sc.INK, fontsize=9.5, handlelength=2.2)
    ax4.text(0.003, 0.93, "4ч", transform=ax4.transAxes, color=sc.INK, fontsize=12, fontweight="bold", va="top")

    sc.candles(ax1, s1, 3600)
    x1 = sc.num(s1.index.to_numpy() + 1800)
    ax1.plot(x1, s1["G"], color=sc.C_G, lw=1.0)
    ax1.plot(x1, s1["Y"], color=sc.C_Y, lw=1.0)
    ax1.plot(x1, s1["R"], color=sc.C_R, lw=1.0)
    ax1.plot(x1, s1["B4"], color=sc.C_B4, lw=2.0)
    ax1.plot(x1, s1["B"], color=sc.C_B1, lw=1.2, ls=(0, (4, 2)))
    ax1.set_ylim(72000, 103000)
    sc.shade_legs(ax1, legs)
    sc.marks(ax1, s1, 3600, 1150)
    ax1.text(0.003, 0.97, "1ч (те же цвета, линии своего таймфрейма; голубая 4ч — по закрытой 4ч)", transform=ax1.transAxes, color=sc.INK, fontsize=11, fontweight="bold", va="top")

    for col, c, name in (("d_G", sc.C_G, "до зелёной"), ("d_R", sc.C_R, "до красной"), ("d_B", sc.C_B4, "до голубой 4ч")):
        axd.plot(x4, s4[col], color=c, lw=1.3, label=name)
    axd.axhline(0, color=sc.MUTED, lw=0.6)
    axd.axhline(-5, color=sc.MUTED, lw=0.8, ls=(0, (2, 3)))
    axd.set_ylim(-16, 18)
    axd.set_yticks([-10, -5, 0, 10])
    axd.legend(loc="upper right", ncol=3, frameon=False, labelcolor=sc.INK, fontsize=9.5)
    axd.text(0.003, 0.96, "Расстояние цены 4ч до линий, %   (пунктир −5%)", transform=axd.transAxes, color=sc.INK, fontsize=10.5, fontweight="bold", va="top")

    axw.plot(x4, s4["width"], color=sc.INK, lw=1.4, label="все 4 линии")
    axw.plot(x4, s4["width3"], color=sc.MUTED, lw=1.2, ls=(0, (4, 2)), label="только 3 TEMA")
    narrow = (s4["width_rank"] <= 0.30).to_numpy()
    axw.fill_between(x4, 0, 19, where=narrow, color="#60a5fa", alpha=0.22, lw=0, step="mid")
    axw.set_ylim(0, 19)
    axw.set_yticks([0, 5, 10])
    axw.legend(loc="upper right", ncol=2, frameon=False, labelcolor=sc.INK, fontsize=9.5)
    axw.text(0.003, 0.95, "Ширина пучка 4ч, %   (заливка — самые узкие 30% за 180 дней)", transform=axw.transAxes, color=sc.INK, fontsize=10.5, fontweight="bold", va="top")

    up = (s4["close"] >= s4["open"]).to_numpy()
    axv.bar(x4, s4["vol_vs30"], 0.117, color=np.where(up, sc.UP, sc.DOWN), lw=0)
    axv.axhline(1, color=sc.MUTED, lw=0.8, ls=(0, (2, 3)))
    axv.set_ylim(0, 7.5)
    axv.set_yticks([0, 1, 2, 4])
    axv.text(0.003, 0.95, "Объём за сутки к медиане 30 дней, раз", transform=axv.transAxes, color=sc.INK, fontsize=10.5, fontweight="bold", va="top")
    axv.xaxis.set_major_locator(mdates.DayLocator(interval=4))
    axv.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    axv.set_xlim(sc.num(A), sc.num(Z) + 0.1)

    fig.suptitle("BTC 05.03–05.05.2025: правила первого участка без изменений на новых данных — сетка +\\$52 при просадке −\\$30; лонг всё время +\\$223 при −\\$211",
                 color=sc.INK, fontsize=13.5, fontweight="bold", x=0.012, ha="left", y=0.985)
    fig.text(0.012, 0.948, "Итог считан с 15.03; точки 1–2 лежат раньше. Binance spot, сетка 0.6/1.4, ордер \\$100. Красная полоса — шорт-нога, зелёная — лонг-нога, сверху её итог, если он больше \\$5.\n"
             "Кружок с белой заливкой — точка из записки, контурный — моя добавка. Два участка отобраны глазами: это ещё не проверка на истории.",
             color=sc.MUTED, fontsize=10.5)
    fig.subplots_adjust(left=0.012, right=0.958, top=0.94, bottom=0.03)
    fig.savefig(OUT / "segment2.png", facecolor=sc.SURFACE)
    print(OUT / "segment2.png")


if __name__ == "__main__":
    main()
