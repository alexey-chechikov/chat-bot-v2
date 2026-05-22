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


def test_up_pump_FIRES_with_pullback_now():
    """Whipsaw events (с intermediate pullback) теперь паузим тоже
    (per Win-колеги verification 2026-05-18: one-way filter removed)."""
    base_ts = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
    bars = []
    for i in range(31):
        cl = 80000 + (81600 - 80000) * i / 30
        low = 79500 if i == 5 else cl  # -0.625% pullback intermediate
        bars.append((base_ts + timedelta(minutes=i), cl, low, cl))
    ev = detect_move(bars, direction="up")
    assert ev is not None  # NEW: fires even with pullback (whipsaw тоже паузим)


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


def test_down_dump_FIRES_with_up_retracement_now():
    """Whipsaw dumps (с intermediate up bounce) тоже fire — one-way filter removed."""
    base_ts = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
    bars = []
    for i in range(31):
        cl = 80000 + (78400 - 80000) * i / 30
        hi = 80500 if i == 5 else cl  # +0.625% bounce intermediate
        bars.append((base_ts + timedelta(minutes=i), hi, cl, cl))
    assert detect_move(bars, direction="down") is not None


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


# ─── Resume condition 2: STALL (no new extreme for N min) ───────────────────

def test_resume_stall_fires_short_when_no_new_high():
    """SHORT frozen on pump: price flat under hi for >= stall_min → resume."""
    now = datetime(2026, 5, 18, 14, 0, tzinfo=timezone.utc)
    freeze_ts = now - timedelta(hours=1)
    last_extreme = now - timedelta(minutes=50)  # 50 min idle ≥ 45
    done, reason = should_resume(
        freeze_extreme_price=81000, current_price=80950,  # only -0.06%, no retrace
        freeze_ts=freeze_ts, now=now, side="short",
        retrace_pct=1.0, timeout_hours=12,
        last_extreme_ts=last_extreme, stall_min=45,
    )
    assert done
    assert "stall" in reason


def test_resume_stall_fires_long_when_no_new_low():
    """LONG frozen on dump: price flat above lo for >= stall_min → resume."""
    now = datetime(2026, 5, 18, 14, 0, tzinfo=timezone.utc)
    freeze_ts = now - timedelta(hours=1)
    last_extreme = now - timedelta(minutes=46)
    done, reason = should_resume(
        freeze_extreme_price=78400, current_price=78450,  # near trough, no retrace
        freeze_ts=freeze_ts, now=now, side="long",
        retrace_pct=1.0, timeout_hours=12,
        last_extreme_ts=last_extreme, stall_min=45,
    )
    assert done
    assert "stall" in reason


def test_resume_stall_not_fired_before_threshold():
    """Idle time below stall_min → no stall resume."""
    now = datetime(2026, 5, 18, 14, 0, tzinfo=timezone.utc)
    freeze_ts = now - timedelta(minutes=40)
    last_extreme = now - timedelta(minutes=30)  # 30 min < 45
    done, _ = should_resume(
        freeze_extreme_price=81000, current_price=80960,  # no retrace either
        freeze_ts=freeze_ts, now=now, side="short",
        retrace_pct=1.0, timeout_hours=12,
        last_extreme_ts=last_extreme, stall_min=45,
    )
    assert not done


def test_resume_stall_skipped_when_args_missing():
    """No last_extreme_ts / stall_min → stall check is a no-op (back-compat)."""
    now = datetime(2026, 5, 18, 14, 0, tzinfo=timezone.utc)
    freeze_ts = now - timedelta(hours=1)
    done, _ = should_resume(
        freeze_extreme_price=81000, current_price=80960,
        freeze_ts=freeze_ts, now=now, side="short",
        retrace_pct=1.0, timeout_hours=12,
    )
    assert not done  # no retrace, no stall args, timeout 12h not reached


def test_resume_stall_clock_resets_on_new_extreme():
    """A recent new extreme keeps the bot frozen even after long total freeze."""
    now = datetime(2026, 5, 18, 17, 0, tzinfo=timezone.utc)
    freeze_ts = now - timedelta(hours=3)            # frozen 3h total
    last_extreme = now - timedelta(minutes=10)      # but new hi 10 min ago
    done, _ = should_resume(
        freeze_extreme_price=82000, current_price=81980,  # no retrace
        freeze_ts=freeze_ts, now=now, side="short",
        retrace_pct=1.0, timeout_hours=12,
        last_extreme_ts=last_extreme, stall_min=45,
    )
    assert not done  # extreme still moving → stay frozen


# ─── Resume priority — retracement wins over stall/timeout ──────────────────

def test_resume_retracement_takes_priority_over_stall():
    """Both retrace AND stall true → reason is retracement (checked first)."""
    now = datetime(2026, 5, 18, 14, 0, tzinfo=timezone.utc)
    freeze_ts = now - timedelta(hours=1)
    last_extreme = now - timedelta(minutes=50)  # stall also true
    done, reason = should_resume(
        freeze_extreme_price=81000, current_price=80100,  # -1.1% retrace
        freeze_ts=freeze_ts, now=now, side="short",
        retrace_pct=1.0, timeout_hours=12,
        last_extreme_ts=last_extreme, stall_min=45,
    )
    assert done
    assert "retracement" in reason


def test_resume_stall_takes_priority_over_timeout():
    """Stall and timeout both true → stall reason (checked before timeout)."""
    now = datetime(2026, 5, 18, 14, 0, tzinfo=timezone.utc)
    freeze_ts = now - timedelta(hours=13)        # timeout 12h exceeded
    last_extreme = now - timedelta(minutes=60)   # stall also true
    done, reason = should_resume(
        freeze_extreme_price=81000, current_price=80950,
        freeze_ts=freeze_ts, now=now, side="short",
        retrace_pct=1.0, timeout_hours=12,
        last_extreme_ts=last_extreme, stall_min=45,
    )
    assert done
    assert "stall" in reason


def test_resume_none_when_move_still_active():
    """Move active: no retrace, recent extreme, before timeout → stay frozen."""
    now = datetime(2026, 5, 18, 13, 0, tzinfo=timezone.utc)
    freeze_ts = now - timedelta(minutes=30)
    last_extreme = now - timedelta(minutes=3)
    for side, ext, cur in (("short", 81000, 80990), ("long", 78400, 78410)):
        done, _ = should_resume(
            freeze_extreme_price=ext, current_price=cur,
            freeze_ts=freeze_ts, now=now, side=side,
            retrace_pct=1.0, timeout_hours=12,
            last_extreme_ts=last_extreme, stall_min=45,
        )
        assert not done
