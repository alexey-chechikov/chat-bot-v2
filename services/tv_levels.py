"""Уровни для TradingView одной строкой (оператор 21.10: «хочу, чтобы всё вставлялось автоматически … в идеале работать
с TradingView напрямую»).

Напрямую нельзя: у TradingView нет API для записи на чужой график, Pine не ходит в сеть, новые репозитории Pine Seeds
закрыты. Поэтому бот собирает строку, которую индикатор docs/tv_pine_scripts/bot7_regime_grids.pine разбирает сам:
одно копирование из Telegram (/tv или сообщение после утренней карточки) → поле «Строка из бота» на графиках.

Формат (индикатор берёт часть своей монеты, остальное игнорирует):
  BTC u1792578000 k80683.9-84665.5 z83442.7:38,81194.4:20 e83127.2,83316.3 t83648.1,84799.9 a83343.1 n13 s74738.8 | ETH …
  u — время сборки, unix с;  k — коридор дня dr-3 (низ-верх);  z — зоны с шансом касания, %;  e — стоящие входы сеток;
  t — ближайший тейк каждой сетки;  a — средняя лонгов бота;  n — лотов;  s — порог дневного закрытия у бота (сверка с Pine).
Только чтение учёта сеток и журнала прогноза; на биржу не ходит. Порог s — дневки Binance (regime_watch._sma_exit).
Только сторона LONG: сетки ведут лонги, шорт BTC передан оператору (release_sides) — его позиции бота нет.
"""
from __future__ import annotations

import html
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SYMS = ("BTCUSDT", "ETHUSDT")


def _n(x: float) -> str:
    """Цена без разделителей тысяч (их Pine не разберёт): BTC — 0.1, остальное — 0.01, без хвостовых нулей."""
    s = f"{x:.1f}" if x >= 10000 else f"{x:.2f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _h(x: float) -> str:
    """Цена для чтения: с разделителями тысяч."""
    return f"{x:,.0f}" if x >= 10000 else f"{x:,.2f}"


def grid_levels(names=None, peek=None, state_path=None) -> dict[str, dict]:
    """По каждому символу — живые сетки (enabled и не dry_run): стоящие входы, ближайший тейк каждой сетки, средняя и объём
    лонгов. Сетка с нечитаемым учётом пропускается и попадает в `skipped` символа."""
    from services.weex_grid import engine as eg
    from services.weex_grid.loop import run_files
    names = eg.GRIDS if names is None else names
    peek = peek or eg.peek_config
    state_path = state_path or (lambda name: run_files(name, False)[0])
    out: dict[str, dict] = {}
    for name in names:
        cfg = peek(name)
        if not cfg or not cfg.get("enabled") or cfg.get("dry_run"):
            continue
        d = out.setdefault(cfg["symbol"], {"entries": [], "tps": [], "qty": 0.0, "cost": 0.0, "lots": 0,
                                           "grids": [], "skipped": []})
        try:
            st = json.loads(state_path(name).read_text(encoding="utf-8"))
            side = st.get("LONG") or {}
            lots = side.get("lots") or []
            entry = side.get("entry") or {}
        except (OSError, ValueError, AttributeError):
            logger.exception("tv_levels.state_unreadable %s", name)
            d["skipped"].append(name)
            continue
        d["grids"].append(name)
        if entry.get("price"):
            d["entries"].append(float(entry["price"]))
        tps = [float(x["tp"]) for x in lots if x.get("tp")]
        if tps:
            d["tps"].append(min(tps))
        for x in lots:
            q = float(x["qty"])
            d["qty"] += q
            d["cost"] += q * float(x["entry"])
            d["lots"] += 1
    for d in out.values():
        d["avg"] = d["cost"] / d["qty"] if d["qty"] > 0 else None
        d["entries"].sort()
        d["tps"].sort()
    return out


def day_corridor(now: datetime, forecasts=None) -> dict[str, dict]:
    """Действующий прогноз размаха dr-3 по символу (окно ещё не закончилось): коридор и зоны с шансом."""
    if forecasts is None:
        from services.coinglass_web import day_range
        forecasts = day_range._mine("forecast")
    now_ms = now.timestamp() * 1000
    out: dict[str, dict] = {}
    for f in forecasts:
        if f.get("end_ms", 0) <= now_ms or f.get("A_ms", now_ms + 1) > now_ms:
            continue
        cur = out.get(f["sym"])
        if cur is None or f.get("issued_utc", "") > cur["issued_utc"]:
            lo, hi = f["corridor"]
            out[f["sym"]] = {"issued_utc": f.get("issued_utc", ""), "lo": float(lo), "hi": float(hi),
                             "zones": [(float(x["price"]), float(x["chance"]), x.get("side", ""))
                                       for x in f.get("levels") or []]}
    return out


def thresholds(syms=SYMS) -> dict[str, float]:
    """Порог сегодняшнего дневного закрытия (как в карточке): ниже — лонги закроются по рынку на следующий день."""
    from services.regime_watch import _sma_exit
    out = {}
    for sym in syms:
        try:
            got = _sma_exit(sym)
        except Exception:                                       # noqa: BLE001
            logger.exception("tv_levels.sma_failed %s", sym)
            got = None
        if got:
            out[sym] = got[1]
    return out


def collect(now: datetime | None = None, *, grids=None, corridor=None, thr=None) -> dict:
    now = now or datetime.now(timezone.utc)
    grids = grid_levels() if grids is None else grids
    corridor = day_corridor(now) if corridor is None else corridor
    thr = thresholds() if thr is None else thr
    return {"now": now, "syms": {s: {"grid": grids.get(s), "day": corridor.get(s), "thr": thr.get(s)} for s in SYMS}}


def tv_line(data: dict) -> str:
    u = int(data["now"].timestamp())
    parts = []
    for sym, d in data["syms"].items():
        toks = [sym.replace("USDT", ""), f"u{u}"]
        day, g = d["day"], d["grid"]
        if day:
            toks.append(f"k{_n(day['lo'])}-{_n(day['hi'])}")
            if day["zones"]:
                toks.append("z" + ",".join(f"{_n(p)}:{c * 100:.0f}" for p, c, _ in day["zones"]))
        if g:
            if g["entries"]:
                toks.append("e" + ",".join(_n(x) for x in g["entries"]))
            if g["tps"]:
                toks.append("t" + ",".join(_n(x) for x in g["tps"]))
            if g["avg"]:
                toks.append(f"a{_n(g['avg'])}")
            toks.append(f"n{g['lots']}")
        if d["thr"]:
            toks.append(f"s{_n(d['thr'])}")
        parts.append(" ".join(toks))
    return " | ".join(parts)


def _span(xs: list[float]) -> str:
    return _h(xs[0]) if len(xs) == 1 else f"{_h(xs[0])}–{_h(xs[-1])}"


def card_lines(data: dict) -> list[str]:
    """Строки для утренней карточки: то, чего в ней ещё нет (коридор и зоны уже в блоке прогноза)."""
    out = []
    for sym, d in data["syms"].items():
        g = d["grid"]
        if not g or not g["grids"]:
            continue
        bits = [f"средняя {_h(g['avg'])} ({g['lots']} лот.)" if g["avg"] else "лотов нет"]
        if g["entries"]:
            bits.append(f"входы {_span(g['entries'])}" + (f" ({len(g['entries'])})" if len(g["entries"]) > 1 else ""))
        if g["tps"]:
            bits.append(f"ближайшие тейки {_span(g['tps'])}")
        if g["skipped"]:
            bits.append("учёт не прочитан: " + ", ".join(g["skipped"]))
        out.append(f"📍 {sym[:3]}: " + " · ".join(bits))
    return out


def tv_message(data: dict) -> str:
    """Ответ /tv (HTML): уровни словами и строка для индикатора в <code> — в Telegram копируется одним нажатием."""
    now_loc = data["now"].astimezone()
    lines = [f"📍 <b>Уровни для TradingView</b> · {now_loc:%d.%m %H:%M}"]
    for sym, d in data["syms"].items():
        day = d["day"]
        if day:
            z = " ".join(f"{'↑' if side == 'up' else '↓'}{_h(p)} ({c * 100:.0f}%)" for p, c, side in day["zones"])
            lines.append(f"{sym[:3]} коридор дня {_h(day['lo'])}–{_h(day['hi'])}" + (f" · зоны {z}" if z else ""))
        else:
            lines.append(f"{sym[:3]} коридор дня: прогноза нет")
        if d["thr"]:
            lines.append(f"   лонги закроются, если день UTC закроется ниже {_h(d['thr'])}")
    lines += [html.escape(x) for x in card_lines(data)]
    lines += ["", "Скопируй строку в поле «Строка из бота» индикатора «bot7 · режим сеток» (на всех графиках одна и та же):",
              f"<code>{html.escape(tv_line(data))}</code>"]
    return "\n".join(lines)
