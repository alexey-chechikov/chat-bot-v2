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
    lines = [f"🧲 CoinGlass · BTC, снимок {t:%H:%M}"]
    pl = prev["levels"] if prev else {}
    for arrow, name, key in (("↑", "шорты", "zones_short"), ("↓", "лонги", "zones_long")):
        z, pz = (lv.get(key) or [None])[0], (pl.get(key) or [None])[0]
        lines.append(f"{arrow} {name} {_z(z)}" + (f" · вчера {_zprev(z, pz)}" if prev else ""))
    nr = lv.get("near")
    if nr:
        ch = f" ({nr['short_pp_24h']:+d} п.п. за сутки)" if nr.get("short_pp_24h") is not None else ""
        lines.append(f"Ближнее поле ±3%: шорты {nr['short_pct']}% / лонги {nr['long_pct']}%{ch}")
    if lq:
        vs = f" ({lq['vs_7d']:.2f}× к средней 7 дн.)" if lq.get("vs_7d") else ""
        lines.append(f"Ликвидации 24 ч (все биржи): лонги ${lq['long_24h'] / 1e6:.1f}M · шорты "
                     f"${lq['short_24h'] / 1e6:.1f}M{vs}")
    lines.append(c1_line())
    return "\n".join(lines)


def c1_line() -> str:
    """Протокол C1 разрешает ежедневно только счётчики, качество и описательный эффект — без выводов до 23.10.2027."""
    try:
        from services.coinglass_web import c1
        s = c1.summary()
    except Exception as exc:                                    # noqa: BLE001
        return f"C1: сводка не прочитана ({type(exc).__name__})"
    eff = (f" · описательно {s['D_low_desc'] * 100:+.0f}…{s['D_high_desc'] * 100:+.0f} п.п." if s["resolved"] else "")
    return (f"C1 (годовая проверка, разбор 23.10.2027): утр {s['slots']}/{s['planned']} · засчитано {s['admitted']} · "
            f"исходов {s['resolved']}{eff} — не вывод")


def _zprev(z: dict | None, pz: dict | None) -> str:
    """Вчерашняя зона той же стороны: та же (диапазоны пересекаются) — только сила; другая — её диапазон."""
    if not pz:
        return "нет"
    if z and z["lo"] <= pz["hi"] and pz["lo"] <= z["hi"]:
        return f"та же, сила {pz['strength']:,.0f}"
    return f"{pz['lo']:,.0f}–{pz['hi']:,.0f} (сила {pz['strength']:,.0f})"
