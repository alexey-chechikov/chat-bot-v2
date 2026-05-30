"""Tests for SETUP_OVERRIDES — conservative pdl_bounce exits.

2026-05-30: the tp1.5/sl0.5 "exit edge" was REVERTED after the 2-year backtest
(tools/_setup_2y_backtest.py) showed WR 32% / EV −0.18% / negative every year —
the May +0.30% was a single-regime fluke. Back to the prior conservative values.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.auto_executor.loop import SETUP_OVERRIDES


def test_pdl_bounce_override_present_with_expected_values() -> None:
    override = SETUP_OVERRIDES.get("long_pdl_bounce")
    assert override is not None
    assert override["sl_pct"] == 0.40
    assert override["tp1_pct"] == 0.70
    assert override["hold_hours"] == 6


def test_dump_reversal_NOT_overridden() -> None:
    """2y backtest negative — no fixed-exit override; use detector geometry."""
    assert "long_dump_reversal" not in SETUP_OVERRIDES


def test_multi_divergence_NOT_overridden() -> None:
    assert "long_multi_divergence" not in SETUP_OVERRIDES


def test_override_math_sl_at_minus_040pct() -> None:
    entry = 76000.0
    sl_pct = SETUP_OVERRIDES["long_pdl_bounce"]["sl_pct"]
    assert round(entry * (1 - sl_pct / 100.0), 1) == 75696.0


def test_override_math_tp1_at_plus_070pct() -> None:
    entry = 76000.0
    tp1_pct = SETUP_OVERRIDES["long_pdl_bounce"]["tp1_pct"]
    assert round(entry * (1 + tp1_pct / 100.0), 1) == 76532.0


def test_override_hold_window_is_6h() -> None:
    detected = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)
    expected = detected + timedelta(hours=SETUP_OVERRIDES["long_pdl_bounce"]["hold_hours"])
    assert (expected - detected).total_seconds() == 6 * 3600


def test_override_rr_is_175_to_1() -> None:
    o = SETUP_OVERRIDES["long_pdl_bounce"]
    assert o["tp1_pct"] / o["sl_pct"] == pytest.approx(1.75)
