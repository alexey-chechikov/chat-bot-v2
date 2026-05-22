"""Tests for pump_freeze state-driven resume logic — stall clock + re-freeze.

Covers freezer.py state machine: update_extreme stamps last_extreme_ts on
every new extreme; get_last_extreme_ts feeds the stall resume condition;
last_resume_info drives the price-based re-freeze gate (2026-05-22 design).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

import services.pump_freeze.freezer as fz


UTC = timezone.utc
T0 = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    """Redirect freezer STATE_PATH/JOURNAL_PATH to a temp dir per test."""
    sp = tmp_path / "pump_freeze_state.json"
    jp = tmp_path / "pump_freeze_events.jsonl"
    monkeypatch.setattr(fz, "STATE_PATH", sp)
    monkeypatch.setattr(fz, "JOURNAL_PATH", jp)
    return sp


def _seed_frozen(state_file, bot_id="777001", side="short", extreme=81000.0,
                 freeze_ts=T0):
    """Write a minimal frozen record directly into state."""
    state = {
        "frozen": {
            bot_id: {
                "freeze_ts": freeze_ts.isoformat(timespec="seconds"),
                "freeze_side": side,
                "freeze_direction": "up" if side == "short" else "down",
                "freeze_extreme_price": extreme,
                "extreme_during_freeze": extreme,
                "last_extreme_ts": freeze_ts.isoformat(timespec="seconds"),
                "freeze_position_usd": 30000.0,
                "freeze_position_raw": 0.4,
                "alert_id": "pf_test",
            }
        }
    }
    state_file.write_text(json.dumps(state), encoding="utf-8")


# ─── update_extreme — stall clock ───────────────────────────────────────────

def test_update_extreme_new_high_stamps_ts(state_file):
    _seed_frozen(state_file, side="short", extreme=81000.0)
    t1 = T0 + timedelta(minutes=20)
    fz.update_extreme("777001", 81500.0, "short", now=t1)
    assert fz.get_extreme_during_freeze("777001") == 81500.0
    assert fz.get_last_extreme_ts("777001") == t1


def test_update_extreme_no_new_high_keeps_ts(state_file):
    _seed_frozen(state_file, side="short", extreme=81000.0)
    t1 = T0 + timedelta(minutes=20)
    fz.update_extreme("777001", 80900.0, "short", now=t1)  # below hi — not new
    assert fz.get_extreme_during_freeze("777001") == 81000.0
    assert fz.get_last_extreme_ts("777001") == T0  # unchanged


def test_update_extreme_long_tracks_minimum(state_file):
    _seed_frozen(state_file, side="long", extreme=78400.0)
    t1 = T0 + timedelta(minutes=15)
    fz.update_extreme("777001", 78000.0, "long", now=t1)  # new low
    assert fz.get_extreme_during_freeze("777001") == 78000.0
    assert fz.get_last_extreme_ts("777001") == t1
    # a higher price is NOT a new extreme for long
    fz.update_extreme("777001", 78900.0, "long", now=t1 + timedelta(minutes=5))
    assert fz.get_extreme_during_freeze("777001") == 78000.0
    assert fz.get_last_extreme_ts("777001") == t1


def test_update_extreme_noop_when_not_frozen(state_file):
    state_file.write_text(json.dumps({"frozen": {}}), encoding="utf-8")
    fz.update_extreme("ghost", 99999.0, "short", now=T0)
    assert fz.get_last_extreme_ts("ghost") is None


def test_get_last_extreme_ts_falls_back_to_freeze_ts(state_file):
    """Record without last_extreme_ts → falls back to freeze_ts."""
    state = {"frozen": {"777001": {
        "freeze_ts": T0.isoformat(timespec="seconds"),
        "freeze_extreme_price": 81000.0,
    }}}
    state_file.write_text(json.dumps(state), encoding="utf-8")
    assert fz.get_last_extreme_ts("777001") == T0


def test_stall_clock_advances_then_resets(state_file):
    """Sequence: idle 30m, new hi resets clock, idle again."""
    _seed_frozen(state_file, side="short", extreme=81000.0)
    # 30 min of no new high — clock still at T0
    fz.update_extreme("777001", 80950.0, "short", now=T0 + timedelta(minutes=30))
    assert fz.get_last_extreme_ts("777001") == T0
    # new high at +35m — clock resets
    t_new = T0 + timedelta(minutes=35)
    fz.update_extreme("777001", 81200.0, "short", now=t_new)
    assert fz.get_last_extreme_ts("777001") == t_new


# ─── freeze / resume — last_resume_info & re-freeze gate ────────────────────

def _fake_api(_bot_id):
    return {"ok": True}


def test_resume_records_last_resume_info(state_file):
    _seed_frozen(state_file, bot_id="777001", side="short", extreme=81000.0)
    t_res = T0 + timedelta(minutes=40)
    ok = fz.resume(bot_id="777001", alias="T1", tier="T1", side="short",
                   current_price=80100.0, resume_reason="retracement -1.1%",
                   extreme_during_freeze=81000.0,
                   resume_api_fn=_fake_api, now=t_res)
    assert ok
    info = fz.last_resume_info("777001")
    assert info is not None
    assert info["resume_price"] == 80100.0
    assert not fz.is_frozen("777001")


def test_freeze_clears_last_resume_info(state_file):
    """After resume, a new freeze() consumes the re-freeze gate marker."""
    _seed_frozen(state_file, bot_id="777001", side="short", extreme=81000.0)
    fz.resume(bot_id="777001", alias="T1", tier="T1", side="short",
              current_price=80100.0, resume_reason="stall",
              extreme_during_freeze=81000.0,
              resume_api_fn=_fake_api, now=T0 + timedelta(minutes=40))
    assert fz.last_resume_info("777001") is not None

    class _Ev:
        direction = "up"; move_pct = 1.7
        price_now = 81200.0; price_window_start = 79800.0
    fz.freeze(bot_id="777001", alias="T1", tier="T1", side="short",
              event=_Ev(), raw_position=0.4, position_usd=32000.0,
              pause_api_fn=_fake_api, now=T0 + timedelta(minutes=90))
    assert fz.last_resume_info("777001") is None  # cleared
    assert fz.is_frozen("777001")


def test_freeze_sets_initial_last_extreme_ts(state_file):
    """freeze() stamps last_extreme_ts = freeze_ts (freeze is 1st extreme)."""
    state_file.write_text(json.dumps({"frozen": {}}), encoding="utf-8")

    class _Ev:
        direction = "up"; move_pct = 1.6
        price_now = 81000.0; price_window_start = 79700.0
    t_fz = T0 + timedelta(minutes=5)
    fz.freeze(bot_id="777001", alias="T1", tier="T1", side="short",
              event=_Ev(), raw_position=0.4, position_usd=30000.0,
              pause_api_fn=_fake_api, now=t_fz)
    assert fz.get_last_extreme_ts("777001") == t_fz


def test_last_resume_info_none_when_never_resumed(state_file):
    _seed_frozen(state_file, bot_id="777001")
    assert fz.last_resume_info("777001") is None
