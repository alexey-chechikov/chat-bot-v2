"""Tests for SETUP_OVERRIDES — backtest-derived fixed SL/TP for pdl_bounce."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.auto_executor.loop import SETUP_OVERRIDES


def test_pdl_bounce_override_present_with_expected_values() -> None:
    """Operator + backtest agreed on these — pin them so future edits are explicit."""
    override = SETUP_OVERRIDES.get("long_pdl_bounce")
    assert override is not None
    assert override["sl_pct"] == 0.40
    assert override["tp1_pct"] == 0.70
    assert override["hold_hours"] == 6


def test_multi_divergence_NOT_overridden() -> None:
    """Backtest 2026-05-27 showed all fixed grids -EV on multi_divergence — keep
    setup_detector's pattern-geometry values."""
    assert "long_multi_divergence" not in SETUP_OVERRIDES


def test_override_math_sl_at_minus_040pct() -> None:
    entry = 76000.0
    sl_pct = SETUP_OVERRIDES["long_pdl_bounce"]["sl_pct"]
    expected_sl = round(entry * (1 - sl_pct / 100.0), 1)
    # 76000 * 0.996 = 75696
    assert expected_sl == 75696.0


def test_override_math_tp1_at_plus_070pct() -> None:
    entry = 76000.0
    tp1_pct = SETUP_OVERRIDES["long_pdl_bounce"]["tp1_pct"]
    expected_tp1 = round(entry * (1 + tp1_pct / 100.0), 1)
    # 76000 * 1.007 = 76532
    assert expected_tp1 == 76532.0


def test_override_hold_window_is_6h() -> None:
    detected = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)
    expected_expire = detected + timedelta(
        hours=SETUP_OVERRIDES["long_pdl_bounce"]["hold_hours"]
    )
    assert (expected_expire - detected).total_seconds() == 6 * 3600


def test_override_rr_is_175_to_1() -> None:
    """Sanity: TP1 0.70 / SL 0.40 → R:R 1:1.75."""
    o = SETUP_OVERRIDES["long_pdl_bounce"]
    assert o["tp1_pct"] / o["sl_pct"] == pytest.approx(1.75)
