"""Daily morning digest → TG, 09:00-10:00 UTC.

Короткая утренняя сводка (≤20 строк):
  - Сколько paper-signals за вчера, per-source
  - Сколько RH signals (placed vs pending)
  - Сколько каскадов, пред-каскадов
  - Сколько pause-events на TB
  - Статус A/B TB vs T1 (volume Δ за вчера)

Dedup через state/daily_digest_sent.json — 1 раз за UTC день.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

SENT_STATE = Path("state/daily_digest_sent.json")
WINDOW_START_HOUR_UTC = 9
WINDOW_END_HOUR_UTC = 10


def _last_sent_date() -> Optional[str]:
    if not SENT_STATE.exists():
        return None
    try:
        return json.loads(SENT_STATE.read_text(encoding="utf-8")).get("date")
    except (OSError, json.JSONDecodeError):
        return None


def _mark_sent(date_str: str) -> None:
    try:
        SENT_STATE.parent.mkdir(parents=True, exist_ok=True)
        SENT_STATE.write_text(json.dumps({"date": date_str}), encoding="utf-8")
    except OSError:
        logger.exception("daily_digest.write_state_failed")


def _count_paper_signals_yesterday(yesterday: datetime) -> dict[str, dict]:
    """Read state/paper_signals.jsonl, count per-source for date yesterday-UTC."""
    from services.paper_signal_tracker.journal import JOURNAL_PATH, read_all
    rows = read_all(path=JOURNAL_PATH)
    out: dict[str, dict] = {}
    day_str = yesterday.strftime("%Y-%m-%d")
    for r in rows:
        ts = r.get("ts_signal", "")
        if not ts.startswith(day_str):
            continue
        src = r.get("source", "?")
        d = out.setdefault(src, {"n": 0, "tp": 0, "sl": 0, "to": 0, "pending": 0, "pnl": 0.0})
        d["n"] += 1
        outcome = r.get("outcome")
        if outcome == "tp_hit":
            d["tp"] += 1
        elif outcome == "sl_hit":
            d["sl"] += 1
        elif outcome == "timeout":
            d["to"] += 1
        else:
            d["pending"] += 1
        d["pnl"] += float(r.get("pnl_usd") or 0)
    return out


def _count_rh_signals_yesterday(yesterday: datetime) -> dict:
    from services.range_hunter.journal import journal_path_for, read_all
    out = {"total": 0, "placed": 0, "skipped": 0, "pending": 0}
    day_str = yesterday.strftime("%Y-%m-%d")
    for sym in ("BTCUSDT", "ETHUSDT", "XRPUSDT"):
        p = journal_path_for(sym, "1m")
        for r in read_all(path=p):
            ts = r.get("ts_signal", "")
            if not ts.startswith(day_str):
                continue
            out["total"] += 1
            ua = r.get("user_action")
            if ua == "placed":
                out["placed"] += 1
            elif ua == "skipped":
                out["skipped"] += 1
            else:
                out["pending"] += 1
    return out


def _count_tb_pauses_yesterday(yesterday: datetime) -> int:
    """Count short_bots_guard.paused entries for TB id in app.log."""
    n = 0
    log = Path("logs/app.log")
    if not log.exists():
        return 0
    day_str = yesterday.strftime("%Y-%m-%d")
    try:
        for line in log.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.startswith(day_str):
                continue
            if "short_bots_guard.paused bot=4525648417" in line:
                n += 1
    except OSError:
        pass
    return n


def _build_report(now: datetime) -> str:
    yesterday = now - timedelta(days=1)
    yest_str = yesterday.strftime("%Y-%m-%d")
    lines = [
        f"☀ DAILY DIGEST — {yest_str} UTC",
        "",
    ]

    # Paper signals
    paper = _count_paper_signals_yesterday(yesterday)
    if paper:
        lines.append("📊 Paper signals (вчерашние):")
        for src in sorted(paper.keys()):
            d = paper[src]
            closed = d["tp"] + d["sl"] + d["to"]
            wr = (100 * d["tp"] / closed) if closed else 0
            pnl_sign = "+" if d["pnl"] >= 0 else ""
            lines.append(f"  {src:14} n={d['n']:>3}  WR={wr:>3.0f}%  PnL ${pnl_sign}{d['pnl']:.1f}")
        lines.append("")

    # RH
    rh = _count_rh_signals_yesterday(yesterday)
    if rh["total"] > 0:
        lines.append(f"🎯 Range Hunter: {rh['total']} signals  "
                     f"({rh['placed']} placed, {rh['skipped']} skipped, "
                     f"{rh['pending']} pending)")

    # TB pauses — neutral wording. "тихий день" вводил в заблуждение:
    # 0 TB auto-pauses ≠ "ничего не происходило" (могли быть regime shifts /
    # action changes — для них см. DAILY REPORT, отдельная карточка).
    tb_pauses = _count_tb_pauses_yesterday(yesterday)
    lines.append(f"⏸ TB auto-pauses: {tb_pauses}")

    lines.append("")
    lines.append("Команды: /ab_status /twap_status /tv_status /bots")
    return "\n".join(lines)


def maybe_send_daily_digest(*, send_fn: Optional[Callable] = None,
                              now: Optional[datetime] = None) -> bool:
    if now is None:
        now = datetime.now(timezone.utc)
    if not (WINDOW_START_HOUR_UTC <= now.hour < WINDOW_END_HOUR_UTC):
        return False
    today_str = now.strftime("%Y-%m-%d")
    if _last_sent_date() == today_str:
        return False
    report = _build_report(now)
    if send_fn is None:
        logger.info("daily_digest.dry_run\n%s", report)
        _mark_sent(today_str)
        return True
    try:
        send_fn(report)
        _mark_sent(today_str)
        logger.info("daily_digest.sent date=%s", today_str)
        return True
    except Exception:
        logger.exception("daily_digest.send_failed")
        return False
