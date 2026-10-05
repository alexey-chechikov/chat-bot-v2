"""Наглядная карточка шансов: картинка + короткий текст словами.

Оператор 01.10.2026: «прогнозы чтобы выглядели понятно и наглядно, а не
цифры столбами». Числа те же, что в odds_intraday / bot_money, меняется
только подача:
- картинка: цена за 3 суток, коридор 80% на сутки вперёд, уровни ботов
  с шансом дойти за сутки;
- текст: где будет цена (коридор), дойдёт ли до ±1/3% (полоски), что
  будет с каждым ботом на его уровнях — одной строкой словами.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
CHART_DIR = ROOT / "state" / "charts"


def bar(p: float, cells: int = 5) -> str:
    n = int(round(max(0.0, min(1.0, p)) * cells))
    return "▰" * n + "▱" * (cells - n)


def pct_txt(p: float) -> str:
    return "<1%" if p < 0.01 else ">99%" if p > 0.99 else f"{p:.0%}"


def _mood(rank: float) -> str:
    if rank < 33:
        return f"рынок тихий — размах ниже, чем {100 - rank:.0f}% времени за 9 лет"
    if rank < 67:
        return "рынок обычный"
    return f"рынок бурный — размах выше, чем {rank:.0f}% времени за 9 лет"


BOT_LABELS = {"первый тейк", "все тейки", "выход шортов по средней",
              "выход лонгов по средней", "граница"}


def _bot_rows(book, px: float, touch) -> list[tuple[str, float]]:
    """Уровни бота, которые стоит показать: выходы/тейки, граница, ±1% и хвост."""
    from services.grid_model import bot_money as bm

    lv = bm.key_levels(book, px)
    has_border = any(name == "граница" for name, _ in lv)
    keep = []
    for name, price in lv:
        if name in BOT_LABELS:
            keep.append((name, price))
        elif name in ("+1%", "-1%", "+10%", "-10%"):
            keep.append((name, price))
        elif name in ("+5%", "-5%") and not has_border:
            keep.append((name, price))
    return keep


def chance_word(p: float) -> str:
    """Шанс словами — оператору 02.10 проценты столбиком были неочевидны."""
    if p < 0.15:
        return "вряд ли"
    if p < 0.40:
        return "возможно"
    if p < 0.60:
        return "50 на 50"
    if p < 0.85:
        return "скорее да"
    return "почти наверняка"


def headline(books: list, px: float, touch) -> list[str]:
    """«Главное на сутки»: по каждому боту ближайший плюс и главный риск словами."""
    from services.grid_model import bot_money as bm

    out = []
    for book in books:
        short_name = (" ".join(book.name.split()[:2]) if book.inverse
                      else book.name.split()[0])
        kind = "Auto" if book.grid_side == 3 else ("шорт" if book.net_qty() < 0 else "лонг")
        rows = _bot_rows(book, px, touch)
        good, risk = None, None
        for name, lvl in rows:
            o = bm.simulate(book, px, lvl)
            pct = lvl / px - 1
            if name in ("первый тейк", "выход шортов по средней", "выход лонгов по средней") \
                    and o.realized > 0:
                if good is None or abs(pct) < abs(good[1] / px - 1):
                    good = (name, lvl, o)
            if name == "граница" or (risk is None and name in ("+5%", "-5%")):
                risk = (name, lvl, o)
        parts = []
        if good:
            name, lvl, o = good
            p = touch(lvl / px - 1, "сутки")
            what = "первый тейк" if name == "первый тейк" else name.replace("выход ", "выход ")
            parts.append(f"✅ {what} {lvl:,.0f} — {chance_word(p)} ({p:.0%}), "
                         f"забирает {o.realized:+,.0f}$")
        if risk:
            name, lvl, o = risk
            p1, p7 = touch(lvl / px - 1, "сутки"), touch(lvl / px - 1, "7д")
            what = "граница" if name == "граница" else f"ход {name}"
            parts.append(f"⚠️ {what} {lvl:,.0f} — сегодня {chance_word(p1)} ({p1:.0%}), "
                         f"за неделю {p7:.0%}; там итог {o.total:+,.0f}$")
        if parts:
            out.append(f"{short_name} {kind}:")
            out.extend(f"  {x}" for x in parts)
    return out


def bot_block(book, px: float, touch) -> str:
    """Бот одной строкой на уровень: что случится, сколько денег, какой шанс."""
    from services.grid_model import bot_money as bm

    net = book.net_qty()
    unit = "$" if book.inverse else f" {book.coin}"
    parts = []
    for side, nm in ((bm.SHORT, "шорты"), (bm.LONG, "лонги")):
        a = book.side_avg(side)
        if a:
            q = sum(o.qty for o in book.orders if o.side == side)
            parts.append(f"{nm} {q:g}{unit} по {a:,.0f}")
    bag = book.bag_usd
    if bag is None:
        bag = sum(bm.pnl_usd(o, px, book.inverse) for o in book.orders)
    short_name = " ".join(book.name.split()[:2]) if book.inverse else book.name.split()[0]
    kind = "Auto" if book.grid_side == 3 else ("шорт" if net < 0 else "лонг")
    out = [f"💰 {short_name} {kind} · {'; '.join(parts) or 'без позиции'} · сейчас {bag:+,.0f}$"]
    for name, lvl in _bot_rows(book, px, touch):
        pct = lvl / px - 1
        o = bm.simulate(book, px, lvl)
        p1, p7 = touch(pct, "сутки"), touch(pct, "7д")
        what = {"первый тейк": "первый тейк", "все тейки": "закроются все",
                "выход шортов по средней": "шорты выходят по средней",
                "выход лонгов по средней": "лонги выходят по средней",
                "граница": "граница, набор стоп"}.get(name, "")
        money = f"итог {o.total:+,.0f}$"
        if o.realized and what and name != "граница":
            money = f"забирает {o.realized:+,.0f}$, итог {o.total:+,.0f}$"
        chance = f"сутки {pct_txt(p1)}"
        if p1 < 0.3:
            chance += f", неделя {pct_txt(p7)}"
        if o.total >= 0:
            icon = "✅"
        elif o.realized > 0 and what and name != "граница":
            icon = "↘️"                    # что-то забрал, но в целом ещё в минусе
        elif abs(pct) >= 0.09 or o.total < -250:
            icon = "🔴"
        else:
            icon = "⚠️"
        label = f"{lvl:,.0f} ({pct:+.1%})" + (f" {what}" if what else "")
        out.append(f"  {icon} {label}: {money} · {chance}")
    return "\n".join(out)


# Доход сетки растёт как степень размаха (05.10.2026, 12 месяцев бэктестов
# GinArea, факт размаха месяца): BTC-шорт 0.6/1.39 — σ^2.0 (R² 0.82), ETH Auto
# 0.1/2.0 — σ^2.7 (R² 0.77). Заранее размах месяца не угадывается (R² 0–0.2),
# поэтому это не прогноз, а «сколько при нынешнем рынке и сколько при обычном».
INCOME_POWER = {"BTC": 2.0, "ETH": 2.7}
SNAPSHOTS = ROOT / "ginarea_live" / "snapshots.csv"


def live_income(bot_ids: list[str], days: int = 14, tail_mb: int = 80) -> dict:
    """Реализованная прибыль за последние `days` суток АКТИВНОЙ работы (статус 2).

    Читаем хвост snapshots.csv трекера: за 14 дней это ~50 МБ. Дни, когда бот
    не был запущен, не считаются — на этом я дважды ошибался в сравнении
    «живое против бэктеста».
    """
    import io

    out = {}
    if not SNAPSHOTS.exists():
        return out
    size = SNAPSHOTS.stat().st_size
    with SNAPSHOTS.open("rb") as f:
        header = f.readline().decode("utf-8", "ignore")
        f.seek(max(0, size - tail_mb * 1024 * 1024))
        f.readline()
        body = f.read().decode("utf-8", "ignore")
    t = pd.read_csv(io.StringIO(header + body), on_bad_lines="skip", low_memory=False,
                    usecols=["ts_utc", "bot_id", "status", "profit"])
    t["bot"] = t["bot_id"].astype(str).str[:10]
    t = t[t["bot"].isin(bot_ids)]
    t["ts"] = pd.to_datetime(t["ts_utc"], utc=True, errors="coerce")
    for bot, g in t.dropna(subset=["ts"]).sort_values("ts").groupby("bot"):
        g = g.set_index("ts")
        daily = g.resample("1D").agg({"status": "max", "profit": "last"})
        daily["gain"] = daily["profit"].diff()
        active = daily[daily["status"] == 2].tail(days)
        if len(active) >= 3:
            out[bot] = {"per_day": float(active["gain"].sum() / len(active)),
                        "days": int(len(active))}
    return out


def income_block(books: list, coin: str, sigma_now: float, sigma_year_med: float,
                 income: dict, px: float) -> list[str]:
    power = INCOME_POWER.get(coin, 2.0)
    ratio = (sigma_year_med / sigma_now) ** power if sigma_now > 0 else 1.0
    lines = []
    for b in books:
        bid = getattr(b, "bot_id", None)
        inc = income.get(str(bid)) if bid else None
        if not inc:
            continue
        per_day = inc["per_day"] * (px if b.inverse else 1.0)
        short_name = " ".join(b.name.split()[:2]) if b.inverse else b.name.split()[0]
        kind = "Auto" if b.grid_side == 3 else ("шорт" if b.net_qty() < 0 else "лонг")
        lines.append(f"  {short_name} {kind}: сейчас ≈ ${per_day:,.1f}/день (${per_day * 30:,.0f}/мес, "
                     f"за {inc['days']} акт. дн); при обычном для года размахе ≈ "
                     f"${per_day * ratio:,.1f}/день (×{ratio:.1f})")
    if lines:
        lines.insert(0, f"💵 ЗАРАБОТОК (доход сетки ∝ размах^{power:g}; "
                        f"размах сейчас {sigma_now * 100:.2f}%/день, обычный {sigma_year_med * 100:.2f}%):")
    return lines


def coin_text(sym: str, px: float, books: list, opt: dict) -> str:
    from services.grid_model import odds_intraday as oi
    from services.grid_model import odds_z as oz

    m, d = oi.get_model(sym)
    now = oi.now_state(m, d)
    md, dd = oz.get_model(sym)
    sd = float(dd["sigma"].iloc[-1])
    coin = sym.replace("USDT", "")

    def touch(pct: float, h: str) -> float:
        if h == "4ч":
            return m.touch(pct, 4, now.paths[4])
        if h == "сутки":
            return m.touch(pct, 24, now.paths[24])
        return md.touch(pct, 7, sd)

    out = [f"🎲 {coin} {px:,.0f} · {_mood(now.pct_rank)}"]
    if now.ahead4 > 1.05:
        out[0] += "; впереди активные часы"
    head = headline(books, px, touch)
    x4 = m.corridor(4, now.paths[4], 0.8)
    out.append("")
    out.append("📌 ГЛАВНОЕ НА СУТКИ")
    nxt = oi.next_event(d.index[-1] + pd.Timedelta(hours=1))
    if nxt is not None:
        ev, label, factor = nxt
        msk = ev + pd.Timedelta(hours=3)
        span = "2 часа" if "ФРС" in label else "час"
        out.append(f"⚡ {label} {ev:%d.%m} в {ev:%H:%M} UTC ({msk:%H:%M} МСК): "
                   f"{span} после выхода размах обычно в {factor:g} раза больше. "
                   f"Шансы ниже это уже учитывают.")
    out.append(f"Обычный ход за 4 часа: {px * (1 - x4):,.0f} … {px * (1 + x4):,.0f}. "
               f"Выйти за эти рамки — событие (1 раз из 5).")
    out.extend(head)
    out.append("")
    out.append("📍 ГДЕ БУДЕТ ЦЕНА (8 раз из 10 — внутри):")
    for h, nm in ((1, "через 1 час "), (4, "через 4 часа"), (24, "через сутки")):
        x = m.corridor(h, now.paths[h], 0.8)
        out.append(f"  {nm}  {px * (1 - x):,.0f} … {px * (1 + x):,.0f}  (±{x:.1%})")
    try:
        from services.grid_model import odds_scenarios
        out.append("")
        out.extend(odds_scenarios.text(odds_scenarios.get(sym), now.paths[24]))
    except Exception:                                       # noqa: BLE001
        logger.exception("odds_view.scenarios_failed")
    out.append("")
    out.append("🎯 ДОЙДЁТ ЛИ ЦЕНА (за 4 часа | за сутки):")
    for pct in (0.03, 0.01, -0.01, -0.03):
        p4, p24 = touch(pct, "4ч"), touch(pct, "сутки")
        arrow = "▲" if pct > 0 else "▼"
        out.append(f"  {arrow} {px * (1 + pct):,.0f} ({pct:+.0%})  "
                   f"{bar(p4)} {pct_txt(p4):>4} | {bar(p24)} {pct_txt(p24):>4}")
    for b in books:
        out.append("")
        out.append(bot_block(b, px, touch))
    try:
        inc = live_income([b.bot_id for b in books if b.bot_id])
        med = float(dd["sigma"].iloc[-365:].median())
        block = income_block(books, coin, float(dd["sigma"].iloc[-1]), med, inc, px)
        if block:
            out.append("")
            out.extend(block)
    except Exception:                                       # noqa: BLE001
        logger.exception("odds_view.income_failed")
    out.append("")
    walls =[f"{opt[k]:,.0f}" for k in ("call_wall", "put_wall") if opt.get(k)]
    month = (f"🧭 Месяц: ±10% — вверх {pct_txt(md.touch(0.10, 30, sd))}, "
             f"вниз {pct_txt(md.touch(-0.10, 30, sd))}")
    if walls:
        month += f". Стены опционов: {' / '.join(walls)}"
    out.append(month)
    out.append("ℹ️ Модель знает размах, а не сторону. Сверка с рынком: /odds сверка")
    return "\n".join(out)


def coin_chart(sym: str, px: float, books: list, path: Path | None = None) -> Path | None:
    """Цена за 3 суток + коридор 80% на сутки вперёд + уровни ботов."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:                                       # noqa: BLE001
        logger.exception("odds_view.matplotlib_missing")
        return None
    from services.grid_model import bot_money as bm
    from services.grid_model import odds_intraday as oi

    m, d = oi.get_model(sym)
    now = oi.now_state(m, d)
    hist = d["close"].iloc[-72:]
    t0 = hist.index[-1]
    hs = np.array([0, 1, 4, 12, 24])
    xs = np.array([0.0] + [m.corridor(h, now.paths[h], 0.8) for h in (1, 4, 12, 24)])
    fine = np.arange(0, 25)
    band = np.interp(np.sqrt(fine), np.sqrt(hs), xs)
    fut = [t0 + np.timedelta64(int(h), "h") for h in fine]

    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=110)
    ax.plot(hist.index, hist.values, color="#2563eb", lw=1.6, label="цена (час)")
    ax.fill_between(fut, px * (1 - band), px * (1 + band), color="#93c5fd", alpha=0.35,
                    label="коридор 80% (сутки вперёд)")
    ax.plot(fut, px * (1 + band), color="#60a5fa", lw=0.8)
    ax.plot(fut, px * (1 - band), color="#60a5fa", lw=0.8)
    lo = min(hist.min(), px * (1 - band[-1])) * 0.995
    hi = max(hist.max(), px * (1 + band[-1])) * 1.005
    # три типичных сценария суток — формы по 9 годам, масштаб сегодняшнего σ
    try:
        from services.grid_model import odds_scenarios
        colors = {"вниз": "#dc2626", "боковик": "#6b7280", "вверх": "#16a34a"}
        for sc in odds_scenarios.get(sym):
            spath = px * (1 + np.r_[0.0, np.asarray(sc.path)] * now.paths[24])
            ax.plot(fut, spath, color=colors[sc.name], lw=1.4, ls="--", alpha=0.9)
            ax.text(fut[-1], spath[-1], f" {sc.name} ≈{sc.share:.0%}",
                    color=colors[sc.name], fontsize=8, va="center", ha="left")
            lo, hi = min(lo, spath.min() * 0.998), max(hi, spath.max() * 1.002)
    except Exception:                                       # noqa: BLE001
        logger.exception("odds_view.scenario_paths_failed")
    marks = []
    for b in books:
        nm = " ".join(b.name.split()[:2]) if b.inverse else b.name.split()[0]
        for label, lvl in bm.key_levels(b, px):
            if label not in BOT_LABELS:
                continue
            marks.append((lvl, f"{nm}: {label}"))
    for lvl, text in marks:
        # 02.10: дальний уровень (все тейки 79 400 при цене 84 156) сплющивал
        # график — рисуем только уровни в пределах суточного коридора + 1%
        if abs(lvl / px - 1) > band[-1] + 0.01:
            continue
        lo, hi = min(lo, lvl * 0.998), max(hi, lvl * 1.002)
        pct = lvl / px - 1
        p24 = m.touch(pct, 24, now.paths[24])
        color = "#16a34a" if ("тейк" in text or "выход" in text) else "#dc2626"
        ax.axhline(lvl, color=color, lw=1.0, ls="--", alpha=0.8)
        ax.text(0.995, lvl, f"{text} {lvl:,.0f} · дойдёт за сутки {pct_txt(p24)}",
                transform=ax.get_yaxis_transform(), color=color, fontsize=8,
                va="bottom", ha="right",
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.85, pad=1))
    ax.axvline(t0, color="#6b7280", lw=0.8, ls=":")
    ax.plot([t0], [px], "o", color="#1d4ed8", ms=5)
    ax.set_ylim(lo, hi)
    ax.set_xlim(hist.index[0], fut[-1] + np.timedelta64(14, "h"))   # место под подписи сценариев
    coin = sym.replace("USDT", "")
    ax.set_title(f"{coin} {px:,.0f} — где будет цена ближайшие сутки", fontsize=11)
    ax.grid(alpha=0.25)
    ax.legend(loc="upper left", fontsize=8)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    fig.autofmt_xdate()
    fig.tight_layout()
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    path = path or CHART_DIR / f"odds_{coin}.png"
    fig.savefig(path)
    plt.close(fig)
    return path
