"""Tests for cascade_followup _recent_losses_streak — fast circuit-breaker
that suppresses TG emission after 3 consecutive evaluated losses on the
same variant bucket (drift_guard waits for n>=10 to flip; this catches
sudden regime breaks much faster).
"""
import json
from pathlib import Path

from services.cascade_followup.loop import _recent_losses_streak


def _w(tmp_path: Path, records: list[dict]) -> Path:
    p = tmp_path / "cascade_accuracy.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in records) + "\n",
                 encoding="utf-8")
    return p


def test_streak_three_short_side_long_fade_losses(tmp_path):
    """3 consecutive LONG-fade losses (price went DOWN after short-liqs)
    → streak True. Uses mega bucket (threshold>=10)."""
    p = _w(tmp_path, [
        {"direction": "short", "threshold_btc": 10.0, "realized_pct_4h": -0.5},
        {"direction": "short", "threshold_btc": 10.0, "realized_pct_4h": -0.3},
        {"direction": "short", "threshold_btc": 10.0, "realized_pct_4h": -0.7},
    ])
    streak, n = _recent_losses_streak("short", 10.0, path=p)
    assert streak is True and n == 3


def test_streak_breaks_on_win(tmp_path):
    """Recent win breaks the streak — no suppression even with prior losses."""
    p = _w(tmp_path, [
        {"direction": "short", "threshold_btc": 10.0, "realized_pct_4h": -0.5},
        {"direction": "short", "threshold_btc": 10.0, "realized_pct_4h": -0.3},
        {"direction": "short", "threshold_btc": 10.0, "realized_pct_4h": +0.2},  # win, most recent
    ])
    streak, n = _recent_losses_streak("short", 10.0, path=p)
    assert streak is False


def test_bucket_isolation_mega_vs_non_mega(tmp_path):
    """A streak in the mega bucket must NOT trip the non-mega circuit and
    vice-versa (separate liquidity regimes)."""
    p = _w(tmp_path, [
        {"direction": "short", "threshold_btc": 5.0, "realized_pct_4h": -0.5},
        {"direction": "short", "threshold_btc": 5.0, "realized_pct_4h": -0.3},
        {"direction": "short", "threshold_btc": 5.0, "realized_pct_4h": -0.7},
    ])
    # mega bucket has no records -> no streak
    streak_mega, n_mega = _recent_losses_streak("short", 10.0, path=p)
    assert streak_mega is False and n_mega == 0
    # non-mega has 3 losses -> streak
    streak_5btc, n_5btc = _recent_losses_streak("short", 5.0, path=p)
    assert streak_5btc is True and n_5btc == 3


def test_long_side_fade_short_loss_direction(tmp_path):
    """For liq_side='long' the fade trade is SHORT — loss when price went UP
    (realized_pct_4h > 0)."""
    p = _w(tmp_path, [
        {"direction": "long", "threshold_btc": 5.0, "realized_pct_4h": +0.4},
        {"direction": "long", "threshold_btc": 5.0, "realized_pct_4h": +0.1},
        {"direction": "long", "threshold_btc": 5.0, "realized_pct_4h": +0.6},
    ])
    streak, n = _recent_losses_streak("long", 5.0, path=p)
    assert streak is True and n == 3


def test_pending_outcomes_ignored(tmp_path):
    """Entries with realized_pct_4h=None (still pending) are skipped so the
    fresh-fire flood right after a regime break doesn't drown the streak."""
    p = _w(tmp_path, [
        # 3 evaluated losses (these should trigger streak)
        {"direction": "short", "threshold_btc": 10.0, "realized_pct_4h": -0.5},
        {"direction": "short", "threshold_btc": 10.0, "realized_pct_4h": -0.3},
        {"direction": "short", "threshold_btc": 10.0, "realized_pct_4h": -0.7},
        # 5 pending fires after (the spam during the dump)
        {"direction": "short", "threshold_btc": 10.0, "realized_pct_4h": None},
        {"direction": "short", "threshold_btc": 10.0, "realized_pct_4h": None},
        {"direction": "short", "threshold_btc": 10.0, "realized_pct_4h": None},
    ])
    streak, n = _recent_losses_streak("short", 10.0, path=p)
    assert streak is True and n == 3


def test_insufficient_evaluated_returns_false(tmp_path):
    """Fewer than n=3 evaluated entries → False (need data to act)."""
    p = _w(tmp_path, [
        {"direction": "short", "threshold_btc": 10.0, "realized_pct_4h": -0.5},
        {"direction": "short", "threshold_btc": 10.0, "realized_pct_4h": -0.3},
    ])
    streak, n = _recent_losses_streak("short", 10.0, path=p)
    assert streak is False and n == 2


def test_missing_path_safe(tmp_path):
    """No journal file → no streak (fail-open, do not suppress)."""
    streak, n = _recent_losses_streak("short", 10.0, path=tmp_path / "nope.jsonl")
    assert streak is False and n == 0
