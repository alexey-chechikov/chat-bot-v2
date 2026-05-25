"""Tests for cross_service_dedup between cascade_alert and cascade_followup."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.cascade_alert import cross_service_dedup as csd


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """Redirect STATE_PATH so tests don't touch the real shared file."""
    monkeypatch.setattr(csd, "STATE_PATH", tmp_path / "cross.json")


def test_no_history_means_not_recently_emitted() -> None:
    now = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    blocked, who = csd.recently_emitted("long", now)
    assert not blocked
    assert who == ""


def test_mark_then_recently_emitted_within_cooldown() -> None:
    t0 = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    csd.mark_emitted("cascade_alert_mega", "short", t0)
    blocked, who = csd.recently_emitted("short", t0 + timedelta(seconds=120))
    assert blocked
    assert who == "cascade_alert_mega"


def test_outside_cooldown_no_block() -> None:
    t0 = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    csd.mark_emitted("cascade_followup", "short", t0)
    # default cooldown 600s; 700s later — should not block
    blocked, _ = csd.recently_emitted("short", t0 + timedelta(seconds=700))
    assert not blocked


def test_different_sides_are_independent() -> None:
    t0 = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    csd.mark_emitted("cascade_alert_mega", "long", t0)
    blocked, _ = csd.recently_emitted("short", t0 + timedelta(seconds=60))
    assert not blocked
    blocked2, _ = csd.recently_emitted("long", t0 + timedelta(seconds=60))
    assert blocked2


def test_custom_cooldown_argument() -> None:
    t0 = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    csd.mark_emitted("cascade_followup", "short", t0)
    # custom 30s cooldown — already expired
    blocked, _ = csd.recently_emitted("short", t0 + timedelta(seconds=45),
                                       cooldown_sec=30)
    assert not blocked


def test_mark_overwrites_previous_for_same_side() -> None:
    t0 = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    csd.mark_emitted("cascade_alert", "long", t0)
    t1 = t0 + timedelta(seconds=200)
    csd.mark_emitted("cascade_followup", "long", t1)
    blocked, who = csd.recently_emitted("long", t1 + timedelta(seconds=30))
    assert blocked
    assert who == "cascade_followup"
