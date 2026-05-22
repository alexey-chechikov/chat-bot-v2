"""Tests for the Phase-4 live feature pipeline (_compute_bar_features).

Synthetic deterministic bars → every reliable feature is hand-computable,
verifying the live computation matches build_event_catalog.py formulas.
"""
from datetime import datetime, timedelta, timezone

from services.pump_freeze.loop import _compute_bar_features

T0 = datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc)


def _bars(n: int) -> list:
    """n 1-min bars; close[i] = 100 + i, open = close-0.5,
    high = close+0.2, low = close-0.7, volume = 10."""
    out = []
    for i in range(n):
        c = 100.0 + i
        out.append((T0 + timedelta(minutes=i), c - 0.5, c + 0.2, c - 0.7, c, 10.0))
    return out


def test_compute_features_known_values():
    bars = _bars(250)
    freeze_ts = bars[150][0]          # anchor a = 150, window 30 -> ws = 120
    f = _compute_bar_features(bars, freeze_ts)

    # move_pct = (close[150]-close[120])/close[120]*100 = (250-220)/220*100
    assert abs(f["move_pct"] - 13.6363636) < 1e-4
    # forward horizons from trigger close[150]=250
    assert abs(f["move_t5"] - 2.0) < 1e-6     # (255-250)/250*100
    assert abs(f["move_t15"] - 6.0) < 1e-6    # (265-250)/250
    assert abs(f["move_t30"] - 12.0) < 1e-6   # (280-250)/250
    assert abs(f["move_t60"] - 24.0) < 1e-6   # (310-250)/250
    # linear close → 2nd diff zero → accel 0
    assert abs(f["accel"]) < 1e-9
    # wick = 0.9, body = 0.5 → ratio ≈ 1.8
    assert abs(f["wick_ratio"] - 1.8) < 1e-6
    # win_vol = 31*10 = 310 ; base = median(10..)*30 = 300 → 1.0333
    assert abs(f["vol_spike"] - (310.0 / 300.0)) < 1e-6


def test_insufficient_history_returns_empty():
    assert _compute_bar_features(_bars(10), T0 + timedelta(minutes=5)) == {}


def test_anchor_before_data_returns_empty():
    bars = _bars(100)
    # freeze_ts earlier than every bar → no anchor
    assert _compute_bar_features(bars, T0 - timedelta(hours=1)) == {}


def test_anchor_too_close_to_start_returns_empty():
    bars = _bars(100)
    # anchor at index 10 < window(30) → not enough pre-window history
    assert _compute_bar_features(bars, bars[10][0]) == {}
