"""«Что изменилось за сутки и что из этого следует» — первый блок утренней карточки и /map (22.10, оператор: «мне не
хватает именно аналитики и выводов и сравнения, что изменилось за вчера; сухие данные, не привязанные ни к чему, — 0
пользы»).

Каждая строка — сегодня против вчера и что это значит механически (OI и цена → кто двигал; ликвидации → чьё плечо
вымыли; топ-трейдеры и фандинг → куда сместились позиции). Затем — что такое состояние значило на истории (наши замеры
2 лет, с числом случаев и половинами) и вывод одной фразой с последствием для живых сеток.

Честность: прогноз направления у нас опровергнут многократно (CLAUDE.md). Поэтому перевес пишется только из таблицы
маршрутов (research/weex/route_table.py: что первым за 24 ч, +1% или −1%, по состоянию «цена против максимума/минимума
12 ч»), со словом «слабый», если интервал задевает 50%, и «нет», если половины расходятся. Механическое толкование OI и
ликвидаций — не прогноз, а объяснение, кто двигал цену.
"""
from __future__ import annotations

import csv
import json
import logging
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
ROUTE = ROOT / "state" / "market_brief" / "route_table.json"
DRIVER = {"OI↓ цена↓": "падение — закрытие лонгов (вымывание плеча), а не приход новых продавцов",
          "OI↑ цена↓": "падение на новых шортах — продавцы набирают позиции",
          "OI↑ цена↑": "рост на новых лонгах — покупатели набирают позиции",
          "OI↓ цена↑": "рост на закрытии шортов (шорт-сквиз), новых покупателей мало"}
SHORT_OI = {"OI↓ цена↓": "закрывали лонги, новых шортов нет", "OI↑ цена↓": "открывали шорты",
            "OI↑ цена↑": "открывали лонги", "OI↓ цена↑": "закрывали шорты"}


def _p(x: float | None, d: int = 1) -> str:
    return "—" if x is None else f"{x * 100:+.{d}f}%".replace("-", "−")


def _n(x: float, fmt: str) -> str:
    """Число со знаком и настоящим минусом (дефисы в словах не трогаем)."""
    return format(x, fmt).replace("-", "−")


def _usd(x: float | None) -> str:
    if x is None:
        return "—"
    return f"${x / 1e6:.1f}M" if x >= 1e6 else f"${x / 1e3:.0f}K"


def liq_window(sym: str, start_h: float, end_h: float, now: datetime | None = None) -> tuple[float, float] | None:
    """Ликвидации (лонги, шорты) в $ за окно [now−start_h, now−end_h) по нашему сборщику (Bybit/OKX/Binance)."""
    from services.market_brief.brief import LIQ
    p = LIQ.get(sym)
    if not p or not p.exists():
        return None
    now = now or datetime.now(timezone.utc)
    a, b = now - timedelta(hours=start_h), now - timedelta(hours=end_h)
    lng = sht = 0.0
    with open(p, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                t = datetime.fromisoformat(r["ts_utc"])
                if not (a <= t < b):
                    continue
                usd = float(r["qty"]) * float(r["price"])
            except (KeyError, ValueError):
                continue
            if r["side"] == "long":
                lng += usd
            else:
                sht += usd
    return lng, sht


def _state_of(c: float, hmax: float, lmin: float) -> str:
    dd, ru = c / hmax - 1, c / lmin - 1
    if -dd >= ru:
        return "падение ≥3.5%" if dd <= -0.035 else "падение 2–3.5%" if dd <= -0.02 else "спокойно"
    return "рост ≥3.5%" if ru >= 0.035 else "рост 2–3.5%" if ru >= 0.02 else "спокойно"


def current_state(sym: str) -> dict | None:
    try:
        kl = json.load(urllib.request.urlopen(
            f"https://api.binance.com/api/v3/klines?symbol={sym}&interval=1m&limit=721", timeout=20))
    except Exception:                                           # noqa: BLE001
        logger.exception("story.klines_failed %s", sym)
        return None
    kl = kl[:-1]                                                # последняя минута не закрыта
    hs, ls = [float(k[2]) for k in kl], [float(k[3]) for k in kl]
    c = float(kl[-1][4])
    hmax, lmin = max(hs), min(ls)
    return {"state": _state_of(c, hmax, lmin), "px": c, "dd": c / hmax - 1, "ru": c / lmin - 1, "hmax": hmax, "lmin": lmin}


def route_row(sym: str, state: str, table: dict | None = None) -> dict | None:
    if table is None:
        try:
            table = json.loads(ROUTE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    return ((table.get("symbols") or {}).get(sym) or {}).get("states", {}).get(state)


def route_phrase(r: dict | None) -> tuple[str, str]:
    """(строка «раньше в таком состоянии», короткий вывод о перевесе) по строке таблицы маршрутов."""
    if not r or not r.get("n"):
        return "", "по этому состоянию данных нет"
    p, lo, hi, n = r["p_up"], r["lo"], r["hi"], r["n"]
    h = [x for x in (r.get("halves") or []) if x is not None]
    same_side = len(h) == 2 and ((h[0] - .5) * (h[1] - .5) > 0)
    hv = " / ".join(f"{x * 100:.0f}%" for x in h)
    side = "вниз" if p < .5 else "вверх"
    first = 1 - p if p < .5 else p
    move = "−1%" if p < .5 else "+1%"
    other = "+1%" if p < .5 else "−1%"
    if n < 50 or abs(p - .5) < .05 or not same_side:         # 53/47 — шум, «перевес» только от 55/45
        verdict = "направления нет (≈50/50)"
    elif lo > .5 or hi < .5:
        verdict = f"устойчивый перевес {side}: сначала {move} в {first * 100:.0f}%"
    else:
        verdict = f"слабый перевес {side}: сначала {move} в {first * 100:.0f}%"
    line = (f"сначала {move}, чем {other}, в {first * 100:.0f}% случаев ({n}; половины {hv}) — {verdict.split(':')[0]}"
            if "перевес" in verdict else f"сначала +1% в {p * 100:.0f}% ({n} случаев) — направления нет")
    return line, verdict


LINK = {("OI↑ цена↑", "OI↓ цена↓"): "вчерашний рост на новых лонгах откатили закрытием этих же лонгов — плечо вымыто, "
                                    "новых продавцов нет",
        ("OI↑ цена↑", "OI↑ цена↓"): "после роста на лонгах пришли продавцы — сегодня открывают шорты",
        ("OI↓ цена↑", "OI↓ цена↓"): "вчера закрывали шорты, сегодня лонги — плечо сокращают с обеих сторон",
        ("OI↑ цена↓", "OI↑ цена↑"): "вчера давили шортами, сегодня рост на новых лонгах — покупатели перехватили",
        ("OI↑ цена↓", "OI↓ цена↑"): "вчерашние шорты закрывают — отскок на откупе, не на новых покупках",
        ("OI↓ цена↓", "OI↑ цена↑"): "после вымывания лонгов набирают новые лонги",
        ("OI↓ цена↓", "OI↑ цена↓"): "после вымывания лонгов пришли продавцы — набирают шорты"}


def conclusion(op: str, op_y: str, cond: dict, t: dict, y: dict, lq: dict, qstat: dict | None, rverdict: str) -> str:
    """Вывод одной фразой: связка вчера → сегодня (кто двигал цену), что сместилось в позициях, перевес на сутки по
    таблице маршрутов и что такой день значил раньше. Шаблоны фиксированы — не подбираются по результату."""
    if (op_y, op) in LINK:
        head = LINK[(op_y, op)]
    elif op and op == op_y and op in DRIVER:
        head = "второй день подряд " + DRIVER[op]
    else:
        head = DRIVER.get(op, "позиции почти не менялись — движение без смены плеча")
    extra = []
    top = cond.get("top_ls", "")
    if top == "топ-трейдеры сократили лонги":
        extra.append("топы сократили лонги")
    elif top == "топ-трейдеры добавили лонгов":
        extra.append("топы добавили лонгов" + (" в падение" if (t.get("ret") or 0) < 0 else ""))
    if t.get("funding") is not None and y.get("funding") is not None:
        if cond.get("funding") == "фандинг высокий":
            extra.append("лонги перегреты (фандинг высокий)")
        elif t["funding"] < y["funding"] - 1e-6:
            extra.append("фандинг остыл")
        elif t["funding"] > y["funding"] + 1e-6:
            extra.append("фандинг греется")
    lt, st_ = (lq or {}).get("long_usd"), (lq or {}).get("short_usd")
    if lt is not None and st_ is not None:
        if lt > 2 * max(st_, 1):
            extra.append("ликвидировали в основном лонги")
        elif st_ > 2 * max(lt, 1):
            extra.append("ликвидировали в основном шорты")
    s = head + (" (" + ", ".join(extra) + ")" if extra else "") + f". На сутки — {rverdict}"
    if qstat and qstat.get("n") and op:
        s += (f"; после таких дней рост бывал {qstat['up'] * 100:.0f}% против {qstat['up_base'] * 100:.0f}% обычно"
              + (" — заметное отличие" if qstat.get("up_diff") else " — в пределах шума"))
    return s + "."


def _share(ls: float) -> float:
    """Доля лонгов в позициях при отношении лонги/шорты ls."""
    return ls / (1 + ls)


def top_line(t: dict, y: dict, cond: dict, hist: list[float] | None) -> list[str]:
    """24.10 (оператор: «из этого я не вижу, куда стоят топ-трейдеры — в лонг или шорт»): доля лонгов/шортов топов в
    процентах, сравнение с нормой 2 лет (квартили L/S по дневной истории) и изменение доли за сутки в п.п. — сегодня и
    вчера. L/S Binance топ-трейдеров по позициям: >1 — лонгов больше."""
    ls, d = t.get("top_ls"), t.get("dls")
    if ls is None or d is None:
        return []
    sh = _share(ls)
    head = f"• Топ-трейдеры: {sh * 100:.0f}% в лонгах / {100 - sh * 100:.0f}% в шортах (L/S {ls:.2f}"
    if hist and len(hist) >= 100:
        q1, med, q3 = (hist[int(p * (len(hist) - 1))] for p in (.25, .5, .75))
        norm = ("лонгов меньше обычного" if ls < q1 else "лонгов больше обычного" if ls > q3 else "в норме")
        pct = sum(v < ls for v in hist) / len(hist) * 100
        head += f"; обычно {med:.2f}, сейчас выше, чем в {pct:.0f}% дней за 2 года — {norm}"
    head += ")"

    def pp(x: float) -> str:
        return "0" if abs(x) < 0.5 else _n(x, "+.0f")
    ch = (sh - _share(ls - d)) * 100
    yd = ""
    if y.get("dls") is not None:
        y_end = ls - d
        ych = (_share(y_end) - _share(y_end - y["dls"])) * 100
        yd = f"; вчера {pp(ych)} п.п."
    top = cond.get("top_ls", "")
    word = {"топ-трейдеры добавили лонгов": "добавили лонгов", "топ-трейдеры сократили лонги": "сократили лонги"}
    return [head + f" · за сутки доля лонгов {pp(ch)} п.п.{yd} → {word.get(top, 'почти без изменений')}"]


def compose(sym: str, lv: dict, liq_y: tuple[float, float] | None, qstat: dict | None, cond: dict,
            route: dict | None, st: dict | None, levels: str = "", grids: str = "",
            cond_y: dict | None = None, top_hist: list[float] | None = None) -> list[str]:
    cond_y = cond_y or {}
    """Текст блока по готовым данным (без сети — для тестов)."""
    c3 = sym[:3]
    t, y = lv["today"], lv["yday"]
    px = lv["price"]
    out = [f"🧭 {c3} {px:,.0f}" if c3 == "BTC" else f"🧭 {c3} {px:,.2f}"]
    out[0] += " · что изменилось за сутки и что из этого следует"
    pr = f"• Цена: {_p(t['ret'])} за сутки (вчера {_p(y['ret'])})"
    if st:
        pr += (f" · от максимума 12 ч {_p(st['dd'])}" if -st["dd"] >= st["ru"] else f" · от минимума 12 ч {_p(st['ru'])}")
    out.append(pr)
    op = cond.get("oi_price", "")
    if t.get("oi_chg_pct") is not None:
        out.append(f"• Позиции (OI): {_n(t['oi_chg_pct'], '+.1f')}% (вчера {_n(y['oi_chg_pct'], '+.1f')}%)"
                   + (f" → {SHORT_OI[op]}" if op in SHORT_OI else " → почти без изменений"))
    out += top_line(t, y, cond, top_hist)
    lq = lv.get("liq") or {}
    if lq.get("long_usd") is not None:
        lt, st_ = lq["long_usd"], lq["short_usd"]
        yd = f" (вчера {_usd(liq_y[0])} / {_usd(liq_y[1])})" if liq_y else ""
        who = ("вымыли лонги" if lt > 2 * max(st_, 1) else "вымыли шорты" if st_ > 2 * max(lt, 1)
               else "ликвидации с обеих сторон")
        out.append(f"• Ликвидации 24 ч: лонги {_usd(lt)} / шорты {_usd(st_)}{yd} → {who}")
    if t.get("funding") is not None:
        f_t, f_y = t["funding"], y.get("funding")
        lvl = cond.get("funding", "")
        mood = {"фандинг высокий": "лонги перегреты", "фандинг низкий": "перекос в шорты"}.get(lvl, "ставка обычная")
        trend = ("" if f_y is None else " · остывает" if f_t < f_y - 1e-6 else " · греется" if f_t > f_y + 1e-6 else "")
        fy = f" (вчера {f_y * 100:.3f}%)" if f_y is not None else ""
        out.append(f"• Фандинг {f_t * 100:.3f}%/сут{fy} → {mood}{trend}")
    out.append(f"📌 Раньше в таком состоянии (2 года {c3}):")
    if qstat and qstat.get("n") and op:
        diff = "заметно " + ("чаще" if qstat["up"] > qstat["up_base"] else "реже") if qstat.get("up_diff") \
            else "в пределах шума"
        out.append(f"• после «{op}» рост на следующий день {qstat['up'] * 100:.0f}% (обычно {qstat['up_base'] * 100:.0f}%, "
                   f"{qstat['n']} дн.) — {diff}")
    rline, rverdict = route_phrase(route)
    if st and rline:
        out.append(f"• {st['state']} от уровня 12 ч → {rline}")
    concl = "✅ Вывод: " + conclusion(op, cond_y.get("oi_price", ""), cond, t, y, lq, qstat, rverdict)
    out.append(concl)
    if levels:
        out.append(levels)
    if grids:
        out.append(grids)
    return out


def levels_line(sym: str, now: datetime) -> str:
    """Зоны ликвидаций CoinGlass (BTC) и шанс касания по прогнозу дня."""
    parts = []
    try:
        if sym == "BTCUSDT":
            from services.coinglass_web.section import _snaps
            snaps = _snaps()
            if snaps:
                lv = snaps[-1]["levels"]
                for arrow, name, key in (("↓", "лонговые ликвидации", "zones_long"), ("↑", "шортовые", "zones_short")):
                    z = (lv.get(key) or [None])[0]
                    if z and z.get("lo") and z.get("hi"):
                        parts.append(f"{arrow} {name} {z['lo']:,.0f}–{z['hi']:,.0f}")
    except Exception:                                           # noqa: BLE001
        logger.exception("story.zones_failed")
    try:
        from services import tv_levels
        day = tv_levels.day_corridor(now).get(sym)
        if day and day["zones"]:
            parts.append("дотянется до конца окна: " + ", ".join(
                f"{p:,.0f} — {(c * 100 if c <= 1 else c):.0f}%" for p, c, _ in day["zones"]))
    except Exception:                                           # noqa: BLE001
        logger.exception("story.corridor_failed")
    yl = yday_hl_line(sym)
    out = ("📍 " + " · ".join(parts)) if parts else ""
    return (out + "\n" + yl) if (out and yl) else (out or yl)


YDAY_NOTE = "здесь чаще пробой, чем отскок: 57/43 (2 года BTC и ETH, обе половины) — не ставить лимитки «на отскок», стоп — дальше"


def yday_hl_line(sym: str) -> str:
    """24.10 (research/weex/level_reaction.py): у вчерашних H/L при первом касании за день пробой на 0.5% раньше отскока
    в 57–58% против ~50% у случайных уровней — BTC 638 касаний, ETH 641, обе половины. Единственный уровень карты, чьё
    поведение отличается от случайного; сделка от уровня после расходов в минусе, пробой ≈0 — это подсказка к стопам."""
    try:
        kl = json.load(urllib.request.urlopen(
            f"https://api.binance.com/api/v3/klines?symbol={sym}&interval=1d&limit=2", timeout=20))
        yh, yl = float(kl[0][2]), float(kl[0][3])
    except Exception:                                           # noqa: BLE001
        logger.exception("story.yday_failed %s", sym)
        return ""
    fmt = "{:,.0f}" if sym == "BTCUSDT" else "{:,.2f}"
    return f"🧱 Вчера H {fmt.format(yh)} / L {fmt.format(yl)} — {YDAY_NOTE}"


def grids_line(sym: str) -> str:
    """Что это значит для живых сеток символа: кто на потолке, мешок, расстояние до выхода по SMA100."""
    try:
        from services import grid_report, tv_levels
        rows = [r for r in grid_report.grid_rows() if r["sym"] == sym and not r["error"]]
        thr, px = tv_levels.market((sym,))
    except Exception:                                           # noqa: BLE001
        logger.exception("story.grids_failed")
        return ""
    if not rows:
        return ""
    cap = [r["name"] for r in rows if "потолок" in r["blocked"]]
    bag = sum(r["bag"] for r in rows)
    s = f"🕸 Сетки {sym[:3]}: мешок {_n(bag, '+,.0f')}$"
    if cap:
        s += f" · на потолке {', '.join(cap)} — доливов нет, ждут отскока"
    if thr.get(sym) and px.get(sym):
        s += f" · до выхода по SMA100 {_n((thr[sym] / px[sym] - 1) * 100, '+.1f')}%"
    return s


def story_lines(sym: str, now: datetime | None = None) -> list[str]:
    from services.market_brief import brief, history
    now = now or datetime.now(timezone.utc)
    lv = brief.live(sym)
    rows = history.read_features(sym)
    labeled, th = brief.label_days(rows)
    t = lv["today"]
    cond = brief.conditions(t["ret"], t["oi_chg_pct"], t["funding"], t["taker"], t["dls"], th)
    op = cond.get("oi_price")
    qstat = brief.stat(labeled, "oi_price", op) if op else None
    st = current_state(sym)
    route = route_row(sym, st["state"]) if st else None
    y = lv["yday"]
    cond_y = brief.conditions(y["ret"], y["oi_chg_pct"], y["funding"], y["taker"], y["dls"], th)
    hist = sorted(float(r["top_ls"]) for r in rows if r.get("top_ls") not in (None, ""))
    return compose(sym, lv, liq_window(sym, 48, 24, now), qstat, cond, route, st, levels_line(sym, now), grids_line(sym),
                   cond_y=cond_y, top_hist=hist)


def block(now: datetime | None = None) -> list[str]:
    """Блок для карточки и /map: BTC и ETH; сбой одной монеты не ломает другую."""
    out = []
    for sym in ("BTCUSDT", "ETHUSDT"):
        try:
            out += (["" ] if out else []) + story_lines(sym, now)
        except Exception as exc:                                # noqa: BLE001
            logger.exception("story.failed %s", sym)
            out += (["" ] if out else []) + [f"🧭 {sym[:3]}: аналитика не собрана ({type(exc).__name__})"]
    return out
