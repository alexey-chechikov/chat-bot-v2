"""Cross-service dedup between cascade_alert and cascade_followup.

Single liq-cascade event used to trigger BOTH services with OPPOSITE
directions (cascade_alert sends MEGA continuation SHORT; cascade_followup
sends fade-LONG). Operator complaint 2026-05-25 day 3: this looks like
contradictory output, paralyses decisions.

Policy:
  - Both services call `mark_emitted(source, side, now)` after every
    successful TG send.
  - Before sending, each calls `recently_emitted(side, now)` — if any
    cascade alert was sent for that side within COOLDOWN_SEC, the new
    one is suppressed (logged, not emitted).
  - "side" is the LIQ side (long-cascade vs short-cascade) — both
    services use the same liq side as input even though their plays
    point opposite directions.

First wins. Race conditions are fine — at our 30-60s tick cadence two
emitters won't race within sub-second.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "state" / "cascade_cross_dedup.json"

# 10 min window — operator confusion lasts that long; outside that any
# follow-up is genuinely a separate event.
COOLDOWN_SEC = 600


def _read() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write(state: dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(STATE_PATH)
    except OSError:
        logger.exception("cascade_cross_dedup.write_failed")


def mark_emitted(source: str, side: str, now: datetime | None = None) -> None:
    """Record that `source` (cascade_alert | cascade_followup) emitted a card
    for liq `side` at `now`."""
    if now is None:
        now = datetime.now(timezone.utc)
    state = _read()
    state[side] = {
        "source": source,
        "ts": now.isoformat(timespec="seconds"),
    }
    _write(state)


def recently_emitted(side: str, now: datetime | None = None,
                      cooldown_sec: int = COOLDOWN_SEC) -> tuple[bool, str]:
    """Returns (yes, source) — True + last-emitter name iff any cascade
    alert was sent for `side` within cooldown."""
    if now is None:
        now = datetime.now(timezone.utc)
    state = _read()
    entry = state.get(side)
    if not entry:
        return False, ""
    try:
        ts = datetime.fromisoformat(entry["ts"].replace("Z", "+00:00"))
    except (KeyError, ValueError, TypeError):
        return False, ""
    if (now - ts).total_seconds() >= cooldown_sec:
        return False, ""
    return True, str(entry.get("source", "?"))
