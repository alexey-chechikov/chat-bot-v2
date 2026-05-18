"""Tests for pump_freeze.detector — bidirectional."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.pump_freeze.detector import detect_move, should_resume


def _bars_flat(price: float, n: int = 31) -> list:
    base_ts = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
    return [(base_ts + timedelta(minutes=i), price, price, price) for i in range(n)]


def _bars_linear(start: float, end: float, n: int = 31) -> list:
    base_ts = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
    bars = []
    for i in range(n):
        cl = start + (end - start) * i / max(n - 1, 1)
        bars.append((base_ts + timedelta(minutes=i), cl, cl, cl))
    return bars


# ─── UP pump detection ──────────────────────────────────────────────────────

def test_up_pump_detected():
    bars = _bars_linear(80000, 81600, n=31)  # +2.0%
    ev = detect_move(bars, direction="up")
    assert ev is not None
    assert ev.direction == "up"
    assert ev.move_pct >= 1.5


def test_up_pump_not_fired_below_threshold():
    bars = _bars_linear(80000, 81040, n=31)  # +1.3%
    assert detect_move(bars, direction="up") is None


def test_up_pump_not_fired_with_pullback():
    base_ts = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
    bars = []
    for i in range(31):
        cl = 80000 + (81600 - 80000) * i / 30
        low = 79500 if i == 5 else cl  # -0.625% pullback
        bars.append((base_ts + timedelta(minutes=i), cl, low, cl))
    assert detect_move(bars, direction="up") is None


def test_up_pump_does_not_trigger_dump_check():
    bars = _bars_linear(80000, 81600, n=31)  # up move
    assert detect_move(bars, direction="down") is None


# ─── DOWN dump detection ────────────────────────────────────────────────────

def test_down_dump_detected():
    bars = _bars_linear(80000, 78400, n=31)  # -2.0%
    ev = detect_move(bars, direction="down")
    assert ev is not None
    assert ev.direction == "down"
    assert ev.move_pct <= -1.5


def test_down_dump_not_fired_below_threshold():
    bars = _bars_linear(80000, 78960, n=31)  # -1.3%
    assert detect_move(bars, direction="down") is None


def test_down_dump_not_fired_with_up_retracement():
    base_ts = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
    bars = []
    for i in range(31):
        cl = 80000 + (78400 - 80000) * i / 30
        hi = 80500 if i == 5 else cl  # +0.625% up retracement
        bars.append((base_ts + timedelta(minutes=i), hi, cl, cl))
    assert detect_move(bars, direction="down") is None


def test_down_dump_does_not_trigger_pump_check():
    bars = _bars_linear(80000, 78400, n=31)  # down move
    assert detect_move(bars, direction="up") is None


# ─── No move ────────────────────────────────────────────────────────────────

def test_flat_no_event_either_direction():
    bars = _bars_flat(80000)
    assert detect_move(bars, direction="up") is None
    assert detect_move(bars, direction="down") is None


# ─── Resume conditions (bidirectional) ──────────────────────────────────────

def test_resume_short_on_retracement_down():
    """SHORT frozen on pump: resume when price retraces DOWN from peak."""
    now = datetime(2026, 5, 18, 13, 0, tzinfo=timezone.utc)
    freeze_ts = now - timedelta(minutes=30)
    done, reason = should_resume(
        freeze_extreme_price=81000, current_price=80190,  # -1.0% from peak
        freeze_ts=freeze_ts, now=now, side="short",
        retrace_pct=1.0, timeout_hours=2,
    )
    assert done
    assert "retracement" in reason


def test_resume_long_on_retracement_up():
    """LONG frozen on dump: resume when price retraces UP from trough."""
    now = datetime(2026, 5, 18, 13, 0, tzinfo=timezone.utc)
    freeze_ts = now - timedelta(minutes=30)
    done, reason = should_resume(
        freeze_extreme_price=78400, current_price=79190,  # +1.0% from trough
        freeze_ts=freeze_ts, now=now, side="long",
        retrace_pct=1.0, timeout_hours=2,
    )
    assert done
    assert "retracement" in reason


def test_resume_short_no_trigger_on_continued_pump():
    """SHORT frozen, price stays NEAR peak → no resume."""
    now = datetime(2026, 5, 18, 13, 0, tzinfo=timezone.utc)
    freeze_ts = now - timedelta(minutes=30)
    done, _ = should_resume(
        freeze_extreme_price=81000, current_price=80950,  # only -0.06% from peak
        freeze_ts=freeze_ts, now=now, side="short",
        retrace_pct=1.0, timeout_hours=2,
    )
    assert not done


def test_resume_on_timeout_regardless_of_side():
    now = datetime(2026, 5, 18, 13, 0, tzinfo=timezone.utc)
    freeze_ts = now - timedelta(hours=2, minutes=5)
    for side in ("short", "long"):
        done, reason = should_resume(
            freeze_extreme_price=81000, current_price=80995,
            freeze_ts=freeze_ts, now=now, side=side,
            retrace_pct=1.0, timeout_hours=2,
        )
        assert done
        assert "timeout" in reason
