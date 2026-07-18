"""Weekly self-report для оператора.

Раз в неделю (вс 18:00 UTC) собирает:
1. Cascade KPI summary (n + accuracy по бакетам/горизонтам).
2. Edge drift flags (что выдохлось).
3. Live config summary (что запущено, expected vs реализованный — TBD).
4. Anomalies: peak_USD по любому SHORT-боту > 100k (нарушение risk-limit).

Шлёт одним сообщением в PRIMARY-канал TG.
"""
from __future__ import annotations

import csv
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

STATE_PATH = Path("state/weekly_report_state.json")
SNAPSHOTS_CSV = Path("ginarea_live/snapshots.csv")
PEAK_USD_LIMIT = 100_000.0
REPORT_DOW = 6  # Sunday
REPORT_HOUR_UTC = 18


def _read_state(path: Path = STATE_PATH) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(state: dict, path: Path = STATE_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        logger.exception("weekly_report.write_state_failed")


def should_send(now: datetime, *, state_path: Path = STATE_PATH) -> bool:
    """True если today=Sunday + hour>=18 UTC + не отправлен на этой неделе."""
    if now.weekday() != REPORT_DOW or now.hour < REPORT_HOUR_UTC:
        return False
    state = _read_state(state_path)
    last_iso = state.get("last_sent_at")
    if not last_iso:
        return True
    try:
        last_sent = datetime.fromisoformat(last_iso)
    except ValueError:
        return True
    return (now - last_sent).total_seconds() >= 518400  # 6 days


def mark_sent(now: datetime, *, state_path: Path = STATE_PATH) -> None:
    state = _read_state(state_path)
    state["last_sent_at"] = now.isoformat(timespec="seconds")
    _write_state(state, state_path)


def _peak_positions_week(
    *,
    snapshots: Path = SNAPSHOTS_CSV,
    now: datetime,
    window_days: int = 7,
) -> dict[str, float]:
    """Найти пиковый |position * avg_price| за неделю по каждому боту."""
    if not snapshots.exists():
        return {}
    cutoff = now - timedelta(days=window_days)
    peaks: dict[str, float] = defaultdict(float)
    try:
        with snapshots.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                ts_str = row.get("ts_utc", "")
                try:
                    ts = datetime.fromisoformat(ts_str)
                except ValueError:
                    continue
                if ts < cutoff:
                    continue
                bid = row.get("bot_id", "").strip()
                if not bid:
                    continue
                try:
                    pos = abs(float(row.get("position") or 0))
                    avg = float(row.get("average_price") or 0)
                    bal = float(row.get("balance") or 0)
                except ValueError:
                    continue
                # 2026-06-21 (Win-аудит): inverse XBTUSD position уже в USD-контрактах
                # (1 контракт=$1) → notional = |pos|, НЕ pos*avg (иначе ×price = гарблено
                # «peak $527089k»). Linear: pos в BTC × avg = USD. Inverse: balance XBT < 5.
                is_inverse = 0 < bal < 5
                peak_usd = pos if is_inverse else pos * avg
                if peak_usd > peaks[bid]:
                    peaks[bid] = peak_usd
    except OSError:
        return dict(peaks)
    return dict(peaks)


def build_report(
    *,
    summary_fn: Callable[..., dict],
    drift_summary_fn: Callable[..., dict],
    now: Optional[datetime] = None,
    snapshots: Path = SNAPSHOTS_CSV,
) -> str:
    """Build human-readable weekly report text (Russian)."""
    if now is None:
        now = datetime.now(timezone.utc)
    lines: list[str] = []
    lines.append("📊 ЕЖЕНЕДЕЛЬНЫЙ ОТЧЁТ")
    lines.append(f"Неделя по {now.strftime('%Y-%m-%d')}")
    lines.append("")

    try:
        summary = summary_fn(min_samples=3)
    except Exception:
        logger.exception("weekly_report.summary_failed")
        summary = {"total": 0, "by_bucket": {}}

    total = summary.get("total", 0)
    lines.append(f"🔔 Каскадных alert'ов: {total}")

    by_bucket = summary.get("by_bucket", {}) or {}
    if not by_bucket or not any(by_bucket.values()):
        lines.append("  (накоплено мало данных для accuracy summary)")
    else:
        for bucket, horizons in by_bucket.items():
            if not horizons:
                continue
            parts: list[str] = []
            for h, s in sorted(horizons.items()):
                parts.append(f"{h}: {s['accuracy']:.0f}% (n={s['n']})")
            lines.append(f"  {bucket}: {' | '.join(parts)}")
    lines.append("")

    try:
        drift = drift_summary_fn()
    except Exception:
        logger.exception("weekly_report.drift_summary_failed")
        drift = {"drifted_count": 0, "drifted": []}

    drifted_n = drift.get("drifted_count", 0)
    if drifted_n > 0:
        lines.append(f"⚠️ EDGE DRIFTED ({drifted_n}):")
        for key in drift.get("drifted", []):
            lines.append(f"  — {key}")
    else:
        lines.append("✅ Edge drift: всё в норме")
    lines.append("")

    peaks = _peak_positions_week(snapshots=snapshots, now=now)
    over_limit = [(bid, p) for bid, p in peaks.items() if p > PEAK_USD_LIMIT]
    if over_limit:
        lines.append(f"🚨 Превышение risk-limit ${PEAK_USD_LIMIT / 1000:.0f}k:")
        for bid, peak in sorted(over_limit, key=lambda x: -x[1])[:5]:
            lines.append(f"  {bid}: peak ${peak / 1000:.0f}k")
    elif peaks:
        top_bid, top_peak = max(peaks.items(), key=lambda x: x[1])
        lines.append(f"✅ Все боты в risk-limit (макс ${top_peak / 1000:.0f}k у {top_bid})")
    else:
        lines.append("(snapshots не найдены)")
    lines.append("")

    try:
        from services.pre_cascade_alert.score_autotune import analyze, format_report_section
        autotune = analyze(now=now, window_days=7)
        lines.append(format_report_section(autotune))
    except Exception:
        logger.exception("weekly_report.autotune_failed")
    lines.append("")
    lines.append("— конец отчёта —")
    return "\n".join(lines)


def maybe_send_weekly(
    *,
    send_fn: Callable[[str], None],
    summary_fn: Callable[..., dict],
    drift_summary_fn: Callable[..., dict],
    now: Optional[datetime] = None,
    state_path: Path = STATE_PATH,
    snapshots: Path = SNAPSHOTS_CSV,
) -> bool:
    """Вернёт True если отчёт был отправлен."""
    if now is None:
        now = datetime.now(timezone.utc)
    if not should_send(now, state_path=state_path):
        return False
    from services.reports.push_policy import scheduled_push_enabled
    if not scheduled_push_enabled():
        logger.info("weekly_self_report.push_off (отчёты по команде)")
        mark_sent(now, state_path=state_path)
        return False
    text = build_report(
        summary_fn=summary_fn,
        drift_summary_fn=drift_summary_fn,
        now=now,
        snapshots=snapshots,
    )
    try:
        send_fn(text)
    except Exception:
        logger.exception("weekly_report.send_failed")
        return False
    mark_sent(now, state_path=state_path)
    return True
