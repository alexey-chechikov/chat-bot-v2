"""Уровни для TradingView одной строкой (оператор 21.10: «хочу, чтобы всё вставлялось автоматически … в идеале работать
с TradingView напрямую»).

Напрямую нельзя: у TradingView нет API для записи на чужой график, Pine не ходит в сеть, новые репозитории Pine Seeds
закрыты. Поэтому бот собирает строку, которую индикатор docs/tv_pine_scripts/bot7_regime_grids.pine разбирает сам:
одно копирование из Telegram (/tv или сообщение после утренней карточки) → поле «Строка из бота» на графиках.

Формат (индикатор берёт часть своей монеты, остальное игнорирует):
  BTC u1792578000 g4/4 k80683.9-84665.5 w1792648800 z83442.7:38,81194.4:20 e83127.2,83316.3 t83648.1,84799.9
      a83343.1 n13 s74738.8 | ETH …
  u — время сборки, unix с;  g — прочитано/ожидалось живых сеток;  x — непрочитанные сетки (через запятую);
  k — коридор дня dr-3 (низ-верх);  w — конец окна прогноза, unix с;  z — зоны с шансом касания, %;
  e — стоящие входы сеток;  t — ближайший тейк каждой сетки;  a — средняя открытых лотов БЕЗ комиссий (не безубыток);
  n — лотов;  s — порог дневного закрытия у бота (сверка с Pine).
Только чтение учёта сеток, сверки позиции, конфигов и журнала прогноза; на биржу не ходит. Порог s — дневки Binance
(regime_watch._sma_exit). Только сторона LONG: сетки ведут лонги, шорт BTC передан оператору (release_sides).
21.10, разбор GPT 8252cc0 (F1–F4): сценарий доборов — по правилам движка (тик, слоты по parent, остаток частичного
входа, потолок позиции); сетка разбирается целиком до сложения в общий итог; полнота и срок данных — в строке.
"""
from __future__ import annotations

import html
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SYMS = ("BTCUSDT", "ETHUSDT")
AVG_LABEL = "средняя открытых лотов, без комиссий"


def _n(x: float) -> str:
    """Цена без разделителей тысяч (их Pine не разберёт): BTC — 0.1, остальное — 0.01, без хвостовых нулей."""
    s = f"{x:.1f}" if x >= 10000 else f"{x:.2f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _h(x: float) -> str:
    """Цена для чтения: с разделителями тысяч."""
    return f"{x:,.0f}" if x >= 10000 else f"{x:,.2f}"


def _audit_blocks(path=None) -> dict[str, str]:
    """{'BTCUSDT:LONG': причина} — общая сверка позиции, при блоке входы стороны стоят (loop.position_audit)."""
    if path is None:
        from services.weex_grid import loop
        path = loop.AUDIT_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: (v.get("reason") or "сверка позиции") for k, v in raw.items() if isinstance(v, dict) and v.get("blocked")}


def _parse_grid(name: str, cfg: dict, st: dict, blocks: dict) -> dict:
    """Полный разбор одной сетки ДО сложения в общий итог (разбор GPT F4): любое битое поле — исключение, сетка
    пропускается целиком, остальные видны."""
    side = st.get("LONG") or {}
    lots = []
    for i, x in enumerate(side.get("lots") or []):
        lots.append({"entry": float(x["entry"]), "qty": float(x["qty"]),
                     "tp": float(x["tp"]) if x.get("tp") not in (None, "") else None,
                     "parent": str(x.get("parent") or f"lot{i}")})
    e = side.get("entry")
    entry = None
    if e:
        entry = {"id": str(e.get("id") or "entry"), "price": float(e["price"]),
                 "qty": float(e.get("qty") or cfg["order_qty"]), "filled": float(e.get("filled") or 0)}
    return {"name": name, "lots": lots, "entry": entry,
            "step": float(cfg["step_pct"]), "target": float(cfg["target_pct"]), "qty": float(cfg["order_qty"]),
            "cap": int(cfg["max_lots_per_side"]), "max_notional": float(cfg["max_notional_usd"]),
            "tick": float(cfg["price_tick"]), "stress": float(cfg.get("stress_budget_frac") or 0),
            "halted": bool(st.get("halted")), "blocked": blocks.get(f"{cfg['symbol']}:LONG", "")}


def grid_levels(names=None, peek=None, state_path=None, blocks=None) -> dict[str, dict]:
    """По каждому символу — живые сетки (enabled и не dry_run): стоящие входы, ближайший тейк каждой сетки, средняя и объём
    лонгов, детали для сценариев. expected — сколько живых сеток должно быть; сетка с нечитаемым учётом — в skipped
    с причиной (её лоты не подменяются нулём)."""
    from services.weex_grid import engine as eg
    from services.weex_grid.loop import run_files
    names = eg.GRIDS if names is None else names
    peek = peek or eg.peek_config
    state_path = state_path or (lambda name: run_files(name, False)[0])
    blocks = _audit_blocks() if blocks is None else blocks
    out: dict[str, dict] = {}
    for name in names:
        cfg = peek(name)
        if not cfg or not cfg.get("enabled") or cfg.get("dry_run"):
            continue
        d = out.setdefault(cfg["symbol"], {"expected": 0, "grids": [], "skipped": [], "detail": [], "entries": [],
                                           "tps": [], "qty": 0.0, "cost": 0.0, "lots": 0})
        d["expected"] += 1
        try:
            gd = _parse_grid(name, cfg, json.loads(state_path(name).read_text(encoding="utf-8")), blocks)
        except Exception as exc:                                # noqa: BLE001 — любая порча = пропуск с причиной
            logger.exception("tv_levels.state_unreadable %s", name)
            d["skipped"].append((name, type(exc).__name__))
            continue
        d["grids"].append(name)
        d["detail"].append(gd)
        if gd["entry"]:
            d["entries"].append(gd["entry"]["price"])
        tps = [x["tp"] for x in gd["lots"] if x["tp"]]
        if tps:
            d["tps"].append(min(tps))
        for x in gd["lots"]:
            d["qty"] += x["qty"]
            d["cost"] += x["qty"] * x["entry"]
            d["lots"] += 1
    for d in out.values():
        d["avg"] = d["cost"] / d["qty"] if d["qty"] > 0 else None
        d["entries"].sort()
        d["tps"].sort()
    return out


def day_corridor(now: datetime, forecasts=None) -> dict[str, dict]:
    """Действующий прогноз размаха dr-3 по символу (окно ещё не закончилось): коридор, зоны с шансом, конец окна."""
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
                             "end": float(f["end_ms"]) / 1000,
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


def gross_cap() -> float | None:
    """Общий потолок всех живых сеток (state/weex_portfolio_config.json), если включён."""
    try:
        from services.weex_grid import portfolio
        cfg = json.loads(portfolio.CONFIG.read_text(encoding="utf-8"))
        return float(cfg["gross_cap_usd"]) if cfg.get("enabled") else None
    except Exception:                                           # noqa: BLE001
        logger.exception("tv_levels.portfolio_unreadable")
        return None


def collect(now: datetime | None = None, *, grids=None, corridor=None, thr=None, px=None, cap="read") -> dict:
    now = now or datetime.now(timezone.utc)
    grids = grid_levels() if grids is None else grids
    corridor = day_corridor(now) if corridor is None else corridor
    if thr is None:
        thr, got_px = market()
        px = got_px if px is None else px
    px = px or {}
    return {"now": now, "cap": gross_cap() if cap == "read" else cap,
            "syms": {s: {"grid": grids.get(s), "day": corridor.get(s), "thr": thr.get(s), "px": px.get(s)}
                     for s in SYMS}}


FEE_MAKER = 0.00016          # мейкер WEEX — замер по исполнениям сеток 09–12.10 (CLAUDE.md); входы и тейки — POST_ONLY


def _sim_down(gd: dict, lo: float, px: float | None) -> tuple[list, list, str]:
    """Непрерывное снижение цены до lo при исполнении предусмотренных лимиток — по правилам движка
    (engine.Grid.tick и may_add): стоящий вход исполняется по своей цене, частично исполненный — остатком в том же слоте;
    следующий вход — от НИЖНЕГО открытого лота на шаг ниже, округлён вниз до тика; новый слот — по уникальному parent;
    потолок позиции — max(себестоимость, стоимость по цене у входа) + новый вход ≤ max_notional_usd.
    Возвращает (доборы [(цена, объём)], все лоты [(цена, объём)], причина остановки или '')."""
    from services.weex_grid.engine import round_tick
    lots = [(x["entry"], x["qty"]) for x in gd["lots"]]
    if gd["halted"]:
        return [], lots, "сетка остановлена"
    if gd["blocked"]:
        return [], lots, "сверка позиции: входы стоят"
    slots = {x["parent"] for x in gd["lots"]}
    cost, qty = sum(p * q for p, q in lots), sum(q for _, q in lots)
    adds: list = []

    def fill(price: float, q: float, parent: str) -> str:
        nonlocal cost, qty
        if len(slots) + (0 if parent in slots else 1) > gd["cap"]:
            return "потолок ордеров"
        if max(cost, qty * price) + q * price > gd["max_notional"] + 1e-9:
            return "потолок позиции"
        cost, qty = cost + q * price, qty + q
        slots.add(parent)
        lots.append((price, q))
        adds.append((price, q))
        return ""

    e = gd["entry"]
    if e:
        if e["price"] < lo:
            return adds, lots, ""
        rem = e["qty"] - e["filled"] if e["filled"] > 0 else e["qty"]
        why = fill(e["price"], max(rem, 0.0), e["id"])
        if why:
            return adds, lots, why
    ref = min((p for p, _ in lots), default=None)
    if ref is None:
        ref = px                                                # без позиции опорная цена — текущая
    if not ref or gd["step"] <= 0:
        return adds, lots, ""
    k = 0
    while True:
        desired = round_tick(ref * (1 - gd["step"] / 100), gd["tick"], up=False)
        if desired < lo or desired <= 0:
            return adds, lots, ""
        why = fill(desired, gd["qty"], f"sim{k}")
        if why:
            return adds, lots, why
        ref, k = desired, k + 1


def scenarios(data: dict) -> dict[str, dict]:
    """Что будет с живыми сетками, если цена дойдёт до края коридора дня (21.10, оператор: сценарии в духе Copilot, но
    про наши деньги). Вверх — тейки, у которых цена тейка ≤ верха, и закрыто (минус мейкер выхода). Вниз — модель
    непрерывного снижения до нижнего края при исполнении предусмотренных лимиток (_sim_down): доборы, причина остановки,
    мешок всех лотов на нижнем краю (с комиссией доборов), номинал позиции. Не гарантированная граница потерь: путь цены,
    стресс-бюджет и общий потолок счёта моделируются лишь пометкой. Арифметика по учёту, не прогноз."""
    out = {}
    for sym, d in data["syms"].items():
        g, day = d["grid"], d["day"]
        if not g or not day or not g.get("detail"):
            continue
        lo, hi = day["lo"], day["hi"]
        r = {"lo": lo, "hi": hi, "takes": 0, "closed": 0.0, "adds": 0, "bag_lo": 0.0, "notional_lo": 0.0,
             "stops": {}, "notes": []}
        for gd in g["detail"]:
            for x in gd["lots"]:
                if x["tp"] and x["tp"] <= hi:
                    r["takes"] += 1
                    r["closed"] += (x["tp"] - x["entry"]) * x["qty"] - x["tp"] * x["qty"] * FEE_MAKER
            adds, pos, why = _sim_down(gd, lo, d.get("px"))
            if why:
                r["stops"][gd["name"]] = why
            if gd["stress"] > 0:
                r["notes"].append(f"{gd['name']}: стресс-бюджет включён — может остановить раньше (не моделируется)")
            r["adds"] += len(adds)
            r["bag_lo"] += sum((lo - p) * q for p, q in pos) - sum(p * q * FEE_MAKER for p, q in adds)
            r["notional_lo"] += sum(p * q for p, q in pos)
        out[sym] = r
    cap = data.get("cap")
    if cap and sum(r["notional_lo"] for r in out.values()) > cap + 1e-9:
        for r in out.values():
            r["notes"].append(f"общий потолок ${cap:,.0f} на все сетки может остановить доборы раньше")
    return out


def _pct(p: float, px: float) -> str:
    return f"{(p / px - 1) * 100:+.1f}%"


def scenario_lines(data: dict) -> list[str]:
    sc = scenarios(data)
    if not sc:
        return []
    out = ["🎯 Сетки на сутки — если цена дойдёт до края коридора"]
    for sym, r in sc.items():
        px, c = data["syms"][sym]["px"], sym[:3]
        up_pct = f" ({_pct(r['hi'], px)})" if px else ""
        dn_pct = f" ({_pct(r['lo'], px)})" if px else ""
        out.append(f"{c} ↑ {_h(r['hi'])}{up_pct}: тейков {r['takes']} · закрыто {r['closed']:+,.2f}$")
        stops = ", ".join(f"{n} — {w}" for n, w in r["stops"].items())
        out.append(f"{c} ↓ {_h(r['lo'])}{dn_pct}: доборов {r['adds']}" + (f" · остановит: {stops}" if stops else "")
                   + f" · мешок {r['bag_lo']:+,.0f}$ · в позиции {r['notional_lo']:,.0f}$")
        out += [f"   ⚠️ {n}" for n in dict.fromkeys(r["notes"])]
    out.append("Модель: непрерывное снижение до нижнего края при исполнении предусмотренных лимиток, правила движка (шаг от "
               "нижнего лота, тик, потолки ордеров и позиции). Не гарантированная граница потерь. Коридор — квантиль 90% "
               "каждой стороны по 2 годам.")
    return out


def _coverage(g: dict | None) -> str:
    if not g or not g["skipped"]:
        return ""
    miss = ", ".join(f"{n} ({why})" for n, why in g["skipped"])
    return f"⚠️ учёт прочитан {len(g['grids'])} из {g['expected']} сеток — не прочитаны: {miss}"


def level_lines(data: dict) -> list[str]:
    """Таблица уровней по монете от цены сейчас (сверху вниз): коридор и зоны дня, средняя открытых лотов, входы и
    ближайшие тейки сеток, порог дневного закрытия. Процент — первым: в Telegram цифры ровнее слов. Неполный учёт
    (в т.ч. ни одной прочитанной сетки) — отдельной строкой-предупреждением."""
    out = []
    for sym, d in data["syms"].items():
        px, day, g = d["px"], d["day"], d["grid"]
        rows = []
        if day:
            rows += [(day["hi"], "верх коридора дня"), (day["lo"], "низ коридора дня")]
            rows += [(p, f"зона {'↑' if s == 'up' else '↓'} · шанс {c * 100:.0f}%") for p, c, s in day["zones"]]
        if g and g["grids"]:
            if g["avg"]:
                rows.append((g["avg"], f"{AVG_LABEL} ({g['lots']})"))
            if g["entries"]:
                rows.append((g["entries"][-1], "вход сетки" if len(g["entries"]) == 1 else
                             f"входы сеток ({len(g['entries'])}): {_span(g['entries'])}"))
            if g["tps"]:
                rows.append((g["tps"][0], "ближайший тейк" if len(g["tps"]) == 1 else
                             f"ближайшие тейки ({len(g['tps'])}): {_span(g['tps'])}"))
        if d["thr"]:
            rows.append((d["thr"], "порог дневного закрытия (SMA100)"))
        cov = _coverage(g)
        if not rows and not cov:
            continue
        out += ([""] if out else []) + [f"📍 Уровни {sym[:3]}" + (f" · цена {_h(px)}" if px else "")]
        if cov:
            out.append(cov)
        if px:
            out += [f"{_pct(p, px):>7}  {_h(p)}  {label}" for p, label in sorted(rows, key=lambda r: -r[0])]
        else:
            out += [f"{_h(p)}  {label}" for p, label in sorted(rows, key=lambda r: -r[0])]
    return out


def tv_line(data: dict) -> str:
    u = int(data["now"].timestamp())
    parts = []
    for sym, d in data["syms"].items():
        toks = [sym.replace("USDT", ""), f"u{u}"]
        day, g = d["day"], d["grid"]
        if g:
            toks.append(f"g{len(g['grids'])}/{g['expected']}")
            if g["skipped"]:
                toks.append("x" + ",".join(n for n, _ in g["skipped"]))
        if day:
            toks.append(f"k{_n(day['lo'])}-{_n(day['hi'])}")
            if day.get("end"):
                toks.append(f"w{int(day['end'])}")
            if day["zones"]:
                toks.append("z" + ",".join(f"{_n(p)}:{c * 100:.0f}" for p, c, _ in day["zones"]))
        if g:
            if g["entries"]:
                toks.append("e" + ",".join(_n(x) for x in g["entries"]))
            if g["tps"]:
                toks.append("t" + ",".join(_n(x) for x in g["tps"]))
            if g["avg"]:
                toks.append(f"a{_n(g['avg'])}")
            if g["grids"]:                                      # ни одной прочитанной — не «0 лотов», а g0/N
                toks.append(f"n{g['lots']}")
        if d["thr"]:
            toks.append(f"s{_n(d['thr'])}")
        parts.append(" ".join(toks))
    return " | ".join(parts)


def _span(xs: list[float]) -> str:
    return _h(xs[0]) if len(xs) == 1 else f"{_h(xs[0])}–{_h(xs[-1])}"


def card_lines(data: dict) -> list[str]:
    """Короткие строки по монете (запасной вид /tv, когда нет цены для таблицы)."""
    out = []
    for sym, d in data["syms"].items():
        g = d["grid"]
        if not g or not (g["grids"] or g["skipped"]):
            continue
        bits = [f"{AVG_LABEL} {_h(g['avg'])} ({g['lots']} лот.)" if g["avg"] else "лотов нет"]
        if g["entries"]:
            bits.append(f"входы {_span(g['entries'])}" + (f" ({len(g['entries'])})" if len(g["entries"]) > 1 else ""))
        if g["tps"]:
            bits.append(f"ближайшие тейки {_span(g['tps'])}")
        cov = _coverage(g)
        if cov:
            bits.append(cov)
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
            end = datetime.fromtimestamp(day["end"], timezone.utc).astimezone() if day.get("end") else None
            lines.append(f"{sym[:3]} коридор дня {_h(day['lo'])}–{_h(day['hi'])}" + (f" · зоны {z}" if z else "")
                         + (f" · до {end:%d.%m %H:%M}" if end else ""))
        else:
            lines.append(f"{sym[:3]} коридор дня: действующего прогноза нет")
        if d["thr"]:
            lines.append(f"   лонги закроются, если день UTC закроется ниже {_h(d['thr'])}")
    body = scenario_lines(data) + level_lines(data)
    lines += [""] + [html.escape(x) for x in (body or card_lines(data))]
    lines += ["", "Скопируй строку в поле «Строка из бота» индикатора «bot7 · режим сеток» (на всех графиках одна и та же):",
              f"<code>{html.escape(tv_line(data))}</code>"]
    return "\n".join(lines)
