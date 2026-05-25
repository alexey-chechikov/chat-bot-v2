"""STALE DATA debounce + self-recovery suppression tests.

Bug 2026-05-25 (teammate day 3): stale sources self-recovered within 1-2
min, but monitor sent STALE → RECOVERED pair, polluting TG. Fix:
debounce — don't alert until source has been stale for 5+ min.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from services.stale_monitor import monitor


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Redirect STATE_PATH and CRITICAL_SOURCES into tmp_path."""
    state_path = tmp_path / "stale_state.json"
    monkeypatch.setattr(monitor, "STATE_PATH", state_path)
    # Use a single fake source pointing at a file we control.
    fake_source = tmp_path / "fake_feed.csv"
    monkeypatch.setattr(monitor, "CRITICAL_SOURCES", {
        "fake": {
            "path": str(fake_source),
            "max_age_min": 5,
            "label": "Fake stream",
        },
    })
    return {"state_path": state_path, "feed": fake_source}


def _touch_with_age(path: Path, age_min: float) -> None:
    path.write_text("data", encoding="utf-8")
    target = time.time() - age_min * 60
    import os
    os.utime(path, (target, target))


def test_fresh_source_no_alert(_isolate):
    _touch_with_age(_isolate["feed"], age_min=1)
    sends: list[str] = []
    monitor.check_once(send_fn=sends.append)
    assert sends == []


def test_stale_within_debounce_does_not_alert(_isolate, monkeypatch):
    """Source becomes stale but the first check_once should NOT alert."""
    _touch_with_age(_isolate["feed"], age_min=6)  # >5min threshold, stale
    monkeypatch.setattr(monitor, "ALERT_DEBOUNCE_SEC", 300)
    sends: list[str] = []
    monitor.check_once(send_fn=sends.append)
    assert sends == []  # first detection — no alert yet
    state = json.loads(_isolate["state_path"].read_text())
    assert state["fake"]["stale"] is True
    assert state["fake"]["alerted"] is False


def test_self_recovery_within_debounce_no_alert(_isolate, monkeypatch):
    """If source recovers before debounce elapses, neither STALE nor RECOVERED is sent."""
    monkeypatch.setattr(monitor, "ALERT_DEBOUNCE_SEC", 300)
    _touch_with_age(_isolate["feed"], age_min=6)
    sends: list[str] = []
    monitor.check_once(send_fn=sends.append)  # mark stale, no alert
    _touch_with_age(_isolate["feed"], age_min=0.1)  # came back fresh
    monitor.check_once(send_fn=sends.append)
    assert sends == []  # silent both ways


def test_stale_persists_past_debounce_emits_alert(_isolate, monkeypatch):
    """If stale lasts > debounce, the next check_once alerts."""
    monkeypatch.setattr(monitor, "ALERT_DEBOUNCE_SEC", 1)  # 1s debounce for test
    _touch_with_age(_isolate["feed"], age_min=6)
    sends: list[str] = []
    monitor.check_once(send_fn=sends.append)  # first hit — mark, no alert
    time.sleep(1.5)  # exceed debounce
    monitor.check_once(send_fn=sends.append)
    assert len(sends) == 1
    assert "STALE DATA" in sends[0]


def test_recovery_after_real_alert_does_emit_recovered(_isolate, monkeypatch):
    """When operator was alerted, send the RECOVERED card on recovery."""
    monkeypatch.setattr(monitor, "ALERT_DEBOUNCE_SEC", 1)
    _touch_with_age(_isolate["feed"], age_min=6)
    sends: list[str] = []
    monitor.check_once(send_fn=sends.append)  # mark
    time.sleep(1.5)
    monitor.check_once(send_fn=sends.append)  # alert
    _touch_with_age(_isolate["feed"], age_min=0.1)
    monitor.check_once(send_fn=sends.append)  # recovery
    assert any("STALE DATA" in m for m in sends)
    assert any("RECOVERED" in m for m in sends)
