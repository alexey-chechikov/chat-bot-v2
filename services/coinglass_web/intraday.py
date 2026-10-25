"""Дневные сводки CoinGlass в 14:00 и 16:00 Варшавы (оператор 20.10: «давать информацию, что изменилось по CoinGlass
с утра»). Шлёт сборщик сразу после своего прогона в эти часы.

Что в сводке — только описание, направление не прогнозируется:
  - цена и магнитные зоны сейчас против снимка 08:00 (сдвиг краёв, сила), ближнее поле ±3%;
  - ликвидации всех бирж за 4 и 12 ч (окна страницы CoinGlass);
  - как идёт утренний прогноз размаха (day_range): коридор пока удержан/пробит, задеты ли зоны и когда, какой
    был утренний шанс — по минуткам Binance от начала окна прогноза.
Отправка — только при report_delivery.json "coinglass_intraday": true; одна на (дату, час); журнал intraday_log.jsonl.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from services.coinglass_web.collector import DIR, ROOT

logger = logging.getLogger(__name__)
WARSAW = ZoneInfo("Europe/Warsaw")
HOURS = (14, 16)
LOG = DIR / "intraday_log.jsonl"
MIN = 60_000


def _snaps() -> list[dict]:
    p = DIR / "snapshots.jsonl"
    out = []
    for line in (p.read_text(encoding="utf-8").splitlines() if p.exists() else []):
        try:
            s = json.loads(line)
        except ValueError:
            continue
        if s.get("levels") and s.get("levels_captured"):
            out.append(s)
    return out


def _near(snaps: list[dict], t: datetime, before_min: int, after_min: int) -> dict | None:
    """Последний снимок, полученный в [t − before; t + after]."""
    best = None
    for s in snaps:
        cap = datetime.fromisoformat(s["levels_captured"])
        if t - timedelta(minutes=before_min) <= cap <= t + timedelta(minutes=after_min):
            best = s
    return best


def _zone(z: dict | None) -> str:
    return "нет" if not z else f"{z['lo']:,.0f}–{z['hi']:,.0f} (сила {z['strength']:,.0f})"


def _zone_change(name: str, m: dict | None, c: dict | None) -> str:
    if not m and not c:
        return f"• {name}: значимых нет"
    if not m or not c:
        return f"• {name}: утром {_zone(m)} → сейчас {_zone(c)}"
    same = c["lo"] <= m["hi"] and m["lo"] <= c["hi"]                # диапазоны пересекаются — та же зона
    ds = (c["strength"] / m["strength"] - 1) * 100 if m["strength"] else 0.0
    if same:
        return (f"• {name}: та же {_zone(c)}; сила {m['strength']:,.0f} → {c['strength']:,.0f} ({ds:+.0f}%)"
                + (f", края сдвинулись с {m['lo']:,.0f}–{m['hi']:,.0f}" if (m["lo"], m["hi"]) != (c["lo"], c["hi"]) else ""))
    return f"• {name}: утром {_zone(m)} → сейчас другая {_zone(c)}"


def _forecast_progress(now: datetime) -> list[str]:
    """Утренний прогноз размаха (day_range, текущая версия): коридор и касания зон от начала окна до сейчас."""
    from services.coinglass_web import day_range as dr
    day = dr.issue_day(now).isoformat()
    out = []
    now_ms = int(now.timestamp() * 1000) // MIN * MIN
    for f in (r for r in dr._mine("forecast") if r["date"] == day):
        if now_ms <= f["A_ms"]:
            continue
        rows = [r for r in (dr.klines(f["sym"], "1m", f["A_ms"], now_ms) or []) if int(r[0]) < now_ms]
        if not rows:
            continue
        # 25.10 (аудит GPT A2): «внутри» и «не задета» — только при полном покрытии закрытых минут окна (как финальная
        # проверка day_range._check_one); увиденное касание/пробой утверждается всегда, отсутствие — нет
        expected = (now_ms - f["A_ms"]) // MIN
        seen = {int(r[0]) for r in rows}
        missing = [t for t in range(f["A_ms"], now_ms, MIN) if t not in seen]
        full = not missing and len(seen) == expected
        gap = "" if full else f" · наблюдения неполные: {len(seen)} из {expected} мин"
        hi, lo = max(float(r[2]) for r in rows), min(float(r[3]) for r in rows)
        clo, chi = f["corridor"]
        broke = " и ".join(w for w, b in (("пробит вверх", hi > chi), ("пробит вниз", lo < clo)) if b)
        st = broke or ("пока внутри" if full else "по увиденным минутам внутри, пробой в пропусках не исключён")
        p = dr._p
        out.append(f"• {f['sym'][:3]}: коридор дня {p(clo, f['sym'])}–{p(chi, f['sym'])} {st} "
                   f"(с утра макс {p(hi, f['sym'])}, мин {p(lo, f['sym'])}){gap}")
        for x in f["levels"]:
            hit = next((r for r in sorted(rows, key=lambda r: int(r[0]))
                        if (float(r[2]) >= x["price"] if x["side"] == "up" else float(r[3]) <= x["price"])), None)
            when = (datetime.fromtimestamp(int(hit[0]) / 1000, timezone.utc).astimezone(WARSAW).strftime("%H:%M")
                    if hit else None)
            if when:
                early_gap = any(t < int(hit[0]) for t in missing)
                res = f"задета в {when}" if not early_gap else f"задета не позже {when} (до этого пропуски)"
            else:
                res = "не задета" if full else "неизвестно — пропуски в данных"
            out.append(f"  {x['name']} {p(x['price'], f['sym'])}: {res} (утром шанс {x['chance'] * 100:.0f}%)")
    return out


def build(now: datetime | None = None) -> str | None:
    now = now or datetime.now(timezone.utc)
    loc = now.astimezone(WARSAW)
    snaps = _snaps()
    morning = _near(snaps, datetime(loc.year, loc.month, loc.day, 8, tzinfo=WARSAW), 10, 10)
    cur = _near(snaps, now, 70, 0)
    if not cur:
        return None
    lc = cur["levels"]
    cap = datetime.fromisoformat(cur["levels_captured"]).astimezone(WARSAW)
    lines = [f"🧲 CoinGlass {cap:%H:%M} — что изменилось с утра (описание, не сигнал)"]
    if morning:
        lm = morning["levels"]
        dp = (lc["price"] / lm["price"] - 1) * 100 if lm.get("price") else 0.0
        lines.append(f"• BTC {lm['price']:,.0f} → {lc['price']:,.0f} ({dp:+.1f}%)")
        lines.append(_zone_change("шорты сверху", (lm.get("zones_short") or [None])[0], (lc.get("zones_short") or [None])[0]))
        lines.append(_zone_change("лонги снизу", (lm.get("zones_long") or [None])[0], (lc.get("zones_long") or [None])[0]))
        nm, nc = lm.get("near"), lc.get("near")
        if nm and nc:
            lines.append(f"• ближнее поле ±3%: шорты {nm['short_pct']}% → {nc['short_pct']}% "
                         f"({nc['short_pct'] - nm['short_pct']:+d} п.п.)")
    else:
        lines.append("• утреннего снимка 08:00 нет — сравнить не с чем")
        lines.append(f"• BTC {lc['price']:,.0f}; шорты сверху {_zone((lc.get('zones_short') or [None])[0])}; "
                     f"лонги снизу {_zone((lc.get('zones_long') or [None])[0])}")
    w = (cur.get("liquidations") or {}).get("windows") or {}
    if w.get("4h") and w.get("12h"):
        lines.append(f"• ликвидации (все биржи): за 4 ч лонги ${w['4h']['long'] / 1e6:.1f}M / шорты "
                     f"${w['4h']['short'] / 1e6:.1f}M; за 12 ч ${w['12h']['long'] / 1e6:.1f}M / "
                     f"${w['12h']['short'] / 1e6:.1f}M")
    try:
        prog = _forecast_progress(now)
    except Exception:                                           # noqa: BLE001
        logger.exception("coinglass_intraday.progress_failed")
        prog = []
    if prog:
        lines.append("Утренний прогноз размаха:")
        lines += prog
    return "\n".join(lines)


def _enabled() -> bool:
    try:
        return bool(json.loads((ROOT / "state" / "report_delivery.json").read_text(encoding="utf-8"))
                    .get("coinglass_intraday", False))
    except (OSError, ValueError):
        return False


def maybe_send(now: datetime | None = None, send_fn=None) -> bool:
    """В 14:xx и 16:xx Варшавы, один раз на (дату, час). send_fn — для тестов; по умолчанию TelegramAlertClient."""
    now = now or datetime.now(timezone.utc)
    loc = now.astimezone(WARSAW)
    if loc.hour not in HOURS or not _enabled():
        return False
    key = (loc.strftime("%Y-%m-%d"), loc.hour)
    done = [json.loads(x) for x in LOG.read_text(encoding="utf-8").splitlines() if x.strip()] if LOG.exists() else []
    if any((r["date"], r["hour"]) == key and r.get("ok") for r in done):
        return False
    text = build(now)
    if not text:
        return False
    if send_fn is None:
        from services.telegram_alert_client import TelegramAlertClient
        send_fn = TelegramAlertClient.instance().send
    try:
        ok = bool(send_fn(text))
    except Exception:                                           # noqa: BLE001
        logger.exception("coinglass_intraday.send_failed")
        ok = False
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"date": key[0], "hour": key[1], "sent_utc": now.isoformat(timespec="seconds"), "ok": ok,
                            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}, ensure_ascii=False) + "\n")
    return ok
