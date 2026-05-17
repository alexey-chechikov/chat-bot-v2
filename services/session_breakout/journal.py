"""Session Breakout journal — state/session_breakout_signals.jsonl.

Per record:
{
  "signal_id":         "sb_20260518_080500_long",
  "ts_signal":         "2026-05-18T08:05:00+00:00",
  "transition":        "asia_to_london",
  "side":              "long",
  "entry":             80000.0,
  "stop":              79520.0,
  "tp":                80720.0,
  "prior_high":        79980.0,
  "prior_low":         79100.0,
  "breakout_level":    79980.0,
  "size_usd":          1000.0,
  "contract":          "XBTUSDT",
  "hold_h":            3,

  // User decision
  "user_action":       null,        # "placed" | "skipped"
  "placed_at":         null,
  "decision_latency_sec": null,

  // Outcome (filled by outcome_tracker)
  "exit_ts":           null,
  "exit_reason":       null,        # "tp_hit" | "sl_hit" | "timeout" | "user_skip"
  "exit_price":        null,
  "pnl_usd":           null
}
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

JOURNAL_PATH = Path("state/session_breakout_signals.jsonl")


def signal_id_from_ts(ts: datetime, side: str) -> str:
    return f"sb_{ts.strftime('%Y%m%d_%H%M%S')}_{side}"


def append_signal(record: dict, *, path: Path = JOURNAL_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("session_breakout.journal.append_failed")


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
        logger.exception("session_breakout.journal.write_failed")


def update_record(signal_id: str, updates: dict, *,
                  path: Path = JOURNAL_PATH) -> bool:
    rows = read_all(path=path)
    found = False
    for r in rows:
        if r.get("signal_id") == signal_id:
            r.update(updates)
            found = True
            break
    if found:
        write_all(rows, path=path)
    return found


def mark_user_action(signal_id: str, action: str, *,
                     now: Optional[datetime] = None,
                     path: Path = JOURNAL_PATH) -> bool:
    """Mark inline button press. action: 'placed' | 'skipped'."""
    if now is None:
        now = datetime.now(timezone.utc)
    rows = read_all(path=path)
    for r in rows:
        if r.get("signal_id") != signal_id:
            continue
        r["user_action"] = action
        if action == "placed":
            r["placed_at"] = now.isoformat(timespec="seconds")
            try:
                ts_sig = datetime.fromisoformat(r["ts_signal"])
                r["decision_latency_sec"] = round((now - ts_sig).total_seconds(), 1)
            except (KeyError, ValueError):
                pass
        elif action == "skipped":
            r["exit_reason"] = "user_skip"
        write_all(rows, path=path)
        return True
    return False


def boundary_already_fired(transition: str, day_iso: str, *,
                            path: Path = JOURNAL_PATH) -> bool:
    """Dedup: was a signal already emitted for this (transition, day) pair?"""
    rows = read_all(path=path)
    for r in rows:
        if r.get("transition") != transition:
            continue
        ts = r.get("ts_signal", "")
        if ts.startswith(day_iso):
            return True
    return False


def pending_signals(*, path: Path = JOURNAL_PATH) -> list[dict]:
    rows = read_all(path=path)
    return [r for r in rows
            if r.get("user_action") == "placed" and r.get("exit_reason") is None]


def summarize(*, path: Path = JOURNAL_PATH) -> dict:
    rows = read_all(path=path)
    if not rows:
        return {"total": 0}
    placed = [r for r in rows if r.get("user_action") == "placed"]
    skipped = [r for r in rows if r.get("user_action") == "skipped"]
    pending = [r for r in rows if r.get("user_action") is None]
    closed = [r for r in placed if r.get("exit_reason") is not None]
    wins = [r for r in closed if r.get("exit_reason") == "tp_hit"]
    pnls = [float(r.get("pnl_usd") or 0) for r in closed]
    by_outcome: dict[str, int] = {}
    for r in closed:
        by_outcome[r.get("exit_reason", "unknown")] = \
            by_outcome.get(r.get("exit_reason", "unknown"), 0) + 1
    return {
        "total": len(rows),
        "pending_decision": len(pending),
        "placed": len(placed),
        "skipped": len(skipped),
        "closed": len(closed),
        "win_rate_pct": round(100 * len(wins) / len(closed), 1) if closed else 0.0,
        "by_outcome": by_outcome,
        "total_pnl_usd": round(sum(pnls), 2),
    }
