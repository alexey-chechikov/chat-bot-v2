"""Сводка сеток WEEX и карта дня для Telegram (22.10, оператор: «где отчёты в телеграм, где аналитика» — при падении BTC
на 3.7%, мелких сетках на потолке и мешке −$179 в Telegram не пришло ничего: сетки пишут только об ошибках и закрытии
по режиму).

- report_text() — короткая сводка в цифрах: счёт, по каждой живой сетке лоты / мешок / закрыто / итог и «на потолке»,
  порог выхода по SMA100 и сколько будет мешок, если цена дойдёт до порога (модель доборов tv_levels._sim_down);
- render_map(sym) — PNG «карта дня»: 15m за 48 ч, коридор дня с шансом касания, входы и ближайшие тейки сеток,
  средняя лонгов, POC/VAH/VAL, вчерашние H/L, кластеры ликвидаций;
- risk_events() — события для пинга: сетка на потолке (раз в сутки на сетку), мешок всех лонгов пересёк −100/−250/
  −500/−1000 (с возвратом выше половины уровня), до порога выхода ≤3% и ≤1.5% (раз в сутки на символ).
Только чтение: учёт сеток, публичные свечи Binance, стакан и баланс WEEX. Ордеров нет.
"""
from __future__ import annotations

import io
import json
import logging
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
PING_STATE = ROOT / "state" / "grid_risk_pings.json"
BAG_LEVELS = (100.0, 250.0, 500.0, 1000.0)
THR_LEVELS = (3.0, 1.5)
RESUME_MIN_CAPPED_S = 3600          # «снова ставит входы» — только если на потолке стояла не меньше часа
RESUME_EVERY_S = 6 * 3600           # и не чаще раза в 6 ч на сетку
STALE_TICK_S = 600                  # нет полного успешного прохода дольше 10 мин (обычно ~45 с) — пинг G5
SHORT = {"BTCUSDT": "BTC", "ETHUSDT": "ETH"}
MAP_CAPTION = ("Карта дня {sym}: коридор с шансом касания (калиброван вне выборки), входы и ближайшие тейки сеток, средняя "
               "лонгов, плотность POC/VAH/VAL, вчерашние H/L, ликвидации")
DELIVERY = ROOT / "state" / "report_delivery.json"


def enabled(key: str) -> bool:
    """Выключатели в state/report_delivery.json: day_map (карты после утренней карточки), grid_risk_pings (риск-пинги)."""
    try:
        return bool(json.loads(DELIVERY.read_text(encoding="utf-8")).get(key, True))
    except (OSError, json.JSONDecodeError):
        return True


def ping_symbols(events: list[str], rows: list[dict]) -> list[str]:
    """Символы, к которым относятся события (для карт к пингу): по имени сетки или короткому имени символа."""
    out = []
    for sym, short in SHORT.items():
        names = [r["name"] for r in rows if r["sym"] == sym]
        if any(short in e or any(n in e for n in names) for e in events):
            out.append(sym)
    if any("Мешок всех" in e for e in events) and not out:
        out.append("BTCUSDT")
    return out


def _price(sym: str) -> float | None:
    try:
        from services.weex_api.client import WeexClient
        b, a = WeexClient().book(sym)
        return (b + a) / 2
    except Exception:                                           # noqa: BLE001
        logger.exception("grid_report.price_failed %s", sym)
        return None


def grid_rows(prices: dict[str, float | None] | None = None) -> list[dict]:
    """Живые сетки (enabled и не dry_run): лоты, мешок, закрыто за вычетом комиссий (обе стороны и переданный мешок —
    как итог в /weex), итог, «на потолке». Нечитаемый учёт — строка с error, остальные сетки видны."""
    from services.weex_grid import engine as eg
    from services.weex_grid.loop import run_files
    prices = {} if prices is None else prices
    rows = []
    for name in eg.GRIDS:
        cfg = eg.peek_config(name)
        if not cfg or not cfg.get("enabled") or cfg.get("dry_run"):
            continue
        sym = cfg["symbol"]
        if sym not in prices:
            prices[sym] = _price(sym)
        px = prices[sym]
        row = {"name": name, "sym": sym, "step": float(cfg["step_pct"]), "target": float(cfg["target_pct"]),
               "sides": cfg.get("sides") or ["LONG"], "lots": 0, "qty": 0.0, "bag": 0.0, "closed": 0.0,
               "cost": 0.0, "blocked": "", "error": "", "ok_ts": None, "tick_err": None}
        try:
            st = json.loads(run_files(name, False)[0].read_text(encoding="utf-8"))
            row["ok_ts"] = st.get("last_tick_ok_ts")                # 25.10 G5: последний полный успешный проход
            row["tick_err"] = st.get("last_tick_error")
            for side, d in (("LONG", 1), ("SHORT", -1)):
                s = st.get(side) or {}
                row["closed"] += float(s.get("realized") or 0) - float(s.get("fees") or 0) \
                    + float(s.get("transferred_mtm") or 0)
                for x in s.get("lots") or []:
                    q, e = float(x["qty"]), float(x["entry"])
                    row["lots"] += 1
                    row["qty"] += q * d
                    row["cost"] += q * e
                    if px:
                        row["bag"] += d * q * (px - e)
                if s.get("blocked") and side in row["sides"]:
                    row["blocked"] = str(s["blocked"])
        except Exception as exc:                                # noqa: BLE001
            logger.exception("grid_report.state_unreadable %s", name)
            row["error"] = type(exc).__name__
        if not row["error"] and row["lots"] and not px:
            row["error"] = "нет цены"                       # 25.10 G3: мешок неизвестен — не 0
        row["total"] = row["closed"] + row["bag"]
        rows.append(row)
    return rows


def equity() -> tuple[float, float] | None:
    """(счёт с открытыми позициями, нереализованный PnL) по USDT-фьючерсам WEEX."""
    try:
        from services.weex_api.client import WeexClient
        r = WeexClient().futures_balance()
        rows = r if isinstance(r, list) else (r.get("data") if isinstance(r, dict) and isinstance(r.get("data"), list)
                                              else [r])
        for b in rows:
            if isinstance(b, dict) and str(b.get("asset", "USDT")).upper() == "USDT" and b.get("balance") is not None:
                return float(b["balance"]), float(b.get("unrealizePnl") or 0)
    except Exception:                                           # noqa: BLE001
        logger.exception("grid_report.balance_failed")
    return None


def threshold_risk(data: dict) -> dict[str, dict]:
    """Порог выхода по SMA100 и мешок всех лонгов на пороге, если цена дойдёт туда при исполнении предусмотренных
    лимиток (tv_levels._sim_down — правила движка: шаг от нижнего лота, потолки). Не граница потерь: закрытие по рынку
    случится по закрытию дня ниже порога, цена может уйти глубже."""
    from services import tv_levels as tv
    out = {}
    for sym, d in data["syms"].items():
        g, thr, px = d.get("grid"), d.get("thr"), d.get("px")
        if not g or not thr or not px or not g.get("detail"):
            continue
        bag, adds = 0.0, 0
        for gd in g["detail"]:
            add, pos, _ = tv._sim_down(gd, thr, px)
            adds += len(add)
            bag += sum((thr - p) * q for p, q in pos) - sum(p * q * tv.FEE_MAKER for p, q in add)
        out[sym] = {"thr": thr, "px": px, "dist": (thr / px - 1) * 100, "bag": bag, "adds": adds}
    return out


def _m(x: float) -> str:
    return f"{x:+,.0f}$".replace("+-", "−").replace("-", "−")


def report_text(now: datetime | None = None, rows: list[dict] | None = None, data: dict | None = None,
                eq: tuple[float, float] | None | str = "read") -> str:
    from services import tv_levels as tv
    now = now or datetime.now(timezone.utc)
    rows = grid_rows() if rows is None else rows
    data = tv.collect(now) if data is None else data
    eq = equity() if eq == "read" else eq
    local = now.astimezone()
    head = f"📊 Сетки WEEX · {local:%d.%m %H:%M}"
    if eq:
        head += f" · счёт ${eq[0]:,.0f} (открытые {_m(eq[1])})"
    px_line = " · ".join(f"{SHORT.get(s, s)} {d['px']:,.0f}" for s, d in data["syms"].items() if d.get("px"))
    out = [head, px_line] if px_line else [head]
    for r in rows:
        if r["error"]:
            out.append(f"• {r['name']}: учёт не прочитан ({r['error']})")
            continue
        cap = " ⛔ на потолке — входов нет" if "потолок" in r["blocked"] else (f" ⚠️ {r['blocked']}" if r["blocked"] else "")
        out.append(f"• {r['name']} {r['step']:g}/{r['target']:g}: лотов {r['lots']}{cap} · мешок {_m(r['bag'])} · "
                   f"закрыто {_m(r['closed'])} → итог {_m(r['total'])}")
    ok = [r for r in rows if not r["error"]]                   # 25.10 G3: непрочитанное — не 0 в общем итоге
    bag = sum(r["bag"] for r in ok)
    total = sum(r["total"] for r in ok)
    miss = len(rows) - len(ok)
    tail = (f"Всего (без {miss} непрочитанных — итог неполный): " if miss else "Всего: ") + \
        f"мешок {_m(bag)} · итог {_m(total)}"
    used = sum(r["cost"] for r in rows)
    if data.get("cap"):
        tail += f" · занято ${used:,.0f} из ${data['cap']:,.0f}"
    out.append(tail)
    risk = threshold_risk(data)
    if risk:
        out.append("🛑 Выход по SMA100 (закрытие дня ниже): " + ", ".join(
            f"{SHORT.get(s, s)} {r['thr']:,.0f} ({r['dist']:+.1f}%)" for s, r in risk.items()))
        worst = sum(r["bag"] for r in risk.values())
        share = f" ({-worst / eq[0] * 100:.0f}% счёта)" if eq and eq[0] > 0 and worst < 0 else ""
        out.append("   если цена дойдёт до порога: " + ", ".join(
            f"{SHORT.get(s, s)} {_m(r['bag'])}" for s, r in risk.items()) + f" = {_m(worst)}{share}")
    return "\n".join(out)


def risk_events(rows: list[dict], risk: dict[str, dict], state: dict, now: datetime) -> tuple[list[str], dict]:
    """События для пинга и новое состояние. Сетка на потолке — раз в сутки на сетку; мешок всех лонгов ≤ −уровень — один
    раз на пересечение (уровень снимается, когда мешок вернулся выше половины уровня); до порога выхода ≤3% и ≤1.5% —
    раз в сутки на символ."""
    day = now.strftime("%Y-%m-%d")
    t = now.timestamp()
    st = {"cap": dict(state.get("cap") or {}), "bag": list(state.get("bag") or []), "thr": dict(state.get("thr") or {}),
          "capped": dict(state.get("capped") or {}), "resumed": dict(state.get("resumed") or {}),
          "stale": list(state.get("stale") or [])}
    ev = []
    # 25.10 (аудит GPT 481385e G5): задачу сеток никто не сторожил — упала или застряла, приложение живёт молча.
    # Сторож со стороны: нет полного успешного прохода дольше STALE_TICK_S — один пинг на эпизод, парный — когда пошли.
    # Перезапуска нет: слепой рестарт при неясных ордерах опасен (решение — оператору).
    stale = []
    for r in rows:
        ok = r.get("ok_ts")
        if r.get("error") in ("", None, "нет цены") and isinstance(ok, (int, float)) and t - ok > STALE_TICK_S:
            stale.append(r)
    names = sorted(r["name"] for r in stale)
    if stale and names != sorted(st["stale"]):
        new = [r for r in stale if r["name"] not in st["stale"]]
        if new:
            age = max(t - r["ok_ts"] for r in new) / 60
            err = next((r["tick_err"] for r in new if isinstance(r.get("tick_err"), dict)
                        and float(r["tick_err"].get("ts") or 0) >= float(r["ok_ts"])), None)
            why = f"; последняя ошибка: {err.get('phase')} — {str(err.get('err', ''))[:120]}" if err else \
                "; ошибок в учёте нет — цикл, похоже, стоит"
            ev.append(f"⚠️ Сетки {', '.join(r['name'] for r in new)}: нет полного прохода {age:.0f} мин — тейки и входы "
                      f"не сопровождаются{why}")
        st["stale"] = names
    elif not stale and st["stale"]:
        ok_now = [r["name"] for r in rows if r["name"] in st["stale"] and not r.get("error")]
        if ok_now:
            ev.append(f"✅ Сетки {', '.join(sorted(ok_now))} снова проходят цикл")
            st["stale"] = []
    for r in rows:
        name, at_cap = r["name"], "потолок" in r.get("blocked", "")
        if r.get("error"):
            continue
        if at_cap:
            st["capped"].setdefault(name, t)
            if st["cap"].get(name) != day:
                st["cap"][name] = day
                ev.append(f"⛔ {name} на потолке позиции — новых входов нет, ждёт тейков (лотов {r['lots']}, "
                          f"мешок {_m(r['bag'])})")
        elif name in st["capped"] and not r.get("blocked"):
            # 25.10 G2: только когда входы реально разрешены; ушла с потолка на паузу/долг/бюджет — ждём молча
            # 24.10 (оператор: «да»): парный пинг — сетка снова ставит входы. Только после упора ≥ RESUME_MIN_CAPPED_S и
            # не чаще раза в RESUME_EVERY_S на сетку (у самого потолка сетка качается: тейк → вход → снова потолок)
            since = float(st["capped"].pop(name))
            if t - since >= RESUME_MIN_CAPPED_S and t - float(st["resumed"].get(name) or 0) >= RESUME_EVERY_S:
                st["resumed"][name] = t
                ev.append(f"✅ {name} снова ставит входы — тейк освободил место под потолком (лотов {r['lots']}, "
                          f"мешок {_m(r['bag'])}; стояла {(t - since) / 3600:.1f} ч)")
    if not any(r.get("error") for r in rows):          # 25.10 G3: неполные данные уровни не трогают
        bag = sum(r["bag"] for r in rows)
        hit = [lv for lv in BAG_LEVELS if bag <= -lv]
        st["bag"] = [lv for lv in st["bag"] if bag <= -lv / 2]    # вернулся выше половины уровня — уровень снят
        new = [lv for lv in hit if lv not in st["bag"]]
        if new:
            st["bag"] = sorted(set(st["bag"]) | set(hit))
            ev.append(f"📉 Мешок всех лонг-сеток {_m(bag)} — ниже −{max(new):,.0f}$")
    for sym, r in risk.items():
        for lv in THR_LEVELS:
            key = f"{sym}:{lv:g}"
            if -r["dist"] <= lv and st["thr"].get(key) != day:
                st["thr"][key] = day
                ev.append(f"🛑 {SHORT.get(sym, sym)} в {-r['dist']:.1f}% от порога выхода {r['thr']:,.0f}: закрытие дня ниже — "
                          f"лонги закроются по рынку (мешок на пороге ≈ {_m(r['bag'])})")
                break
    return ev, st


RETRY_MAX = 6                       # недоставленный получателю срочный текст — повтор раз в проход (5 мин), до 30 мин


def ping_tick(chat_ids: list, send_text, send_photo, *, rows: list[dict], data: dict | None, state: dict,
              now: datetime, render=None, summary=None) -> dict:
    """Один проход риск-пингов (аудит GPT 481385e G1). Срочный текст событий уходит ПЕРВЫМ отдельным сообщением: ни
    сводка, ни карты, ни котировки его не держат. Состояние риска фиксируется, как только текст дошёл хотя бы одному
    получателю; кому не дошёл — очередь undelivered (получатель × текст), повтор каждый проход до RETRY_MAX попыток.
    Сводка и карты — отдельные попытки после текста: их сбой текст не отменяет и не повторяет. Нет данных котировок
    (data None) — события по порогу SMA не считаются, остальные идут. Возвращает новое состояние (пишет вызывающий);
    None — нечего записывать (событий не было и очередь не менялась)."""
    render = render or render_map
    summary = summary or (lambda: report_text(now=now, rows=rows, data=data))
    queue, left = list(state.get("undelivered") or []), []
    for q in queue:                                             # сначала — недоставленное прошлых проходов
        try:
            send_text(q["cid"], q["text"])
        except Exception:                                       # noqa: BLE001
            logger.exception("grid_risk_pings.retry_failed cid=%s", q["cid"])
            if q.get("attempts", 1) + 1 < RETRY_MAX:
                left.append({**q, "attempts": q.get("attempts", 1) + 1})
    try:
        risk = threshold_risk(data) if data else {}
    except Exception:                                           # noqa: BLE001
        logger.exception("grid_risk_pings.threshold_failed")
        risk = {}
    events, st = risk_events(rows, risk, state, now)
    same = {**state, "undelivered": left} if queue != left else None   # состояние риска прежнее, очередь — новая
    if not events:
        return same
    text = "\n".join(events)
    got, failed = [], []
    for cid in chat_ids:
        try:
            send_text(cid, text)
            got.append(cid)
        except Exception:                                       # noqa: BLE001
            logger.exception("grid_risk_pings.send_failed cid=%s", cid)
            failed.append(cid)
    if not got:
        return same                                             # не ушло никому — состояние риска не трогаем
    st["undelivered"] = left + [{"cid": c, "text": text, "ts": now.timestamp(), "attempts": 1} for c in failed]
    try:
        body = summary()
    except Exception as exc:                                    # noqa: BLE001
        logger.exception("grid_risk_pings.summary_failed")
        body = f"сводка не собрана: {type(exc).__name__}"
    for cid in got:
        try:
            send_text(cid, body)
        except Exception:                                       # noqa: BLE001
            logger.exception("grid_risk_pings.summary_send_failed cid=%s", cid)
    for sym in (ping_symbols(events, rows) if data else []):
        try:
            png = render(sym, data=data)
        except Exception:                                       # noqa: BLE001
            logger.exception("grid_risk_pings.map_failed %s", sym)
            continue
        for cid in got:
            try:
                send_photo(cid, png, MAP_CAPTION.format(sym=SHORT[sym]))
            except Exception:                                   # noqa: BLE001
                logger.exception("grid_risk_pings.photo_failed cid=%s", cid)
    logger.info("grid_risk_pings.sent events=%d recipients=%d failed=%d", len(events), len(got), len(failed))
    return st


def read_ping_state() -> dict:
    try:
        return json.loads(PING_STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_ping_state(st: dict) -> None:
    from services.weex_grid.engine import atomic_write
    atomic_write(PING_STATE, json.dumps(st, ensure_ascii=False))


def render_map(sym: str = "BTCUSDT", data: dict | None = None, now: datetime | None = None) -> bytes:
    """PNG «карта дня» по символу."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    from services import tv_levels as tv
    from services.scalp_levels import levels as sl
    now = now or datetime.now(timezone.utc)
    data = tv.collect(now) if data is None else data
    kl = json.load(urllib.request.urlopen(
        f"https://api.binance.com/api/v3/klines?symbol={sym}&interval=15m&limit=192", timeout=20))
    t = [datetime.fromtimestamp(k[0] / 1000, timezone.utc) for k in kl]
    o, h, l, c = ([float(k[i]) for k in kl] for i in (1, 2, 3, 4))
    s = data["syms"].get(sym) or {}
    px = c[-1]
    try:
        dens = sl.collect(sym)
    except Exception:                                           # noqa: BLE001
        logger.exception("grid_report.density_failed %s", sym)
        dens = {"levels": []}
    fig, ax = plt.subplots(figsize=(11, 6.2), dpi=110)
    w = (t[1] - t[0]) * 0.7
    for ti, oi, hi, li, ci in zip(t, o, h, l, c):
        col = "#26a69a" if ci >= oi else "#ef5350"
        ax.vlines(ti, li, hi, color=col, linewidth=0.8)
        ax.bar(ti, ci - oi if ci != oi else px * 1e-5, bottom=oi, width=w, color=col, edgecolor=col)
    labels: list[tuple[float, str, str]] = []
    lim = [min(l), max(h)]

    def hline(y, color, label, style="-", lw=1.0, alpha=0.9):
        ax.axhline(y, color=color, linestyle=style, linewidth=lw, alpha=alpha)
        labels.append((y, color, label))
        lim[0], lim[1] = min(lim[0], y), max(lim[1], y)

    day = s.get("day")
    if day:
        ax.axhspan(day["lo"], day["hi"], color="#90caf9", alpha=0.12)
        hline(day["hi"], "#1565c0", f"коридор дня {day['hi']:,.0f}", "--")
        hline(day["lo"], "#1565c0", f"коридор дня {day['lo']:,.0f}", "--")
        for zp, ch, side in day["zones"]:
            pct = ch * 100 if ch <= 1 else ch
            hline(zp, "#5e35b1", f"{'↑' if side == 'up' else '↓'} {zp:,.0f} — шанс касания {pct:.0f}%", ":", 0.9)
    g = s.get("grid") or {}
    for e in g.get("entries", [])[:3]:
        hline(e, "#2e7d32", f"вход сетки {e:,.0f}", "-", 1.3)
    for tp in g.get("tps", [])[:3]:
        hline(tp, "#f9a825", f"ближайший тейк {tp:,.0f}", "-", 1.1)
    if g.get("avg"):
        hline(g["avg"], "#6d4c41", f"средняя лонгов {g['avg']:,.0f} ({g['lots']} лотов)", "-.", 1.0)
    for lv in dens.get("levels", []):
        src = "+".join(lv["srcs"])
        if "бот" not in src and any(k in src for k in ("POC", "VAH", "VAL", "вчера", "liq")):
            hline(lv["price"], "#757575", f"{src} {lv['price']:,.0f}", (0, (2, 3)), 0.8, 0.7)
    ax.axhline(px, color="black", linewidth=0.6)
    pad = (lim[1] - lim[0]) * 0.03
    ax.set_ylim(lim[0] - pad, lim[1] + pad)
    ax.set_xlim(t[0], t[-1])
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m %H:%M", tz=now.astimezone().tzinfo))   # время мака
    thr = s.get("thr")
    sub = (f"режим ЛОНГ: лонги закроются, если день закроется ниже {thr:,.0f} ({(thr / px - 1) * 100:+.1f}%)"
           if thr else "режим: порог не прочитан")
    ax.set_title(f"{SHORT.get(sym, sym)} 15m · {px:,.0f} · {now.astimezone():%d.%m %H:%M}\n{sub}", fontsize=10, loc="left")
    ax.grid(alpha=0.15)
    fig.subplots_adjust(right=0.72)
    y0, y1 = ax.get_ylim()
    gap = (y1 - y0) * 0.032
    labels.sort()
    pos: list[float] = []
    for y, _, _ in labels:
        pos.append(max(y, pos[-1] + gap) if pos else y)
    shift = max(0.0, pos[-1] - y1) if pos else 0.0
    for (y, col, lab), yy in zip(labels, pos):
        ax.annotate(lab, xy=(t[-1], y), xytext=(1.01, (yy - shift - y0) / (y1 - y0)), textcoords="axes fraction",
                    fontsize=8, color=col, va="center", ha="left",
                    arrowprops=dict(arrowstyle="-", color=col, lw=0.5, alpha=0.6))
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()
