"""Суточный отчёт по СЧЁТУ, а не по журналу оркестратора.

Оператор 2026-08-28 показал прежний отчёт: «Всего событий: 2, ботов
затронуто: 1, btc_short: REDUCE → RUN». В тот день по журналам служб было
726 записей, три закрытых ордера на +$13.42 и две остановки риск-контуром
— ничего из этого в отчёт не попало.

Причина: прежний отчёт читал CalibrationLog оркестратора, который с 2 мая
не выдал ни одной команды, а бот в нём — btc_short_l1, у которого вообще
нет id GinArea (см. tools/config_coverage.py).

Здесь читаются журналы служб, которые реально трогают деньги, плюс живое
состояние счёта.
"""
from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "state"

SOURCES = {
    "harvester": STATE / "order_harvester_journal.jsonl",
    "autotune": STATE / "grid_autotune_journal.jsonl",
    "risk": STATE / "risk_guard_journal.jsonl",
    "pauses": STATE / "short_bots_audit.jsonl",
}


def _read_day(path: Path, day: str) -> list[dict]:
    if not path.exists():
        return []
    out = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        ts = str(r.get("ts") or r.get("ts_utc") or r.get("time") or "")
        if ts.startswith(day):
            out.append(r)
    return out


def _account_state(api=None) -> dict | None:
    """Живое состояние счёта. None — если не дотянулись (не выдумываем)."""
    try:
        from services.risk_guard.loop import load_config, snapshot
        cfg = load_config()
        if not cfg.get("bots"):
            return None
        if api is None:
            from services.order_harvester.loop import _cached_api
            api = _cached_api()
        if api is None:
            return None
        snap = snapshot(api, cfg)
        return None if snap.get("error") else {**snap, "cfg": cfg}
    except Exception:
        logger.exception("daily_account_report.state_failed")
        return None


def build_report(day: str | date | None = None, api=None) -> str:
    if day is None:
        day = datetime.now(timezone.utc).date()
    day_s = day.isoformat() if isinstance(day, date) else str(day)

    harvest = _read_day(SOURCES["harvester"], day_s)
    autotune = _read_day(SOURCES["autotune"], day_s)
    risk = _read_day(SOURCES["risk"], day_s)
    pauses = _read_day(SOURCES["pauses"], day_s)

    L = [f"📘 СЧЁТ ЗА {day_s}", ""]

    # ── деньги ────────────────────────────────────────────────────────
    closed = [r for r in harvest if r.get("event") == "ORDER_CLOSED"]
    earned = sum(float(r.get("profit_usd") or 0) for r in closed)
    L.append("ДЕНЬГИ")
    if closed:
        by_bot = defaultdict(lambda: [0, 0.0])
        for r in closed:
            b = by_bot[str(r.get("alias") or r.get("bot_id"))]
            b[0] += 1
            b[1] += float(r.get("profit_usd") or 0)
        L.append(f"  зафиксировано {len(closed)} ордеров на +${earned:,.2f}")
        for alias, (n, s) in sorted(by_bot.items(), key=lambda kv: -kv[1][1]):
            L.append(f"    {alias}: {n} шт, +${s:,.2f}")
    else:
        L.append("  ордеров не закрывалось")

    # ── состояние ─────────────────────────────────────────────────────
    st = _account_state(api)
    L.append("")
    L.append("СОСТОЯНИЕ")
    if st is None:
        L.append("  не прочитано — состояние счёта недоступно")
    else:
        cfg = st["cfg"]
        dep = float(cfg.get("deposit_usd") or 0)
        kill = dep * float(cfg.get("kill_pct", 10)) / 100
        L.append(f"  депозит ${dep:,.0f}   позиция ${st['total_notional_usd']:,.0f}"
                 f"   плечо {st['leverage']}x")
        L.append(f"  мешок ${st['total_unrealized_usd']:,.2f}"
                 f"   до предела ${kill + st['total_unrealized_usd']:,.0f}")
        for r in st.get("rows", []):
            pct = (r["unrealized_usd"] / dep * 100) if dep else 0
            L.append(f"    {r['alias']}: ${r['notional_usd']:,.0f}, "
                     f"мешок ${r['unrealized_usd']:,.2f} ({pct:+.1f}% деп)")

    # ── риск-контур ───────────────────────────────────────────────────
    L.append("")
    L.append("РИСК-КОНТУР")
    if risk:
        c = Counter(str(r.get("event")) for r in risk)
        L.append("  " + ", ".join(f"{k} ×{v}" for k, v in c.most_common(4)))
        acted = [r for r in risk if r.get("event") in
                 ("HALT", "KILL", "LIMIT_NO_CLOSE")]
        if acted:
            last = acted[-1]
            L.append(f"  последнее действие: {last.get('event')} — "
                     f"{str(last.get('reason'))[:110]}")
    else:
        L.append("  не вмешивался")

    # ── шаг сетки ─────────────────────────────────────────────────────
    L.append("")
    L.append("ШАГ СЕТКИ")
    applied = [r for r in autotune if r.get("event") == "LADDER_APPLIED"]
    held = sum(1 for r in autotune if r.get("event") == "LADDER_MANUAL_HELD")
    if applied:
        for r in applied:
            L.append(f"  {r.get('alias')}: {r.get('gs_from')} → "
                     f"{r.get('gs_to')} (занято {r.get('occupancy_pct')}%)")
    else:
        L.append("  не менялся")
    if held:
        L.append(f"  ручное значение удержано {held} раз")

    # ── паузы ─────────────────────────────────────────────────────────
    if pauses:
        c = Counter(str(r.get("action") or r.get("event")) for r in pauses)
        L.append("")
        L.append("ПАУЗЫ БОТОВ")
        L.append("  " + ", ".join(f"{k} ×{v}" for k, v in c.most_common(4)))

    total = len(harvest) + len(autotune) + len(risk) + len(pauses)
    L.append("")
    L.append(f"записей в журналах за сутки: {total}")
    return "\n".join(L)


def is_empty_day(day: str | date | None = None) -> bool:
    """День без единой записи — отчёт можно не слать."""
    if day is None:
        day = datetime.now(timezone.utc).date()
    day_s = day.isoformat() if isinstance(day, date) else str(day)
    return not any(_read_day(p, day_s) for p in SOURCES.values())
