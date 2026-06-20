"""R3 escalation guard — persistent state for cap + cooldown.

Context: 2026-05-18 R3 (rule R3_vol_high_resize_UP) сработала 18 раз подряд за
~19ч, разогнав TB.maxQ ×288× от стартового (0.0009 → 0.259). Оператор ручками
ресетнул TB. Phase 3.6 R3 в исходном виде не имела ни cap, ни adequate
cooldown — bot_brain dedup ~60мин не помог при затяжном HIGH vol.

Этот модуль добавляет:
  - Hard cap: cumulative factor от baseline q.maxQ не должен превышать MAX_FACTOR (default 3.0).
  - Per-bot cooldown: COOLDOWN_SEC (default 4h) между успешными R3 fires.
  - Auto-rebaseline: если оператор вручную ресетнул q.maxQ к ≈baseline, state
    автоматически считает это новой стартовой точкой (current/baseline ≤ 1.1).

State в state/r3_state.json:
  {
    "bots": {
      "<bot_id>": {
        "baseline_maxQ": 0.003,
        "last_fired_ts": "2026-05-19T18:32:00+00:00",
        "fire_count": 1
      }
    }
  }
"""
from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "state" / "r3_state.json"
PARAMS_CSV = ROOT / "ginarea_live" / "params.csv"

MAX_FACTOR = 3.0
COOLDOWN_SEC = 14400  # 4h
APPLY_FACTOR = 1.5
REBASELINE_RATIO = 1.1  # current/baseline ≤ 1.1 → operator reset detected


def _load() -> dict:
    if not STATE_PATH.exists():
        return {"bots": {}}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"bots": {}}
        data.setdefault("bots", {})
        return data
    except (OSError, json.JSONDecodeError):
        logger.exception("r3_state.load_failed")
        return {"bots": {}}


def _save(state: dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        logger.exception("r3_state.save_failed")


def read_current_maxQ(bot_id: str, *, params_csv: Optional[Path] = None) -> Optional[float]:
    """Tail-read latest q.maxQ for bot_id from ginarea_live/params.csv."""
    csv_path = params_csv or PARAMS_CSV
    if not csv_path.exists():
        return None
    latest: Optional[float] = None
    latest_ts: str = ""
    try:
        with csv_path.open("r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            while True:
                try:
                    row = next(reader)
                except StopIteration:
                    break
                except csv.Error:
                    continue
                if row.get("bot_id") != str(bot_id):
                    continue
                raw = row.get("raw_params_json") or ""
                if not raw:
                    continue
                try:
                    p = json.loads(raw)
                    q = (p.get("q") or {})
                    val = q.get("maxQ")
                    if val is None:
                        continue
                    ts = row.get("ts_utc") or ""
                    if ts >= latest_ts:
                        latest_ts = ts
                        latest = float(val)
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue
    except OSError:
        logger.exception("r3_state.params_csv_read_failed")
        return None
    return latest


def r3_check_and_record(bot_id: str, now: Optional[datetime] = None, *,
                         current_maxQ: Optional[float] = None,
                         max_factor: float = MAX_FACTOR,
                         cooldown_sec: int = COOLDOWN_SEC,
                         apply_factor: float = APPLY_FACTOR,
                         state: Optional[dict] = None,
                         persist: bool = True) -> tuple[bool, str]:
    """Check if R3 can fire for bot_id; if allowed, record fire intent.

    Returns (allowed, reason). When allowed, last_fired_ts is updated and saved.

    state/current_maxQ params useful for testing — production callers leave both
    None to read from disk.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if current_maxQ is None:
        current_maxQ = read_current_maxQ(bot_id)
    if current_maxQ is None or current_maxQ <= 0:
        return False, "no_current_maxQ"

    if state is None:
        state = _load()
    bots = state.setdefault("bots", {})
    entry = bots.get(str(bot_id))

    if entry is None or entry.get("baseline_maxQ") in (None, 0):
        bots[str(bot_id)] = {
            "baseline_maxQ": current_maxQ,
            "last_fired_ts": None,
            "fire_count": 0,
        }
        if persist:
            _save(state)
        return True, f"baseline_captured maxQ={current_maxQ:g}"

    baseline = float(entry["baseline_maxQ"])
    if baseline <= 0:
        entry["baseline_maxQ"] = current_maxQ
        if persist:
            _save(state)
        return True, "baseline_re-captured"

    observed = current_maxQ / baseline
    if observed <= REBASELINE_RATIO:
        entry["baseline_maxQ"] = current_maxQ
        entry["last_fired_ts"] = None
        entry["fire_count"] = 0
        if persist:
            _save(state)
        return True, f"rebaseline_after_reset observed={observed:.2f}"

    projected = observed * apply_factor
    if projected > max_factor:
        return False, f"cap_blocked projected={projected:.2f}>cap={max_factor}"

    last_ts = entry.get("last_fired_ts")
    if last_ts:
        try:
            last = datetime.fromisoformat(last_ts)
            elapsed = (now - last).total_seconds()
            if elapsed < cooldown_sec:
                return False, f"cooldown_active elapsed={elapsed:.0f}s<{cooldown_sec}s"
        except ValueError:
            pass

    entry["last_fired_ts"] = now.isoformat(timespec="seconds")
    entry["fire_count"] = int(entry.get("fire_count") or 0) + 1
    if persist:
        _save(state)
    return True, f"allowed cum={observed:.2f}→{projected:.2f}"


def reset_for_bot(bot_id: str) -> bool:
    """Operator escape valve: drop R3 state for a bot. Next R3 evaluation will
    re-capture baseline from current params."""
    state = _load()
    if str(bot_id) in state.get("bots", {}):
        state["bots"].pop(str(bot_id))
        _save(state)
        return True
    return False
