"""TWAP defender journal — state/twap_defender_alerts.jsonl.

Каждый alert представляет ОДИН шаг TWAP (5 мин окно). Серия шагов
объединена общим series_id и инкрементальным step (1..MAX_STEPS).

Record schema:
{
  "alert_id":         "td_20260517_120000_4729923198",  # unique per emit
  "series_id":        "td_series_4729923198_20260517_110000",  # group key
  "step":             3,                              # 1..MAX_STEPS
  "ts_alert":         "2026-05-17T12:00:00+00:00",
  "bot_id":           "4729923198",
  "alias":            "SHORT-T1",
  "tier":             "T1",
  "side":             "short",
  "position_btc":     -0.620,
  "position_usd_abs": 49600,
  "delta_30min_usd":  +4500,                          # rost za 30 min (always > 0 для alert)
  "btc_mid":          80000,
  "suggested_qty_usd": 1000,                          # фиксированный шаг
  "suggested_side":   "buy",                          # против direction накопления

  # User decision
  "user_action":      null,    # "executed" | "skipped" | "muted" | null
  "user_action_ts":   null,
  "muted_until":      null
}
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

JOURNAL_PATH = Path("state/twap_defender_alerts.jsonl")
SERIES_GAP_MIN = 30      # gap > N min между алертами стартует новую серию
STEP_INTERVAL_MIN = 5    # минимальный gap между последовательными TWAP-шагами
MAX_STEPS = 12           # после стольких шагов в серии — auto-stop


def append_alert(record: dict, *, path: Path = JOURNAL_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("twap_defender.journal.append_failed")


def read_all(*, path: Path = JOURNAL_PATH) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return out
    return out


def write_all(rows: list[dict], *, path: Path = JOURNAL_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("twap_defender.journal.write_failed")


def latest_alert_for_bot(bot_id: str, *, path: Path = JOURNAL_PATH) -> Optional[dict]:
    rows = read_all(path=path)
    for r in reversed(rows):
        if r.get("bot_id") == bot_id:
            return r
    return None


def active_series_for_bot(bot_id: str, *, now: datetime,
                          path: Path = JOURNAL_PATH) -> tuple[Optional[str], int]:
    """Return (series_id, last_step) for current active series of this bot.

    Active = latest alert < SERIES_GAP_MIN ago AND step < MAX_STEPS AND not muted.
    Otherwise returns (None, 0) — caller should start a new series.
    """
    latest = latest_alert_for_bot(bot_id, path=path)
    if not latest:
        return (None, 0)
    try:
        last_ts = datetime.fromisoformat(latest["ts_alert"])
    except (KeyError, ValueError):
        return (None, 0)
    age_min = (now - last_ts).total_seconds() / 60.0
    if age_min > SERIES_GAP_MIN:
        return (None, 0)
    if latest.get("step", 0) >= MAX_STEPS:
        return (None, 0)
    muted_until = latest.get("muted_until")
    if muted_until:
        try:
            mu = datetime.fromisoformat(muted_until)
            if now < mu:
                return (None, 0)
        except ValueError:
            pass
    return (latest.get("series_id"), int(latest.get("step", 0)))


def mark_user_action(alert_id: str, action: str, *,
                     now: Optional[datetime] = None,
                     mute_minutes: int = 60,
                     path: Path = JOURNAL_PATH) -> bool:
    """Marks user's button press. Returns True if alert found.

    action: "executed" | "skipped" | "muted"
    """
    if now is None:
        now = datetime.now(timezone.utc)
    rows = read_all(path=path)
    found = False
    for r in rows:
        if r.get("alert_id") != alert_id:
            continue
        r["user_action"] = action
        r["user_action_ts"] = now.isoformat(timespec="seconds")
        if action == "muted":
            from datetime import timedelta
            r["muted_until"] = (now + timedelta(minutes=mute_minutes)).isoformat(timespec="seconds")
        found = True
        break
    if found:
        write_all(rows, path=path)
    return found


def summarize(*, path: Path = JOURNAL_PATH) -> dict:
    rows = read_all(path=path)
    if not rows:
        return {"total": 0}
    executed = sum(1 for r in rows if r.get("user_action") == "executed")
    skipped = sum(1 for r in rows if r.get("user_action") == "skipped")
    muted = sum(1 for r in rows if r.get("user_action") == "muted")
    pending = sum(1 for r in rows if r.get("user_action") is None)
    total_exec_usd = sum(float(r.get("suggested_qty_usd", 0))
                          for r in rows if r.get("user_action") == "executed")
    return {
        "total": len(rows),
        "executed": executed,
        "skipped": skipped,
        "muted": muted,
        "pending": pending,
        "estimated_volume_added_usd": round(total_exec_usd, 2),
    }
