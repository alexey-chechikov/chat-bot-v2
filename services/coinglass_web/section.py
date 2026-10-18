"""Блок CoinGlass в утренней сводке: зоны и ближнее поле сейчас против вчера, ликвидации всех бирж, исход вчерашнего
утреннего снимка, накопленный счёт «сильная зона — магнит или нет». Только то, что записал сборщик."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from services.coinglass_web import outcomes
from services.coinglass_web.collector import DIR


def _snaps() -> list[dict]:
    p = DIR / "snapshots.jsonl"
    out = []
    for line in (p.read_text(encoding="utf-8").splitlines() if p.exists() else []):
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return [s for s in out if s.get("levels")]


def _near(snaps: list[dict], target: datetime, tol_h: float = 3) -> dict | None:
    best = min(snaps, key=lambda s: abs(datetime.fromisoformat(s["ts"]) - target), default=None)
    if best and abs(datetime.fromisoformat(best["ts"]) - target) <= timedelta(hours=tol_h):
        return best
    return None


def _z(z: dict | None) -> str:
    return "нет значимых" if not z else f"{z['lo']:,.0f}–{z['hi']:,.0f} ({z['dist_pct']:+.1f}%, сила {z['strength']:,.0f})"


LAST: dict = {}                     # какой снимок попал в последний собранный блок — для журнала доставки


def section(now: datetime | None = None) -> str:
    text = _section(now)
    LAST["section_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return text


def _section(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    LAST.clear()
    try:
        outcomes.update(now)
    except Exception:                                           # noqa: BLE001 — досверка не ломает сводку
        pass
    snaps = _snaps()
    if not snaps:
        return "🧲 CoinGlass: снимков ещё нет"
    cur = snaps[-1]
    LAST.update(snapshot_run_id=cur.get("run_id", cur["ts"]), snapshot_levels_captured=cur.get("levels_captured"))
    prev = _near(snaps, datetime.fromisoformat(cur["ts"]) - timedelta(hours=24))
    lv, lq = cur["levels"], cur.get("liquidations") or {}
    t = datetime.fromisoformat(cur["ts"]).astimezone()
    lines = [f"🧲 CoinGlass (Binance BTC, снимок {t:%H:%M}):"]
    zs, zl = (lv.get("zones_short") or [None])[0], (lv.get("zones_long") or [None])[0]
    lines.append(f"• магнитные зоны: шорты сверху {_z(zs)} · лонги снизу {_z(zl)}")
    if prev:
        pl = prev["levels"]
        ps, pll = (pl.get("zones_short") or [None])[0], (pl.get("zones_long") or [None])[0]
        lines.append(f"  сутки назад: сверху {_z(ps)} · снизу {_z(pll)}")
    nr = lv.get("near")
    if nr:
        ch = f", доля шортов {nr['short_pp_24h']:+d} п.п. за сутки" if nr.get("short_pp_24h") is not None else ""
        lines.append(f"• ближнее поле ±3%: лонги {nr['long_pct']}% / шорты {nr['short_pct']}%{ch}")
    if lq:
        vs = f" · {lq['vs_7d']:.2f}× к средней за 7 дн." if lq.get("vs_7d") else ""
        lines.append(f"• ликвидации 24 ч (все биржи): лонги ${lq['long_24h'] / 1e6:.1f}M / шорты "
                     f"${lq['short_24h'] / 1e6:.1f}M{vs}")
    # исход вчерашнего снимка 07:00 Варшавы (правила v1: сильнейшие зоны, полная сетка минут, эмпирическая база)
    p = DIR / "outcomes.jsonl"
    outs = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []
    yday = (now.astimezone(outcomes.WARSAW) - timedelta(days=1)).strftime("%Y-%m-%d")
    mine = [o for o in outs if o.get("rules") == outcomes.RULES and o.get("outcome") != "missing"
            and datetime.fromisoformat(o["captured"]).astimezone(outcomes.WARSAW).strftime("%Y-%m-%d") == yday
            and datetime.fromisoformat(o["captured"]).astimezone(outcomes.WARSAW).hour == 7]
    if mine:
        o = mine[0]
        word = {"upper": "верхняя (зона шортов)", "lower": "нижняя (зона лонгов)", "both": "обе в одном часе",
                "none": "ни одна"}[o["outcome"]]
        b = o.get("base") or {}
        exp = (f" — по прошлым окнам при тех же расстояниях в ATR: верхняя {b['upper'] * 100:.0f}%, нижняя "
               f"{b['lower'] * 100:.0f}%, ни одна {b['none'] * 100:.0f}%") if b else ""
        lines.append(f"• вчера в 07:00 (v1, разведочно): за сутки первой задета {word}{exp}; цена "
                     f"{o['ret_24h'] * 100:+.1f}%, размах {o['range_24h'] * 100:.1f}%")
    t = outcomes.table()
    if t["n"] == 0:
        lines.append("• таблица зон (v1, разведочно): исходов ещё нет — первый снимок 07:00 досверится через сутки")
    else:
        lines.append("• таблица зон (v1, разведочно; снимки 07:00 → 24 ч): n {n} дн.; наблюдалось верхняя {ou:.0f}% / "
                     "нижняя {ol:.0f}% / ни одна {on:.0f}%, ожидалось {eu:.0f}% / {el:.0f}% / {en:.0f}%".format(
                         n=t["n"], ou=t["obs"]["upper"] * 100, ol=t["obs"]["lower"] * 100, on=t["obs"]["none"] * 100,
                         eu=t["exp"]["upper"] * 100, el=t["exp"]["lower"] * 100, en=t["exp"]["none"] * 100)
                     + ("" if t["n"] >= 30 else " — мало дней для выводов"))
    lines.append(c1_line())
    return "\n".join(lines)


def c1_line() -> str:
    """Протокол C1 разрешает ежедневно только счётчики, качество и описательный эффект — без выводов до 23.10.2027."""
    try:
        from services.coinglass_web import c1
        s = c1.summary()
    except Exception as exc:                                    # noqa: BLE001
        return f"• C1: сводка не прочитана ({type(exc).__name__})"
    st = ", ".join(f"{k} {v}" for k, v in sorted(s["status"].items())) or "слотов ещё нет"
    eff = (f"; описательно сильная зона первой минус база {s['D_low_desc'] * 100:+.0f}…{s['D_high_desc'] * 100:+.0f} п.п."
           if s["resolved"] else "")
    return (f"• C1 (единственный разбор 23.10.2027): слотов {s['slots']}/{s['planned']} — {st}; исходов {s['resolved']}"
            f"{eff} — не вывод")
