"""Tests for SHORT-side INVERTED_PLAYS in cascade_alert.

Per 2026-05-19 live drift findings (state/cascade_edge_drift.json):
  short_24h accuracy 37.2% n=43 → DOWN-WR 62.8% → INVERTED SHORT fade is the
  best available play on a drifted SHORT-cascade.
"""
from __future__ import annotations

from unittest.mock import patch

import services.cascade_alert.loop as cs_loop
from services.cascade_alert.loop import INVERTED_PLAYS, _format_alert


def test_inverted_plays_has_short_5btc() -> None:
    assert ("short", 5.0) in INVERTED_PLAYS
    plan = INVERTED_PLAYS[("short", 5.0)]["entry_plan"]
    assert plan["dir"] == "SHORT"
    assert plan["tp1_pct"] < 0
    assert plan["tp2_pct"] < 0
    assert plan["stop_pct"] > 0
    assert plan["size_usd"] <= 2500  # half-size sanity


def test_short_2btc_inverted_removed_minus_ev() -> None:
    """Was added 2026-05-19 morning, removed afternoon — -EV after fees per
    re-sweep (long_2btc inverted 4h DOWN 51.2%, mean +0.091%, net -0.06%/trade)."""
    assert ("short", 2.0) not in INVERTED_PLAYS


def test_format_alert_uses_inverted_for_drifted_short() -> None:
    """When is_drifted returns True for short-cascade, _format_alert should
    produce the inverted SHORT play, not the original continuation."""
    with patch("services.cascade_alert.edge_drift_guard.is_drifted",
                return_value=True):
        text = _format_alert("short", 5.0, 6.5, 81500.0)
    assert "INVERTED" in text or "EDGE INVERTED" in text
    assert "SHORT" in text
    assert "fade" in text.lower() or "squeeze" in text.lower()


def test_format_alert_keeps_continuation_for_healthy_short() -> None:
    """When not drifted — keep the original short-cascade play (no inversion)."""
    with patch("services.cascade_alert.edge_drift_guard.is_drifted",
                return_value=False):
        text = _format_alert("short", 5.0, 6.5, 81500.0)
    assert "INVERTED" not in text
    assert "EDGE INVERTED" not in text
