"""Weekly paper-signal P&L report → TG, Sunday 18:00-19:00 UTC.

Tracks per-source paper-trade outcomes (cascade_alert, spike_alert, grid_coord,
market_intel, level_break). При запуске в окне Sun 18:00-19:00 UTC, шлёт
сводку. Dedup через state/paper_signal_weekly_sent.json чтоб не слать дважды.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

SENT_STATE = Path("state/paper_signal_weekly_sent.json")
WINDOW_START_HOUR_UTC = 18
WINDOW_END_HOUR_UTC = 19


def _last_sent_week() -> Optional[tuple[int, int]]:
    if not SENT_STATE.exists():
        return None
    try:
        d = json.loads(SENT_STATE.read_text(encoding="utf-8"))
        return tuple(d.get("year_week", [None, None]))
    except (OSError, json.JSONDecodeError):
        return None


def _mark_sent(year: int, week: int) -> None:
    try:
        SENT_STATE.parent.mkdir(parents=True, exist_ok=True)
        SENT_STATE.write_text(json.dumps({"year_week": [year, week]}), encoding="utf-8")
    except OSError:
        logger.exception("paper_signal_weekly.write_state_failed")


def _build_report() -> str:
    """Re-use scripts/weekly_paper_signal_report.py aggregator."""
    from datetime import timedelta
    import sys
    from pathlib import Path as _P
    sys.path.insert(0, str(_P(__file__).resolve().parents[2]))
    from scripts.weekly_paper_signal_report import aggregate, format_report
    from services.paper_signal_tracker.journal import JOURNAL_PATH, read_all

    until = datetime.now(timezone.utc)
    since = until - timedelta(days=7)
    rows = read_all(path=JOURNAL_PATH)
    agg = aggregate(rows, since)
    return format_report(agg, since, until)


def maybe_send_paper_signal_weekly(*, send_fn: Optional[Callable] = None,
                                     now: Optional[datetime] = None) -> bool:
    """Returns True если report был отправлен."""
    from services.reports.push_policy import scheduled_push_enabled
    if send_fn is not None and not scheduled_push_enabled():
        send_fn = None  # отчёт строится в лог (dry_run), пуш выключен оператором
    if now is None:
        now = datetime.now(timezone.utc)
    # Sunday = 6 в isoweekday (Mon=1..Sun=7); weekday() Mon=0..Sun=6
    if now.weekday() != 6:
        return False
    if not (WINDOW_START_HOUR_UTC <= now.hour < WINDOW_END_HOUR_UTC):
        return False
    iso_year, iso_week, _ = now.isocalendar()
    last = _last_sent_week()
    if last == (iso_year, iso_week):
        return False  # already sent this week

    report = _build_report()
    if send_fn is None:
        logger.info("paper_signal_weekly.dry_run\n%s", report)
        _mark_sent(iso_year, iso_week)
        return True
    try:
        # TG message length limit ~4096 chars. Trim if longer.
        msg = report[:3900] + ("\n…(truncated)" if len(report) > 3900 else "")
        send_fn(msg)
        _mark_sent(iso_year, iso_week)
        logger.info("paper_signal_weekly.sent week=%s-W%s", iso_year, iso_week)
        return True
    except Exception:
        logger.exception("paper_signal_weekly.send_failed")
        return False
