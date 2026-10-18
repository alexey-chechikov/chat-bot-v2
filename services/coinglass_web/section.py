"""Блок CoinGlass в утренней сводке: зоны и ближнее поле сейчас против вчера, ликвидации всех бирж, исход вчерашнего
утреннего снимка, накопленный счёт «сильная зона — магнит или нет». Только то, что записал сборщик."""
from __future__ import annotations

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


def section(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    try:
        outcomes.update(now)
    except Exception:                                           # noqa: BLE001 — досверка не ломает сводку
        pass
    snaps = _snaps()
    if not snaps:
        return "🧲 CoinGlass: снимков ещё нет"
    cur = snaps[-1]
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
    # исход вчерашнего утреннего (первого за день) снимка на 24 ч
    p = DIR / "outcomes.jsonl"
    outs = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x] if p.exists() else []
    yday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    first = sorted((o for o in outs if o["ts"][:10] == yday and o["horizon"] == "24h"), key=lambda o: o["ts"])
    if first:
        o = first[0]
        word = {"upper": "сверху (зона шортов)", "lower": "снизу (зона лонгов)", "both": "обе в одну минуту",
                "none": "ни одна"}[o["outcome"]]
        lines.append(f"• вчерашнее утро: первой сработала {word}; по расстояниям шанс верхней был "
                     f"{o['base_up'] * 100:.0f}%; цена за сутки {o['ret'] * 100:+.1f}%")
    st = outcomes.stats("24h", daily=True)
    if st["n"] == 0:
        lines.append("• счёт зон: исходов ещё нет — копится (первый день — завтра)")
    else:
        verdict = ("зоны работают как магнит: верхняя срабатывает чаще ожидания" if st["differs"] and st["obs_up"] >
                   st["base_up"] else "сильная зона срабатывает реже ожидания" if st["differs"] else
                   f"пока не отличается от случайности{' (нужно n ≥ 30 дней)' if st['n'] < 30 else ''}")
        lines.append(f"• счёт зон (утро → 24 ч): n {st['n']} дн., верхняя первой {st['obs_up'] * 100:.0f}% при "
                     f"ожидании по расстояниям {st['base_up'] * 100:.0f}% — {verdict}")
    return "\n".join(lines)
