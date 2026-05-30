"""Tests for SETUP_OVERRIDES — exit params from the FIXED per-pair tracker.

2026-05-30: exit-optimization (tools/_exit_optimize.py) on correctly-graded
per-pair price → dip-buy setups use tight SL 0.5% + wide TP 1.5%, 2h hold
(net +0.30%/trade, OOS time-split holds). pdl_bounce + dump_reversal overridden.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.auto_executor.loop import SETUP_OVERRIDES


def test_pdl_bounce_override_present_with_expected_values() -> None:
    override = SETUP_OVERRIDES.get("long_pdl_bounce")
    assert override is not None
    assert override["sl_pct"] == 0.50
    assert override["tp1_pct"] == 1.50
    assert override["hold_hours"] == 2


def test_dump_reversal_override_present() -> None:
    override = SETUP_OVERRIDES.get("long_dump_reversal")
    assert override is not None
    assert override["sl_pct"] == 0.50
    assert override["tp1_pct"] == 1.50
    assert override["hold_hours"] == 2


def test_multi_divergence_NOT_overridden() -> None:
    """Honest precision: 1 TP1 / 82 — keep it out (also removed from allowlist)."""
    assert "long_multi_divergence" not in SETUP_OVERRIDES


def test_override_math_sl_at_minus_050pct() -> None:
    entry = 76000.0
    sl_pct = SETUP_OVERRIDES["long_pdl_bounce"]["sl_pct"]
    expected_sl = round(entry * (1 - sl_pct / 100.0), 1)
    assert expected_sl == 75620.0  # 76000 * 0.995


def test_override_math_tp1_at_plus_150pct() -> None:
    entry = 76000.0
    tp1_pct = SETUP_OVERRIDES["long_pdl_bounce"]["tp1_pct"]
    expected_tp1 = round(entry * (1 + tp1_pct / 100.0), 1)
    assert expected_tp1 == 77140.0  # 76000 * 1.015


def test_override_hold_window_is_2h() -> None:
    detected = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)
    expected_expire = detected + timedelta(
        hours=SETUP_OVERRIDES["long_pdl_bounce"]["hold_hours"]
    )
    assert (expected_expire - detected).total_seconds() == 2 * 3600


def test_override_rr_is_3_to_1() -> None:
    """TP1 1.50 / SL 0.50 → R:R 3:1 (tight stop, wide target)."""
    o = SETUP_OVERRIDES["long_pdl_bounce"]
    assert o["tp1_pct"] / o["sl_pct"] == pytest.approx(3.0)
