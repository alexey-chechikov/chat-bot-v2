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
               "cost": 0.0, "blocked": "", "error": ""}
        try:
            st = json.loads(run_files(name, False)[0].read_text(encoding="utf-8"))
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
    bag = sum(r["bag"] for r in rows)
    total = sum(r["total"] for r in rows)
    tail = f"Всего: мешок {_m(bag)} · итог {_m(total)}"
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
    st = {"cap": dict(state.get("cap") or {}), "bag": list(state.get("bag") or []), "thr": dict(state.get("thr") or {})}
    ev = []
    for r in rows:
        if "потолок" in r.get("blocked", "") and st["cap"].get(r["name"]) != day:
            st["cap"][r["name"]] = day
            ev.append(f"⛔ {r['name']} на потолке позиции — новых входов нет, ждёт тейков (лотов {r['lots']}, "
                      f"мешок {_m(r['bag'])})")
    bag = sum(r["bag"] for r in rows if not r.get("error"))
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
