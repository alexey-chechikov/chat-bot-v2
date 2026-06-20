"""Tests for LEVEL_BREAK source-based filtering in SignalAlertWorker._should_send.

Operator feedback 2026-05-19: 13-час swing low broken by $30 = noise, не actionable
(меньше BitMEX fees). Round numbers + bot borders — actionable. Swing-only —
suppress по умолчанию.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from services.telegram_runtime import SignalAlertWorker


def _row(signal_type: str, **details) -> dict:
    return {
        "signal_type": signal_type,
        "details_json": json.dumps(details),
    }


def _worker(monkeypatch) -> SignalAlertWorker:
    """Build a worker bypassing __init__ heavy dependencies."""
    w = SignalAlertWorker.__new__(SignalAlertWorker)
    w._cooldowns = {"LEVEL_BREAK": 3600}
    w._last_sent = {}
    w._spam_enabled = True
    w._log_deduped = False
    w._dedup_state_path = monkeypatch  # not actually written in this test
    return w


def test_swing_only_level_break_suppressed(monkeypatch) -> None:
    monkeypatch.delenv("LEVEL_BREAK_FORWARD_SWINGS", raising=False)
    monkeypatch.delenv("TELEGRAM_REGULATION_FILTER_ENABLED", raising=False)
    w = _worker(monkeypatch)
    row = _row("LEVEL_BREAK", level=76433.0, direction="down", price=76403.6,
                source="swing")
    assert w._should_send(row) is False


def test_round_number_level_break_forwarded(monkeypatch) -> None:
    monkeypatch.delenv("LEVEL_BREAK_FORWARD_SWINGS", raising=False)
    monkeypatch.delenv("TELEGRAM_REGULATION_FILTER_ENABLED", raising=False)
    w = _worker(monkeypatch)
    row = _row("LEVEL_BREAK", level=77000.0, direction="up", price=77010.0,
                source="round")
    assert w._should_send(row) is True


def test_bot_border_level_break_forwarded(monkeypatch) -> None:
    monkeypatch.delenv("LEVEL_BREAK_FORWARD_SWINGS", raising=False)
    monkeypatch.delenv("TELEGRAM_REGULATION_FILTER_ENABLED", raising=False)
    w = _worker(monkeypatch)
    row = _row("LEVEL_BREAK", level=85000.0, direction="down", price=84990.0,
                source="border")
    assert w._should_send(row) is True


def test_mixed_source_level_break_forwarded(monkeypatch) -> None:
    """Round + swing overlap (e.g. $76000 happens to also be a swing low) — forward."""
    monkeypatch.delenv("LEVEL_BREAK_FORWARD_SWINGS", raising=False)
    monkeypatch.delenv("TELEGRAM_REGULATION_FILTER_ENABLED", raising=False)
    w = _worker(monkeypatch)
    row = _row("LEVEL_BREAK", level=76000.0, direction="down", price=75990.0,
                source="round,swing")
    assert w._should_send(row) is True


def test_env_override_forwards_swings(monkeypatch) -> None:
    """LEVEL_BREAK_FORWARD_SWINGS=1 возвращает старое поведение."""
    monkeypatch.setenv("LEVEL_BREAK_FORWARD_SWINGS", "1")
    monkeypatch.delenv("TELEGRAM_REGULATION_FILTER_ENABLED", raising=False)
    w = _worker(monkeypatch)
    row = _row("LEVEL_BREAK", level=76433.0, direction="down", price=76403.6,
                source="swing")
    assert w._should_send(row) is True


def test_missing_source_field_forwarded(monkeypatch) -> None:
    """Backwards compat: если source отсутствует в payload (старые записи) — forward."""
    monkeypatch.delenv("LEVEL_BREAK_FORWARD_SWINGS", raising=False)
    monkeypatch.delenv("TELEGRAM_REGULATION_FILTER_ENABLED", raising=False)
    w = _worker(monkeypatch)
    row = _row("LEVEL_BREAK", level=76433.0, direction="down", price=76403.6)
    # no "source" key → not suppressed by this filter (dedup may still kick in)
    assert w._should_send(row) is True
