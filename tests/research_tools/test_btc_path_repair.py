"""Acceptance: target-exit boundaries, OHLC bounds, minute continuity, label safety."""
from __future__ import annotations

import numpy as np
import pytest

from services.btc_signals import features as fx
from services.btc_signals.excursions import PATH_BOUND_FIELDS
from research.chart_walk_20261105 import trade_scan


def hours(high=(100, 110), low=(100, 80), op=(100, 100), close=(100, 100), atr=1):
    n = len(close)
    return {"t": np.arange(n) * 3600, "o": np.array(op, float), "h": np.array(high, float),
            "l": np.array(low, float), "c": np.array(close, float), "atr4": np.full(n, atr, float)}


def tape(ts, op, high, low, close):
    return {"t": np.array(ts), "o": np.array(op), "h": np.array(high), "l": np.array(low), "c": np.array(close)}


def test_hour_target_caps_favorable_extreme_and_marks_unknown_adverse():
    result = fx.path(hours(), 0, 1, -1, 100, 95, exit_mode="target")
    assert result["MFE, ATR"] == result["MFE lower, ATR"] == result["MFE upper, ATR"] == 5
    assert result["отдача, ATR"] == 0
    assert result["MAE lower, ATR"] == 0 and result["MAE upper, ATR"] == 10
    assert result["MAE, ATR"] is None and result["MAE, %"] is None
    assert result["сначала +1 ATR или −1 ATR"] is None
    assert result["качество пути"] == "ambiguous"


@pytest.mark.parametrize("side,price", [(-1, 94), (1, 106)])
def test_open_gap_excludes_the_entire_exit_bar_extremes(side, price):
    a = hours(op=(100, price))
    result = fx.path(a, 0, 1, side, 100, price, exit_mode="target")
    assert result["MFE, ATR"] == 6
    assert result["MAE, ATR"] == result["MAE upper, ATR"] == result["MAE lower, ATR"] == 0
    assert result["разрешение выхода"] == "open"
    assert result["качество пути"] == "exact"
    assert result["часов до MFE"] == 0
    assert result["часов до MFE lower"] == result["часов до MFE upper"] == 0


def test_close_exit_keeps_complete_hourly_extrema_but_not_invented_order():
    result = fx.path(hours(), 0, 1, -1, 100, 95)
    assert result["MFE, ATR"] == 20 and result["MAE, ATR"] == 10
    assert result["отдача, ATR"] == 15
    assert result["сначала +1 ATR или −1 ATR"] is None
    assert result["качество порядка ±1 ATR"] == "ambiguous"
    assert result["часов до MFE"] == result["часов до MFE upper"] == 1
    assert result["часов до MFE lower"] == 0
    assert result["семантика времени экстремумов"] == "bar_upper_bound_not_tick_time"


def test_target_preserves_extremes_from_completed_prior_hours():
    a = hours(high=(100, 113, 110), low=(100, 96, 80), op=(100, 100, 100), close=(100, 100, 100))
    result = fx.path(a, 0, 2, -1, 100, 95, exit_mode="target")
    assert result["MFE, ATR"] == 5
    assert result["MAE lower, ATR"] == result["MAE upper, ATR"] == result["MAE, ATR"] == 13


def test_target_adverse_lower_bound_includes_known_hour_open():
    a = hours(op=(100, 103))
    result = fx.path(a, 0, 1, -1, 100, 95, exit_mode="target")
    assert result["MAE lower, ATR"] == 3 and result["MAE upper, ATR"] == 10
    assert result["MAE, ATR"] is None


def test_minute_tape_stops_at_first_hit_and_bounds_touching_minute_only():
    a = hours(high=(100, 120), low=(100, 70))
    minute = tape([0, 60, 120], [100, 99.5, 95], [100.2, 100.5, 120], [99, 94, 70], [99.5, 95, 100])
    result = fx.path(a, 0, 1, -1, 100, 95, exit_mode="target", execution=minute)
    assert result["MFE, ATR"] == 5 and result["отдача, ATR"] == 0
    assert result["MAE lower, ATR"] == pytest.approx(.2)
    assert result["MAE upper, ATR"] == pytest.approx(.5)
    assert result["MAE, ATR"] is None
    assert result["разрешение выхода"] == "minute"
    assert result["причина качества пути"] == "minute_touch_bounds"
    assert result["сначала +1 ATR или −1 ATR"] == 1
    assert result["часов до MFE lower"] == pytest.approx(1 / 60)
    assert result["часов до MFE upper"] == pytest.approx(2 / 60)
    assert result["часов до MFE"] == result["часов до MFE upper"]
    assert result["часов до MAE lower"] is None


def test_completed_prior_minute_can_make_adverse_excursion_exact():
    minute = tape([0, 60, 120], [100, 99.5, 95], [103, 102, 120], [99, 94, 70], [99.5, 95, 100])
    result = fx.path(hours(high=(100, 120), low=(100, 70), atr=2), 0, 1, -1, 100, 95,
                     exit_mode="target", execution=minute)
    assert result["MFE, ATR"] == 2.5
    assert result["MAE, ATR"] == result["MAE lower, ATR"] == result["MAE upper, ATR"] == 1.5
    assert result["сначала +1 ATR или −1 ATR"] == -1
    assert result["качество пути"] == "exact"


def test_missing_minute_before_hit_falls_back_to_hourly_bounds():
    minute = tape([0, 120], [100, 99.5], [100.2, 100.5], [99, 94], [99.5, 95])
    result = fx.path(hours(), 0, 1, -1, 100, 95, exit_mode="target", execution=minute)
    assert result["разрешение выхода"] == "hour"
    assert result["причина качества пути"] == "minute_gap_before_execution"
    assert result["MAE upper, ATR"] == 10 and result["MAE, ATR"] is None


def test_gaps_and_extremes_after_execution_cannot_change_the_path():
    before = tape([0], [100], [100.2], [94], [95])
    after = tape([0, 360, 900], [100, 95, 100], [100.2, 900, 1000], [94, 1, .1], [95, 100, 100])
    a = hours(high=(100, 1000), low=(100, .1))
    result = fx.path(a, 0, 1, -1, 100, 95, exit_mode="target", execution=before)
    assert result == fx.path(a, 0, 1, -1, 100, 95, exit_mode="target", execution=after)


def test_sequence_from_different_complete_bars_is_known():
    a = hours(high=(100, 100.1, 102), low=(100, 98, 99), op=(100, 100, 100), close=(100, 100, 100))
    result = fx.path(a, 0, 2, -1, 100, 100)
    assert result["сначала +1 ATR или −1 ATR"] == 1
    assert result["качество порядка ±1 ATR"] == "exact"


def test_no_threshold_hit_remains_zero():
    result = fx.path(hours(high=(100, 100.1), low=(100, 99.9)), 0, 1, 1, 100, 100)
    assert result["сначала +1 ATR или −1 ATR"] == 0


def test_new_path_bounds_and_quality_are_never_model_inputs():
    assert PATH_BOUND_FIELDS <= trade_scan.OUTCOME
    assert "добор UTC" in trade_scan.OUTCOME


def test_capped_horizon_uses_actual_clock_and_missing_exact_hour_is_unknown():
    a = hours(high=(100, 100, 102, 103), low=(100, 100, 100, 100),
              op=(100, 100, 100, 100), close=(100, 100, 102, 103))
    a["t"] = np.array([0, 1, 25, 26]) * 3600
    result = fx.path(a, 0, 3, 1, 100, 103)
    assert result["часов в сделке"] == 26
    assert result["ход через 24ч, %"] is None
    assert result["ход через 72ч, %"] == pytest.approx(3)
    assert result["ход через 7д, %"] == pytest.approx(3)

