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
        d.setdefault("detail", []).append({
            "name": name, "entry": float(entry["price"]) if entry.get("price") else None,
            "lots": [(float(x["entry"]), float(x["qty"]), float(x["tp"]) if x.get("tp") else None) for x in lots],
            "step": float(cfg.get("step_pct") or 0), "target": float(cfg.get("target_pct") or 0),
            "qty": float(cfg.get("order_qty") or 0), "cap": int(cfg.get("max_lots_per_side") or 0)})
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


def market(syms=SYMS) -> tuple[dict[str, float], dict[str, float]]:
    """(порог сегодняшнего дневного закрытия, цена сейчас) — как в карточке: ниже порога лонги закроются по рынку на
    следующий день; цена — закрытие формирующейся дневки Binance."""
    from services.regime_watch import _sma_exit
    thr, px = {}, {}
    for sym in syms:
        try:
            got = _sma_exit(sym)
        except Exception:                                       # noqa: BLE001
            logger.exception("tv_levels.sma_failed %s", sym)
            got = None
        if got:
            px[sym], thr[sym] = got
    return thr, px


def thresholds(syms=SYMS) -> dict[str, float]:
    return market(syms)[0]


def collect(now: datetime | None = None, *, grids=None, corridor=None, thr=None, px=None) -> dict:
    now = now or datetime.now(timezone.utc)
    grids = grid_levels() if grids is None else grids
    corridor = day_corridor(now) if corridor is None else corridor
    if thr is None:
        thr, got_px = market()
        px = got_px if px is None else px
    px = px or {}
    return {"now": now, "syms": {s: {"grid": grids.get(s), "day": corridor.get(s), "thr": thr.get(s),
                                     "px": px.get(s)} for s in SYMS}}


FEE_MAKER = 0.00016          # мейкер WEEX — замер по исполнениям сеток 09–12.10 (CLAUDE.md); входы и тейки — POST_ONLY


def scenarios(data: dict) -> dict[str, dict]:
    """Что будет с живыми сетками, если цена дойдёт до края коридора дня ПО ПРЯМОЙ (21.10, оператор: сценарии в духе
    Copilot, но про наши деньги): вверх — тейки, у которых цена тейка ≤ верха, и закрыто (минус комиссия выхода); вниз —
    доборы от стоящего входа через шаг сетки до потолка ордеров, мешок всех лотов на нижнем краю (с комиссией доборов) и
    номинал позиции. Отскоки по пути дали бы тейки — по прямой это худший случай для мешка. Арифметика по учёту, не прогноз."""
    out = {}
    for sym, d in data["syms"].items():
        g, day = d["grid"], d["day"]
        if not g or not day or not g.get("detail"):
            continue
        lo, hi = day["lo"], day["hi"]
        r = {"lo": lo, "hi": hi, "takes": 0, "closed": 0.0, "adds": 0, "bag_lo": 0.0, "notional_lo": 0.0, "capped": []}
        for gd in g["detail"]:
            for e, q, tp in gd["lots"]:
                if tp and tp <= hi:
                    r["takes"] += 1
                    r["closed"] += (tp - e) * q - tp * q * FEE_MAKER
            p, n, new = gd["entry"], len(gd["lots"]), []
            while p and gd["step"] > 0 and p >= lo and n < gd["cap"]:
                new.append(p)
                n += 1
                p *= 1 - gd["step"] / 100
            if gd["cap"] and n >= gd["cap"]:
                r["capped"].append(gd["name"])
            r["adds"] += len(new)
            pos = [(e, q) for e, q, _ in gd["lots"]] + [(x, gd["qty"]) for x in new]
            r["bag_lo"] += sum((lo - e) * q for e, q in pos) - sum(x * gd["qty"] * FEE_MAKER for x in new)
            r["notional_lo"] += sum(e * q for e, q in pos)
        out[sym] = r
    return out


def _pct(p: float, px: float) -> str:
    return f"{(p / px - 1) * 100:+.1f}%"


def scenario_lines(data: dict) -> list[str]:
    sc = scenarios(data)
    if not sc:
        return []
    out = ["🎯 Сетки на сутки — если цена дойдёт до края коридора по прямой"]
    for sym, r in sc.items():
        px, c = data["syms"][sym]["px"], sym[:3]
        up_pct = f" ({_pct(r['hi'], px)})" if px else ""
        dn_pct = f" ({_pct(r['lo'], px)})" if px else ""
        out.append(f"{c} ↑ {_h(r['hi'])}{up_pct}: тейков {r['takes']} · закрыто {r['closed']:+,.2f}$")
        out.append(f"{c} ↓ {_h(r['lo'])}{dn_pct}: доборов {r['adds']}"
                   + (f" · в потолке: {', '.join(r['capped'])}" if r["capped"] else "")
                   + f" · мешок {r['bag_lo']:+,.0f}$ · в позиции {r['notional_lo']:,.0f}$")
    out.append("Коридор — квантиль 90% каждой стороны по 2 годам. Отскоки по пути дали бы тейки — по прямой это худший "
               "случай для мешка.")
    return out


def level_lines(data: dict) -> list[str]:
    """Таблица уровней по монете от цены сейчас (сверху вниз): коридор и зоны дня, безубыток лотов, входы и ближайшие
    тейки сеток, порог дневного закрытия. Процент — первым: в Telegram цифры ровнее слов."""
    out = []
    for sym, d in data["syms"].items():
        px, day, g = d["px"], d["day"], d["grid"]
        if not px:
            continue
        rows = []
        if day:
            rows += [(day["hi"], "верх коридора дня"), (day["lo"], "низ коридора дня")]
            rows += [(p, f"зона {'↑' if s == 'up' else '↓'} · шанс {c * 100:.0f}%") for p, c, s in day["zones"]]
        if g and g["grids"]:
            if g["avg"]:
                rows.append((g["avg"], f"безубыток лотов ({g['lots']})"))
            if g["entries"]:
                rows.append((g["entries"][-1], "вход сетки" if len(g["entries"]) == 1 else
                             f"входы сеток ({len(g['entries'])}): {_span(g['entries'])}"))
            if g["tps"]:
                rows.append((g["tps"][0], "ближайший тейк" if len(g["tps"]) == 1 else
                             f"ближайшие тейки ({len(g['tps'])}): {_span(g['tps'])}"))
            if g["skipped"]:
                rows.append((px, "учёт не прочитан: " + ", ".join(g["skipped"])))
        if d["thr"]:
            rows.append((d["thr"], "порог дневного закрытия (SMA100)"))
        if not rows:
            continue
        out += ([""] if out else []) + [f"📍 Уровни {sym[:3]} · цена {_h(px)}"]
        out += [f"{_pct(p, px):>7}  {_h(p)}  {label}" for p, label in sorted(rows, key=lambda r: -r[0])]
    return out


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
    body = scenario_lines(data) + level_lines(data)
    lines += [""] + [html.escape(x) for x in (body or card_lines(data))]
    lines += ["", "Скопируй строку в поле «Строка из бота» индикатора «bot7 · режим сеток» (на всех графиках одна и та же):",
              f"<code>{html.escape(tv_line(data))}</code>"]
    return "\n".join(lines)
