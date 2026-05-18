"""Tests for pump_freeze.detector."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.pump_freeze.detector import PumpEvent, detect, should_resume


def _bars_flat(price: float, n: int = 35) -> list:
    """Generate n bars at flat price."""
    base_ts = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
    return [(base_ts + timedelta(minutes=i), price, price, price) for i in range(n)]


def _bars_linear_climb(start: float, end: float, n: int = 35) -> list:
    """n bars from start to end (linear)."""
    base_ts = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
    bars = []
    for i in range(n):
        cl = start + (end - start) * i / max(n - 1, 1)
        bars.append((base_ts + timedelta(minutes=i), cl, cl, cl))
    return bars


def test_no_pump_when_flat():
    bars = _bars_flat(80000)
    assert detect(bars) is None


def test_pump_detected_on_strong_climb():
    # Detector берёт last 31 bars (window_min+1=31). Generate 31 bars 80k→81.6k = +2%
    bars = _bars_linear_climb(80000, 81600, n=31)
    ev = detect(bars)
    assert ev is not None
    assert ev.move_pct >= 1.5
    assert ev.max_pullback_pct < 0.5


def test_no_pump_below_threshold():
    # 1.3% climb — under 1.5% threshold
    bars = _bars_linear_climb(80000, 81040, n=35)
    assert detect(bars) is None


def test_no_pump_with_pullback():
    # Climbs 1.6% but with mid-climb dip of -0.6%
    base_ts = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
    bars = []
    for i in range(35):
        # i=15: dip below start
        if i == 15:
            low = 79500  # -0.625% below start
            hi = 79500
            cl = 79500
        else:
            cl = 80000 + (81280 - 80000) * i / 34
            hi = cl
            low = cl
        bars.append((base_ts + timedelta(minutes=i), hi, low, cl))
    assert detect(bars) is None


def test_pump_borderline_pullback_passes():
    # 31 bars, 1.875% climb, with mid 0.3% pullback (< 0.5% threshold)
    base_ts = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
    bars = []
    for i in range(31):
        cl = 80000 + (81500 - 80000) * i / 30
        if i == 5:
            low = 79760  # -0.3% pullback from start
        else:
            low = cl
        bars.append((base_ts + timedelta(minutes=i), cl, low, cl))
    ev = detect(bars)
    assert ev is not None


def test_too_few_bars_returns_none():
    bars = _bars_linear_climb(80000, 81280, n=10)
    assert detect(bars) is None


# ─── resume conditions ──────────────────────────────────────────────────────

def test_resume_on_retracement():
    now = datetime(2026, 5, 18, 13, 0, tzinfo=timezone.utc)
    freeze_ts = now - timedelta(minutes=30)
    done, reason = should_resume(
        freeze_peak_price=81000, current_price=80190,  # -1.0% from peak
        freeze_ts=freeze_ts, now=now,
        retrace_pct=1.0, timeout_hours=2,
    )
    assert done
    assert "retracement" in reason


def test_resume_on_timeout():
    now = datetime(2026, 5, 18, 13, 0, tzinfo=timezone.utc)
    freeze_ts = now - timedelta(hours=2, minutes=5)
    done, reason = should_resume(
        freeze_peak_price=81000, current_price=80950,  # almost no retrace
        freeze_ts=freeze_ts, now=now,
        retrace_pct=1.0, timeout_hours=2,
    )
    assert done
    assert "timeout" in reason


def test_no_resume_if_neither():
    now = datetime(2026, 5, 18, 13, 0, tzinfo=timezone.utc)
    freeze_ts = now - timedelta(minutes=30)
    done, _ = should_resume(
        freeze_peak_price=81000, current_price=80900,  # only -0.12% retrace
        freeze_ts=freeze_ts, now=now,
        retrace_pct=1.0, timeout_hours=2,
    )
    assert not done
