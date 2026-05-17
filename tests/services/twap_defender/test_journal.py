"""Tests for twap_defender.journal — series tracking + user actions."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.twap_defender.journal import (
    MAX_STEPS,
    SERIES_GAP_MIN,
    STEP_INTERVAL_MIN,
    active_series_for_bot,
    append_alert,
    latest_alert_for_bot,
    mark_user_action,
    summarize,
)


def test_step_interval_constant():
    assert STEP_INTERVAL_MIN == 5


def _alert(bot_id="123", step=1, ts=None, series="series-A",
           user_action=None, muted_until=None, qty=1000):
    if ts is None:
        ts = datetime.now(timezone.utc)
    return {
        "alert_id": f"td_{ts.strftime('%Y%m%d_%H%M%S')}_{bot_id}",
        "series_id": series,
        "step": step,
        "ts_alert": ts.isoformat(timespec="seconds"),
        "bot_id": bot_id,
        "alias": "T1",
        "tier": "T1",
        "side": "short",
        "position_btc": -0.7,
        "position_usd_abs": 56000,
        "delta_30min_usd": 5000,
        "btc_mid": 80000,
        "suggested_qty_usd": qty,
        "suggested_side": "buy",
        "user_action": user_action,
        "user_action_ts": None,
        "muted_until": muted_until,
    }


def test_first_alert_starts_new_series(tmp_path: Path):
    p = tmp_path / "j.jsonl"
    now = datetime.now(timezone.utc)
    sid, step = active_series_for_bot("123", now=now, path=p)
    assert sid is None and step == 0


def test_recent_alert_continues_series(tmp_path: Path):
    p = tmp_path / "j.jsonl"
    now = datetime.now(timezone.utc)
    append_alert(_alert(ts=now - timedelta(minutes=10), step=2, series="abc"), path=p)
    sid, step = active_series_for_bot("123", now=now, path=p)
    assert sid == "abc" and step == 2


def test_old_alert_starts_new_series(tmp_path: Path):
    p = tmp_path / "j.jsonl"
    now = datetime.now(timezone.utc)
    append_alert(_alert(ts=now - timedelta(minutes=SERIES_GAP_MIN + 5),
                         step=1, series="old"), path=p)
    sid, step = active_series_for_bot("123", now=now, path=p)
    assert sid is None and step == 0


def test_max_steps_blocks_series(tmp_path: Path):
    p = tmp_path / "j.jsonl"
    now = datetime.now(timezone.utc)
    append_alert(_alert(ts=now - timedelta(minutes=5), step=MAX_STEPS,
                         series="full"), path=p)
    sid, step = active_series_for_bot("123", now=now, path=p)
    assert sid is None  # MAX reached


def test_muted_blocks_series(tmp_path: Path):
    p = tmp_path / "j.jsonl"
    now = datetime.now(timezone.utc)
    muted = (now + timedelta(minutes=30)).isoformat(timespec="seconds")
    append_alert(_alert(ts=now - timedelta(minutes=10), step=3,
                         series="muted", muted_until=muted), path=p)
    sid, _ = active_series_for_bot("123", now=now, path=p)
    assert sid is None


def test_mute_expired_continues_series(tmp_path: Path):
    p = tmp_path / "j.jsonl"
    now = datetime.now(timezone.utc)
    muted = (now - timedelta(minutes=1)).isoformat(timespec="seconds")  # past
    append_alert(_alert(ts=now - timedelta(minutes=10), step=3,
                         series="exmute", muted_until=muted), path=p)
    sid, step = active_series_for_bot("123", now=now, path=p)
    assert sid == "exmute" and step == 3


def test_mark_user_action_executed(tmp_path: Path):
    p = tmp_path / "j.jsonl"
    a = _alert()
    append_alert(a, path=p)
    ok = mark_user_action(a["alert_id"], "executed", path=p)
    assert ok
    latest = latest_alert_for_bot("123", path=p)
    assert latest["user_action"] == "executed"
    assert latest["user_action_ts"] is not None


def test_mark_user_action_muted_sets_until(tmp_path: Path):
    p = tmp_path / "j.jsonl"
    a = _alert()
    append_alert(a, path=p)
    now = datetime.now(timezone.utc)
    ok = mark_user_action(a["alert_id"], "muted", now=now, mute_minutes=60, path=p)
    assert ok
    latest = latest_alert_for_bot("123", path=p)
    assert latest["muted_until"] is not None
    mu = datetime.fromisoformat(latest["muted_until"])
    assert (mu - now).total_seconds() > 3500  # ~60 min


def test_summarize_counts(tmp_path: Path):
    p = tmp_path / "j.jsonl"
    append_alert(_alert(bot_id="A", user_action="executed", qty=1000), path=p)
    append_alert(_alert(bot_id="B", user_action="executed", qty=1000), path=p)
    append_alert(_alert(bot_id="C", user_action="skipped"), path=p)
    append_alert(_alert(bot_id="D"), path=p)  # pending
    s = summarize(path=p)
    assert s["total"] == 4
    assert s["executed"] == 2
    assert s["skipped"] == 1
    assert s["pending"] == 1
    assert s["estimated_volume_added_usd"] == 2000.0
