"""Daily self-report — раз в день в TG digest за прошедшие 24ч.

Что включает:
1. BitMEX balance Δ (start vs end of day)
2. Range Hunter signals fired / placed / outcomes (per symbol × variant)
3. Watchlist fires (label + count + last value)
4. Cascade alerts fired + edge_drift статус
5. Volatility regime по 3 символам сейчас
6. Pre-cascade fires
7. Confluence detections

Шлёт раз в день в 21:00 UTC (как weekly_self_report но daily).
"""
from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "state" / "daily_report_state.json"
REPORT_HOUR_UTC = 21


def _read_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(state: dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError:
        logger.exception("daily_report.state_write_failed")


def should_send(now: datetime) -> bool:
    """True если час == REPORT_HOUR_UTC и сегодня ещё не слали."""
    if now.hour != REPORT_HOUR_UTC:
        return False
    state = _read_state()
    last = state.get("last_sent_at")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
        return (now.date() != last_dt.date())
    except (ValueError, TypeError):
        return True


def mark_sent(now: datetime) -> None:
    state = _read_state()
    state["last_sent_at"] = now.isoformat(timespec="seconds")
    _write_state(state)


def _bitmex_delta_today() -> Optional[dict]:
    """Compute wallet balance Δ за последние 24h из margin_automated.jsonl."""
    margin_file = ROOT / "state" / "margin_automated.jsonl"
    if not margin_file.exists():
        return None
    rows = []
    try:
        with margin_file.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return None
    if not rows:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    rows_24h = []
    for r in rows:
        try:
            ts = datetime.fromisoformat(r["ts"].replace("Z", "+00:00"))
        except (ValueError, TypeError, KeyError):
            continue
        if ts >= cutoff:
            rows_24h.append(r)
    if not rows_24h:
        return None
    first = rows_24h[0]
    last = rows_24h[-1]
    return {
        "wallet_start": first.get("wallet_balance_usd"),
        "wallet_end": last.get("wallet_balance_usd"),
        "wallet_delta": (last.get("wallet_balance_usd", 0) or 0) - (first.get("wallet_balance_usd", 0) or 0),
        "available_end": last.get("available_margin_usd"),
        "dist_liq_end": last.get("distance_to_liquidation_pct"),
        "positions_end": last.get("positions_count"),
    }


def _rh_summary_24h() -> str:
    """Summary Range Hunter за 24ч по всем (symbol, variant)."""
    from services.range_hunter.journal import journal_path_for, read_all
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    lines = []
    total_signals = 0
    total_placed = 0
    total_resolved = 0
    total_pnl = 0.0
    for sym in ("BTCUSDT", "ETHUSDT", "XRPUSDT"):
        for variant in ("1m", "5m"):
            rows = read_all(path=journal_path_for(sym, variant))
            recent = []
            for r in rows:
                try:
                    ts = datetime.fromisoformat(r.get("ts_signal", ""))
                    if ts >= cutoff:
                        recent.append(r)
                except (ValueError, TypeError):
                    continue
            if not recent:
                continue
            n_sig = len(recent)
            n_placed = sum(1 for r in recent if r.get("user_action") == "placed")
            resolved = [r for r in recent if r.get("exit_reason") is not None]
            n_res = len(resolved)
            pnl = sum(float(r.get("pnl_usd") or 0) for r in resolved)
            total_signals += n_sig
            total_placed += n_placed
            total_resolved += n_res
            total_pnl += pnl
            if n_sig > 0:
                lines.append(f"  [{sym} {variant}] signals={n_sig}, placed={n_placed}, resolved={n_res}, pnl=${pnl:+.2f}")
    if not lines:
        return "  (нет RH сигналов за 24ч)"
    summary = f"  TOTAL: signals={total_signals}, placed={total_placed}, resolved={total_resolved}, pnl=${total_pnl:+.2f}"
    return summary + "\n" + "\n".join(lines)


def _watchlist_24h() -> str:
    """Watchlist fires per label за 24ч."""
    journal = ROOT / "state" / "play_journal.jsonl"
    if not journal.exists():
        return "  (нет watchlist fires)"
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    fires_by_label: dict[str, int] = {}
    try:
        for line in journal.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                ts = datetime.fromisoformat(rec.get("ts_fire", ""))
                if ts >= cutoff:
                    lbl = rec.get("label", "?")
                    fires_by_label[lbl] = fires_by_label.get(lbl, 0) + 1
            except (ValueError, KeyError, json.JSONDecodeError):
                continue
    except OSError:
        return "  (журнал недоступен)"
    if not fires_by_label:
        return "  (нет watchlist fires)"
    return "\n".join(f"  • {lbl}: {n}" for lbl, n in sorted(fires_by_label.items(), key=lambda x: -x[1]))


def _vol_regime_summary() -> str:
    try:
        from services.volatility_regime import current_regime
        lines = []
        for sym in ("BTCUSDT", "ETHUSDT", "XRPUSDT"):
            reg, vol = current_regime(sym)
            emoji = "🟢" if reg == "low" else "🟡" if reg == "medium" else "🔴"
            vs = f"{vol:.0f}%" if vol is not None else "N/A"
            lines.append(f"  {emoji} {sym}: {reg.upper()} ({vs})")
        return "\n".join(lines)
    except Exception:
        return "  (vol regime недоступен)"


def _edge_drift_summary() -> str:
    drift_file = ROOT / "state" / "cascade_edge_drift.json"
    if not drift_file.exists():
        return "  (нет данных edge drift)"
    try:
        drift = json.loads(drift_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "  (нет данных edge drift)"
    drifted = [k for k, v in drift.items() if v.get("drifted")]
    if drifted:
        return "  ❌ Drifted: " + ", ".join(drifted)
    return "  ✓ Все edges в норме"


def _confluence_count_24h() -> str:
    journal = ROOT / "state" / "confluence_fires.jsonl"
    if not journal.exists():
        return "  (нет confluence fires)"
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    fires = []
    try:
        for line in journal.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                ts = datetime.fromisoformat(rec.get("ts", ""))
                if ts >= cutoff:
                    fires.append(rec)
            except (ValueError, json.JSONDecodeError):
                continue
    except OSError:
        return "  (журнал недоступен)"
    if not fires:
        return "  (нет confluence fires за 24ч)"
    return "\n".join(f"  • {f.get('direction')} confluence: {f.get('count')} источников @ {f.get('ts', '?')[:19]}" for f in fires[-5:])


def build_report(now: Optional[datetime] = None) -> str:
    if now is None:
        now = datetime.now(timezone.utc)
    lines = [
        "📰 ДНЕВНОЙ ОТЧЁТ",
        f"Период: {(now - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M')} → {now.strftime('%Y-%m-%d %H:%M')} UTC",
        "",
    ]
    # BitMEX
    bm = _bitmex_delta_today()
    if bm:
        lines.append("💰 BitMEX за 24ч:")
        lines.append(f"  Wallet: ${bm['wallet_start']:,.2f} → ${bm['wallet_end']:,.2f}  (Δ ${bm['wallet_delta']:+,.2f})")
        lines.append(f"  Available margin: ${bm['available_end']:,.2f}")
        lines.append(f"  Dist to liq: {bm['dist_liq_end']:.1f}%  |  Positions: {bm['positions_end']}")
        lines.append("")
    # Range Hunter
    lines.append("🎯 Range Hunter (24ч):")
    lines.append(_rh_summary_24h())
    lines.append("")
    # Watchlist
    lines.append("🔔 Watchlist fires (24ч):")
    lines.append(_watchlist_24h())
    lines.append("")
    # Confluence
    lines.append("🔥 Confluence (24ч):")
    lines.append(_confluence_count_24h())
    lines.append("")
    # Vol regime
    lines.append("🌊 Volatility regime (текущий):")
    lines.append(_vol_regime_summary())
    lines.append("")
    # Edge drift
    lines.append("⚠️ Edge drift status:")
    lines.append(_edge_drift_summary())
    lines.append("")
    lines.append("— конец отчёта —")
    return "\n".join(lines)


def maybe_send_daily(*, send_fn: Callable[[str], None],
                       now: Optional[datetime] = None) -> bool:
    if now is None:
        now = datetime.now(timezone.utc)
    if not should_send(now):
        return False
    from services.reports.push_policy import scheduled_push_enabled
    if not scheduled_push_enabled():
        logger.info("daily_self_report.push_off (отчёты по команде)")
        mark_sent(now)  # окно закрываем, чтобы не пересобирать каждый тик
        return False
    text = build_report(now)
    try:
        send_fn(text)
    except Exception:
        logger.exception("daily_report.send_failed")
        return False
    mark_sent(now)
    return True
