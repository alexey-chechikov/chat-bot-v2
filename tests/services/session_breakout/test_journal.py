"""Tests for session_breakout.journal — dedup + user actions + outcomes."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from services.session_breakout.journal import (
    append_signal,
    boundary_already_fired,
    mark_user_action,
    pending_signals,
    read_all,
    summarize,
    update_record,
)


def _record(signal_id="sb_test_1", transition="asia_to_london", side="long",
            ts_signal="2026-05-18T08:05:00+00:00", user_action=None,
            exit_reason=None):
    return {
        "signal_id": signal_id,
        "ts_signal": ts_signal,
        "transition": transition,
        "side": side,
        "new_session": "london",
        "prior_session": "asia",
        "time_in_session_min": 5,
        "mid": 80000.0,
        "entry": 80000.0,
        "stop": 79520.0,
        "tp": 80720.0,
        "prior_high": 79980.0,
        "prior_low": 79100.0,
        "breakout_level": 79980.0,
        "size_usd": 1000.0,
        "contract": "XBTUSDT",
        "hold_h": 3,
        "user_action": user_action,
        "placed_at": None,
        "decision_latency_sec": None,
        "exit_ts": None,
        "exit_reason": exit_reason,
        "exit_price": None,
        "pnl_usd": None,
    }


def test_append_and_read(tmp_path: Path):
    p = tmp_path / "sb.jsonl"
    append_signal(_record(), path=p)
    rows = read_all(path=p)
    assert len(rows) == 1
    assert rows[0]["signal_id"] == "sb_test_1"


def test_boundary_dedup_same_day(tmp_path: Path):
    p = tmp_path / "sb.jsonl"
    append_signal(_record(signal_id="sb_1",
                          ts_signal="2026-05-18T08:05:00+00:00"), path=p)
    assert boundary_already_fired("asia_to_london", "2026-05-18", path=p) is True
    assert boundary_already_fired("asia_to_london", "2026-05-19", path=p) is False
    assert boundary_already_fired("london_to_ny_am", "2026-05-18", path=p) is False


def test_mark_user_action_placed_sets_latency(tmp_path: Path):
    p = tmp_path / "sb.jsonl"
    append_signal(_record(), path=p)
    now = datetime(2026, 5, 18, 8, 7, 0, tzinfo=timezone.utc)
    ok = mark_user_action("sb_test_1", "placed", now=now, path=p)
    assert ok
    rows = read_all(path=p)
    r = rows[0]
    assert r["user_action"] == "placed"
    assert r["placed_at"] is not None
    assert r["decision_latency_sec"] == 120.0  # 2 min after signal


def test_mark_user_action_skipped_sets_exit_reason(tmp_path: Path):
    p = tmp_path / "sb.jsonl"
    append_signal(_record(), path=p)
    mark_user_action("sb_test_1", "skipped", path=p)
    rows = read_all(path=p)
    assert rows[0]["exit_reason"] == "user_skip"


def test_update_record(tmp_path: Path):
    p = tmp_path / "sb.jsonl"
    append_signal(_record(), path=p)
    ok = update_record("sb_test_1", {"pnl_usd": 12.5, "exit_reason": "tp_hit"}, path=p)
    assert ok
    rows = read_all(path=p)
    assert rows[0]["pnl_usd"] == 12.5
    assert rows[0]["exit_reason"] == "tp_hit"


def test_pending_signals_only_placed_no_exit(tmp_path: Path):
    p = tmp_path / "sb.jsonl"
    append_signal(_record(signal_id="a", user_action="placed"), path=p)
    append_signal(_record(signal_id="b", user_action="skipped"), path=p)
    append_signal(_record(signal_id="c", user_action="placed",
                          exit_reason="tp_hit"), path=p)
    append_signal(_record(signal_id="d"), path=p)  # no decision yet
    pend = pending_signals(path=p)
    assert len(pend) == 1
    assert pend[0]["signal_id"] == "a"


def test_summarize_counts(tmp_path: Path):
    p = tmp_path / "sb.jsonl"
    rows = [
        _record(signal_id="a", user_action="placed", exit_reason="tp_hit"),
        _record(signal_id="b", user_action="placed", exit_reason="sl_hit"),
        _record(signal_id="c", user_action="skipped"),
        _record(signal_id="d"),
    ]
    for r in rows:
        append_signal(r, path=p)
    # add pnl to closed ones
    update_record("a", {"pnl_usd": 12.0}, path=p)
    update_record("b", {"pnl_usd": -8.0}, path=p)
    s = summarize(path=p)
    assert s["total"] == 4
    assert s["placed"] == 2
    assert s["skipped"] == 1
    assert s["closed"] == 2
    assert s["win_rate_pct"] == 50.0
    assert s["total_pnl_usd"] == 4.0
