"""Картинка рынка «как у CoinGlass» (27.10, оператор прислал свою панель CoinGlass: «сравнение метрик — визуально видно,
где сходятся ликвидации, лонги-шорты, ставка финансирования, а не как у тебя каждый день в пределах нормы»).

Часовые панели за 12 суток, все на одной оси времени:
- цена и объём (Binance USDT-M);
- фандинг — начисления Binance;
- ликвидации лонгов и шортов — наш сборщик Bybit/OKX/Binance;
- толпа — L/S всех аккаунтов Binance (та же линия, что «Лонг/Шорт коэффициент (Аккаунтов)» у CoinGlass);
- крупные — L/S топ-трейдеров Binance по позициям (Whale Index CoinGlass — другая метрика, её формула не опубликована;
  27.10 их изменения совпали: резкое сокращение шортов 26.10);
- OI.
Вертикали — максимум и минимум цены окна и «сейчас» с цифрами всех панелей в эти часы: что совпало.

Подпись — только факты, без прогноза. Замер 27.10 на 2.4 годах (research/market_lens/crowd_check.py, правила записаны до
прогона): толпа — зеркало цены — изменение за сутки против цены тех же суток −0.69 BTC / −0.64 ETH, против следующих
суток 0.00; 5 состояний × 2 монеты (толпа на краю, толпа против крупных, фандинг ≤0 после падения) — шум: 46–55% против
50%, обе половины не держат. Поэтому «что совпало» показывается, а «что будет» — нет.
Только чтение публичных данных Binance и нашего файла ликвидаций.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
LIQ = {"BTCUSDT": ROOT / "market_live" / "liquidations.csv",
       "ETHUSDT": ROOT / "market_live" / "liquidations_ETHUSDT.csv"}
DAYS = 12
CAPTION_LIMIT = 1024                # подпись к фото в Telegram
MIRROR = {"BTCUSDT": "−0.69", "ETHUSDT": "−0.64"}      # корр. Δтолпы за сутки с ценой тех же суток (2.4 года)
NOTE = ("Проверено на 2.4 годах: толпа — зеркало цены (с теми же сутками {m}, со следующими 0.00); толпа на краю, "
        "толпа против крупных, фандинг ≤0 после падения — шум. Показываю, что совпало; угадывать не берусь.")


def _get(url: str):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bot7"}),
                                             timeout=30).read())


def _series(path: str, sym: str, field: str):
    import pandas as pd
    rows = _get(f"https://fapi.binance.com{path}?symbol={sym}&period=1h&limit=500")
    return pd.Series({pd.Timestamp(int(r["timestamp"]), unit="ms", tz="UTC"): float(r[field]) for r in rows},
                     dtype=float)


def liq_hourly(sym: str, since) -> tuple[dict, dict]:
    """Ликвидации по часам ($): (лонги, шорты) с часа since."""
    import pandas as pd
    ll, ls = {}, {}
    p = LIQ.get(sym)
    if not p or not p.exists():
        return ll, ls
    with open(p, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                t = pd.Timestamp(datetime.fromisoformat(r["ts_utc"])).floor("h")
                usd = float(r["qty"]) * float(r["price"])
            except (KeyError, TypeError, ValueError):
                continue
            if t < since:
                continue
            d = ll if r["side"] == "long" else ls
            d[t] = d.get(t, 0.0) + usd
    return ll, ls


def collect(sym: str):
    """Часовая таблица за ~20 суток: o h l c qv, crowd, top, oi, funding, liq_long, liq_short."""
    import pandas as pd
    kl = _get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=1h&limit=480")
    df = pd.DataFrame([{"t": pd.Timestamp(int(k[0]), unit="ms", tz="UTC"), "o": float(k[1]), "h": float(k[2]),
                        "l": float(k[3]), "c": float(k[4]), "qv": float(k[7])} for k in kl]).set_index("t")
    df["crowd"] = _series("/futures/data/globalLongShortAccountRatio", sym, "longShortRatio")
    df["top"] = _series("/futures/data/topLongShortPositionRatio", sym, "longShortRatio")
    df["oi"] = _series("/futures/data/openInterestHist", sym, "sumOpenInterestValue")
    fr = _get(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={sym}&limit=100")
    fund = pd.Series({pd.Timestamp(int(r["fundingTime"]), unit="ms", tz="UTC").floor("h"): float(r["fundingRate"])
                      for r in fr}, dtype=float)
    df["funding"] = fund.reindex(df.index).ffill()
    df["fund_tick"] = fund.reindex(df.index)           # само начисление — только в его час
    ll, ls = liq_hourly(sym, df.index[0])
    df["liq_long"] = pd.Series(ll, dtype=float).reindex(df.index).fillna(0.0)
    df["liq_short"] = pd.Series(ls, dtype=float).reindex(df.index).fillna(0.0)
    df[["crowd", "top", "oi"]] = df[["crowd", "top", "oi"]].ffill()
    return df


# ---------------------------------------------------------------- факты (чистые функции, без сети)
def _money(x: float) -> str:
    return f"${x / 1e9:.2f}B" if x >= 1e9 else f"${x / 1e6:.1f}M" if x >= 1e6 else f"${x / 1e3:.0f}K"


def _px(sym: str, x: float) -> str:
    return f"{x:,.0f}" if sym.startswith("BTC") else f"{x:,.2f}"


def _n(x: float, fmt: str) -> str:
    return format(x, fmt).replace("-", "−")


def _share(ls: float) -> float:
    return ls / (1 + ls)


def _times(n: int) -> str:
    return "раза" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else "раз"


def structure(df) -> tuple[str, list[float], list[float]] | None:
    """Три последних суток скользящими окнами по 24 ч: хаи и лои выше/ниже — словами."""
    end = df.index[-1] + timedelta(hours=1)
    hs, ls = [], []
    for k in (3, 2, 1):
        w = df[(df.index >= end - timedelta(hours=24 * k)) & (df.index < end - timedelta(hours=24 * (k - 1)))]
        if w.empty:
            return None
        hs.append(float(w["h"].max()))
        ls.append(float(w["l"].min()))
    hd = "ниже" if hs[0] > hs[1] > hs[2] else "выше" if hs[0] < hs[1] < hs[2] else "вразнобой"
    ld = "ниже" if ls[0] > ls[1] > ls[2] else "выше" if ls[0] < ls[1] < ls[2] else "вразнобой"
    word = {("ниже", "ниже"): "снижение", ("выше", "выше"): "рост", ("ниже", "выше"): "сжатие",
            ("выше", "ниже"): "расширение"}.get((hd, ld), "без порядка")
    return f"3 сут: хаи {hd}, лои {ld} → {word}", hs, ls


def facts(sym: str, df, days: int = DAYS) -> list[str]:
    """Строки подписи: цена и структура, толпа, крупные, ликвидации, фандинг, OI — что совпало на вершине и дне окна
    и где каждая линия сейчас против 20 суток. Только наблюдаемое."""
    w = df[df.index >= df.index[-1] - timedelta(days=days)]
    hi_t, lo_t = w["h"].idxmax(), w["l"].idxmin()
    r = w.iloc[-1]
    c3 = sym[:3]
    out = [f"{c3} {_px(sym, r.c)}: от макс. 12 сут {_px(sym, w.h.max())} ({hi_t:%d.%m}) "
           f"{_n((r.c / w.h.max() - 1) * 100, '+.1f')}%, мин. {_px(sym, w.l.min())} ({lo_t:%d.%m})"]
    st = structure(df)
    if st is not None:
        s, hs, ls = st
        out[0] += f"\n{s} (хаи {' → '.join(_px(sym, x) for x in hs)}; лои {' → '.join(_px(sym, x) for x in ls)})"
    cr = df["crowd"].dropna()
    if len(cr):
        mx_t = cr.idxmax()
        rank = (cr < cr.iloc[-1]).mean()
        out.append(f"👥 Толпа L/S {cr.iloc[-1]:.2f} (лонгов {_share(cr.iloc[-1]) * 100:.0f}%) — выше, чем {rank * 100:.0f}% "
                   f"часов 20 сут; макс. {cr.max():.2f} {mx_t:%d.%m %H}ч · на вершине {w.loc[hi_t, 'crowd']:.2f}, "
                   f"на дне {w.loc[lo_t, 'crowd']:.2f}")
    tp = df["top"].dropna()
    if len(tp) > 72:
        sh = tp.map(_share) * 100
        d24, d72 = sh.iloc[-1] - sh.iloc[-25], sh.iloc[-1] - sh.iloc[-73]
        word = ("лонгов стало больше, шортов меньше" if d72 >= 2 else "шортов стало больше" if d72 <= -2
                else "почти без изменений")
        rank = (tp < tp.iloc[-1]).mean()
        s = (f"🐋 Крупные L/S {tp.iloc[-1]:.2f} (лонгов {sh.iloc[-1]:.0f}%, выше {rank * 100:.0f}% часов 20 сут) · "
             f"за 24 ч {_n(d24, '+.0f')} п.п., за 72 ч {_n(d72, '+.0f')} п.п. → {word}")
        jump = sh.diff(6).iloc[-72:]                        # самый резкий сдвиг за 6 ч в последние 3 сут
        if len(jump.dropna()) and abs(jump).max() >= 3:
            t = abs(jump).idxmax()
            s += (f"; резкий сдвиг {t:%d.%m %H}ч: L/S {tp.loc[t - timedelta(hours=6)]:.2f} → {tp.loc[t]:.2f} "
                  f"({_n(jump.loc[t], '+.0f')} п.п. лонгов)")
        out.append(s)
    last = w[w.index > w.index[-1] - timedelta(hours=24)]
    big_l = w["liq_long"].idxmax() if w["liq_long"].max() > 0 else None
    big_s = w["liq_short"].idxmax() if w["liq_short"].max() > 0 else None
    s = f"💥 Ликвидации 24 ч: лонги {_money(last.liq_long.sum())} / шорты {_money(last.liq_short.sum())}"
    for t, name, col in ((big_l, "лонгов", "liq_long"), (big_s, "шортов", "liq_short")):
        if t is None:
            continue
        tag = (" — у дна" if abs((t - lo_t).total_seconds()) <= 3 * 3600 else
               " — у вершины" if abs((t - hi_t).total_seconds()) <= 3 * 3600 else "")
        s += f"\n   макс. час {name}: {_money(w.loc[t, col])} {t:%d.%m %H}ч у {_px(sym, w.loc[t, 'c'])}{tag}"
    out.append(s)
    ft = w["fund_tick"].dropna()
    if len(ft):
        neg = ft[ft <= 0]
        s = f"💸 Фандинг {ft.iloc[-1] * 100:.4f}%"
        if len(neg):
            s += f" · ≤0 за 12 сут: {len(neg)} {_times(len(neg))} ({', '.join(f'{t:%d.%m}' for t in neg.index[-3:])})"
        else:
            s += " · за 12 сут ни разу ≤0"
        out.append(s)
    oi = df["oi"].dropna()
    if len(oi) > 24:
        ch24 = oi.iloc[-1] / oi.iloc[-25] - 1
        px24 = df["c"].iloc[-1] / df["c"].iloc[-25] - 1
        mech = ("позиции растут на росте" if ch24 > 0.005 and px24 > 0.002 else
                "позиции растут на падении" if ch24 > 0.005 and px24 < -0.002 else
                "позиции сокращают на росте" if ch24 < -0.005 and px24 > 0.002 else
                "позиции сокращают на падении" if ch24 < -0.005 and px24 < -0.002 else "без заметных изменений")
        out.append(f"📊 OI {_money(oi.iloc[-1])}: за 24 ч {_n(ch24 * 100, '+.1f')}% при цене {_n(px24 * 100, '+.1f')}% "
                   f"→ {mech}; от вершины {_n((oi.iloc[-1] / w.loc[hi_t, 'oi'] - 1) * 100, '+.1f')}%")
    return out


def caption(sym: str, df) -> str:
    """Подпись ≤ 1024 знаков: факты + замечание о проверке; лишние строки фактов отбрасываются с конца."""
    lines = facts(sym, df)
    note = NOTE.format(m=MIRROR.get(sym, "≈−0.65"))
    while lines:
        text = "\n".join(lines + [note])
        if len(text) <= CAPTION_LIMIT:
            return text
        lines = lines[:-1]
    return note[:CAPTION_LIMIT]


# ---------------------------------------------------------------- картинка
BG, FG, GRID = "#131722", "#d1d4dc", "#2a2e39"
UP, DN, ACC, WARN = "#26a69a", "#ef5350", "#5b9cf6", "#f5a623"


def render(sym: str, df, days: int = DAYS) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    w = df[df.index >= df.index[-1] - timedelta(days=days)]
    hi_t, lo_t = w["h"].idxmax(), w["l"].idxmin()
    with matplotlib.rc_context({"text.parse_math": False}):
        fig, ax = plt.subplots(7, 1, figsize=(14, 13), sharex=True, facecolor=BG,
                               gridspec_kw={"height_ratios": [3.2, 1, 1, 1.2, 1.2, 1.2, 1]})
        try:
            for a in ax:
                a.set_facecolor(BG)
                a.tick_params(colors=FG, labelsize=9)
                a.grid(color=GRID, lw=0.6)
                for s in a.spines.values():
                    s.set_color(GRID)
            bw = timedelta(minutes=40)
            col = [UP if c >= o else DN for o, c in zip(w["o"], w["c"])]
            a = ax[0]
            a.vlines(w.index, w["l"], w["h"], color=col, lw=0.8)
            a.bar(w.index, (w["c"] - w["o"]).abs().clip(lower=w["c"] * 2e-5), bottom=w[["o", "c"]].min(axis=1),
                  width=bw, color=col)
            a.set_title(f"{sym} · 1ч · Binance USDT-M · {w.index[0]:%d.%m}–{w.index[-1]:%d.%m %H:%M} UTC", color=FG,
                        loc="left", fontsize=12)
            a.axhline(w["c"].iloc[-1], color=ACC, lw=0.6, ls=":")
            ax[1].bar(w.index, w["qv"] / 1e9, width=bw, color=col)
            ax[1].set_ylabel("объём $B", color=FG, fontsize=9)
            f = w["funding"] * 100
            ax[2].bar(w.index, f, width=bw * 1.5, color=[UP if v >= 0 else DN for v in f.fillna(0)])
            ax[2].set_ylabel("фандинг %", color=FG, fontsize=9)
            ax[3].bar(w.index, w["liq_long"] / 1e6, width=bw, color=DN, label="ликвидации лонгов")
            ax[3].bar(w.index, -w["liq_short"] / 1e6, width=bw, color=UP, label="ликвидации шортов (вниз)")
            ax[3].set_ylabel("ликв. $M", color=FG, fontsize=9)
            ax[3].legend(loc="upper left", fontsize=8, facecolor=BG, labelcolor=FG, framealpha=0.6)
            ax[4].plot(w.index, w["crowd"], color=WARN, lw=1.4)
            ax[4].set_ylabel("толпа L/S\n(все аккаунты)", color=FG, fontsize=9)
            ax[5].plot(w.index, w["top"], color=ACC, lw=1.4)
            ax[5].set_ylabel("крупные L/S\n(топ, позиции)", color=FG, fontsize=9)
            ax[6].plot(w.index, w["oi"] / 1e9, color=FG, lw=1.2)
            ax[6].set_ylabel("OI $B", color=FG, fontsize=9)
            for t, name, c in ((hi_t, "вершина", UP), (lo_t, "дно", DN), (w.index[-1], "сейчас", ACC)):
                for a in ax:
                    a.axvline(t, color=c, lw=0.9, ls="--", alpha=0.8)
                r = w.loc[t]
                near = w[(w.index >= t - timedelta(hours=3)) & (w.index <= t + timedelta(hours=3))]
                txt = (f"{name} {t:%d.%m %H}ч · {_px(sym, r.h if name == 'вершина' else r.l if name == 'дно' else r.c)}\n"
                       f"толпа {r.crowd:.2f} · крупные {r.top:.2f}\nOI {_money(r.oi)} · фандинг {r.funding * 100:.4f}%\n"
                       f"ликв. ±3ч: Л {_money(near.liq_long.sum())} / Ш {_money(near.liq_short.sum())}")
                now = t == w.index[-1]
                ax[0].text(t, ax[0].get_ylim()[0 if now else 1], txt, color=c, fontsize=8,
                           va="bottom" if now else "top", ha="right" if now else "left",
                           bbox=dict(facecolor=BG, edgecolor=c, alpha=0.85, pad=3))
            ax[-1].xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
            ax[-1].xaxis.set_major_locator(mdates.DayLocator())
            fig.tight_layout(h_pad=0.3)
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=100, facecolor=BG)
            return buf.getvalue()
        finally:
            plt.close(fig)


def build(sym: str) -> tuple[bytes, str]:
    """(PNG, подпись) для Telegram."""
    df = collect(sym)
    return render(sym, df), caption(sym, df)
