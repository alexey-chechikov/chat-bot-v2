"""Tests for r3_state cap + cooldown + auto-rebaseline guard."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import services.bot_brain.r3_state as r3
from services.bot_brain.r3_state import (
    MAX_FACTOR,
    APPLY_FACTOR,
    COOLDOWN_SEC,
    r3_check_and_record,
    reset_for_bot,
)


def _state_with(baseline: float, last_fired_ts: str | None = None,
                fire_count: int = 0) -> dict:
    return {"bots": {"42": {
        "baseline_maxQ": baseline,
        "last_fired_ts": last_fired_ts,
        "fire_count": fire_count,
    }}}


def test_first_call_captures_baseline(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(r3, "STATE_PATH", tmp_path / "r3.json")
    now = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)
    allowed, reason = r3_check_and_record("42", now=now, current_maxQ=0.003)
    assert allowed
    assert "baseline_captured" in reason
    saved = (tmp_path / "r3.json").read_text()
    assert "0.003" in saved


def test_cap_blocks_runaway(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(r3, "STATE_PATH", tmp_path / "r3.json")
    now = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)
    state = _state_with(baseline=0.003, last_fired_ts=None)
    # current at 0.0066 → observed=2.2, projected=2.2*1.5=3.3 > cap 3.0
    allowed, reason = r3_check_and_record("42", now=now, current_maxQ=0.0066,
                                            state=state, persist=False)
    assert not allowed
    assert "cap_blocked" in reason


def test_cap_allows_just_below(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(r3, "STATE_PATH", tmp_path / "r3.json")
    now = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)
    state = _state_with(baseline=0.003, last_fired_ts=None)
    # current 0.0058: observed≈1.93, projected≈2.9 → under cap
    allowed, reason = r3_check_and_record("42", now=now, current_maxQ=0.0058,
                                            state=state, persist=False)
    assert allowed
    assert "allowed" in reason


def test_cooldown_blocks_recent_fire(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(r3, "STATE_PATH", tmp_path / "r3.json")
    fired_ts = "2026-05-19T11:00:00+00:00"
    now = datetime.fromisoformat(fired_ts) + timedelta(hours=2)  # 2h after fire
    state = _state_with(baseline=0.003, last_fired_ts=fired_ts)
    allowed, reason = r3_check_and_record("42", now=now, current_maxQ=0.0035,
                                            state=state, persist=False)
    assert not allowed
    assert "cooldown_active" in reason


def test_cooldown_expires_after_4h(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(r3, "STATE_PATH", tmp_path / "r3.json")
    fired_ts = "2026-05-19T08:00:00+00:00"
    now = datetime.fromisoformat(fired_ts) + timedelta(hours=4, seconds=1)
    state = _state_with(baseline=0.003, last_fired_ts=fired_ts)
    allowed, reason = r3_check_and_record("42", now=now, current_maxQ=0.0035,
                                            state=state, persist=False)
    assert allowed


def test_auto_rebaseline_after_manual_reset(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(r3, "STATE_PATH", tmp_path / "r3.json")
    # Bot was at 0.005 (cumulative 1.66 of baseline 0.003).
    # Operator reset to 0.003 → ratio 1.0 ≤ 1.1 → rebaseline expected.
    now = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)
    state = _state_with(baseline=0.003, last_fired_ts="2026-05-19T10:00:00+00:00",
                         fire_count=5)
    allowed, reason = r3_check_and_record("42", now=now, current_maxQ=0.003,
                                            state=state, persist=False)
    assert allowed
    assert "rebaseline" in reason
    assert state["bots"]["42"]["fire_count"] == 0
    assert state["bots"]["42"]["last_fired_ts"] is None


def test_no_current_maxQ_blocks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(r3, "STATE_PATH", tmp_path / "r3.json")
    monkeypatch.setattr(r3, "PARAMS_CSV", tmp_path / "missing.csv")
    now = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)
    allowed, reason = r3_check_and_record("42", now=now)
    assert not allowed
    assert "no_current_maxQ" in reason


def test_simulated_escalation_caps_at_3x(tmp_path: Path, monkeypatch) -> None:
    """Simulate repeated R3 fires + actions._act_resize × 1.5 each → cap kicks in."""
    monkeypatch.setattr(r3, "STATE_PATH", tmp_path / "r3.json")
    now = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)
    current_maxQ = 0.003
    fires = 0
    blocked_at = None
    for i in range(20):
        tick = now + timedelta(hours=i * 5)  # past cooldown each iteration
        allowed, reason = r3_check_and_record("42", now=tick, current_maxQ=current_maxQ)
        if allowed:
            fires += 1
            # simulate _act_resize × 1.5
            current_maxQ *= APPLY_FACTOR
        else:
            blocked_at = i
            assert "cap_blocked" in reason
            break
    assert blocked_at is not None, "must block before 20 iterations"
    # Cumulative factor at block point — actual multiplier
    cumulative = current_maxQ / 0.003
    assert cumulative <= MAX_FACTOR, f"cumulative {cumulative} should be ≤ cap {MAX_FACTOR}"
    # Without cap we'd hit 1.5^20 ≈ 3325× — guard truncated to ≤3.0
    assert fires < 5, f"with cap=3.0 and apply=1.5, only ~2-3 fires expected, got {fires}"


def test_reset_for_bot_clears(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(r3, "STATE_PATH", tmp_path / "r3.json")
    now = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)
    r3_check_and_record("42", now=now, current_maxQ=0.003)
    assert (tmp_path / "r3.json").exists()
    assert reset_for_bot("42") is True
    state = r3._load()
    assert "42" not in state.get("bots", {})


def test_read_current_maxQ_from_params_csv(tmp_path: Path, monkeypatch) -> None:
    csv_path = tmp_path / "params.csv"
    csv_path.write_text(
        "ts_utc,bot_id,raw_params_json\n"
        '2026-05-18T10:00:00+00:00,42,"{""q"": {""maxQ"": 0.003, ""minQ"": 0.001}}"\n'
        '2026-05-19T10:00:00+00:00,42,"{""q"": {""maxQ"": 0.0066, ""minQ"": 0.0033}}"\n'
        '2026-05-19T10:00:00+00:00,99,"{""q"": {""maxQ"": 0.999}}"\n',
        encoding="utf-8",
    )
    val = r3.read_current_maxQ("42", params_csv=csv_path)
    assert val == 0.0066
    val_other = r3.read_current_maxQ("99", params_csv=csv_path)
    assert val_other == 0.999
    val_missing = r3.read_current_maxQ("11", params_csv=csv_path)
    assert val_missing is None
