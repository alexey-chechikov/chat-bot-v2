"""Orchestrator anti-whipsaw (Win 25.06): min-dwell на границе low-vol↔TREND.
25.06 2:05-8:04 флипало БОКОВИК↔ТРЕНД-ВНИЗ ~7×/6ч, дёргая BTC-LONG. Win предложил
ATR-дедбенд, но тренд определяется ADX/EMA (ATR синт.тренда 0.77% < range 0.85%),
поэтому временной гистерезис, а не ATR-гейт."""
from __future__ import annotations

from core.orchestrator.regime_classifier import (
    is_lowvol_trend_flip, MIN_DWELL_MIN_TREND_FLIP,
    PRIMARY_RANGE, PRIMARY_COMPRESSION, PRIMARY_TREND_DOWN, PRIMARY_TREND_UP,
)


def test_flip_detection_boundary_crossings():
    assert is_lowvol_trend_flip(PRIMARY_RANGE, PRIMARY_TREND_DOWN)
    assert is_lowvol_trend_flip(PRIMARY_TREND_DOWN, PRIMARY_RANGE)
    assert is_lowvol_trend_flip(PRIMARY_COMPRESSION, PRIMARY_TREND_UP)
    assert is_lowvol_trend_flip(PRIMARY_TREND_UP, PRIMARY_COMPRESSION)


def test_non_boundary_pairs_not_flagged():
    # low-vol↔low-vol (отдельный гейт) и trend↔trend — не наш дедбенд
    assert not is_lowvol_trend_flip(PRIMARY_RANGE, PRIMARY_COMPRESSION)
    assert not is_lowvol_trend_flip(PRIMARY_TREND_UP, PRIMARY_TREND_DOWN)
    assert not is_lowvol_trend_flip(PRIMARY_RANGE, PRIMARY_RANGE)


def test_dwell_threshold_value():
    assert MIN_DWELL_MIN_TREND_FLIP == 90
