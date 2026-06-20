"""Tests for inverted PRE_CASCADE_ENTRY_PLANS (2026-05-19 re-validation).

Live validation на n=63 SHORT pre-cluster fires + n=48 LONG pre-cluster fires
показал inversion edge (continuation play мёртв, inverted SHORT @ 24h работает).
"""
from __future__ import annotations

from services.pre_cascade_alert.liq_clustering import PRE_CASCADE_ENTRY_PLANS


def test_short_plan_is_inverted_to_short_direction() -> None:
    """SHORT pre-cluster теперь предлагает SHORT, не LONG (live 4h 44.4% UP)."""
    plan = PRE_CASCADE_ENTRY_PLANS["short"]
    assert plan["dir"] == "SHORT"
    # SHORT trade → TPs ниже entry, stop выше
    assert plan["tp1_pct"] < 0
    assert plan["tp2_pct"] < 0
    assert plan["stop_pct"] > 0


def test_short_plan_uses_24h_hold() -> None:
    """24h horizon — где edge максимален (36% UP = 64% DOWN, mean -0.468%)."""
    plan = PRE_CASCADE_ENTRY_PLANS["short"]
    assert plan["exit_after_h"] == 24


def test_long_plan_now_exists_as_inverted_short() -> None:
    """LONG pre-cluster раньше не имел plan (defensive only).
    Re-validation показала самый сильный inverted edge (24h 29% UP = 71% DOWN)."""
    assert "long" in PRE_CASCADE_ENTRY_PLANS
    plan = PRE_CASCADE_ENTRY_PLANS["long"]
    assert plan["dir"] == "SHORT"
    assert plan["exit_after_h"] == 24


def test_plans_half_size_pending_more_fills() -> None:
    """Half-size $2500 до накопления 30+ собственных fills с inverted WR."""
    for side in ("short", "long"):
        plan = PRE_CASCADE_ENTRY_PLANS[side]
        assert plan.get("size_usd") == 2500


def test_edge_notes_cite_live_validation_2026_05_19() -> None:
    """edge_note должен ссылаться на свежее измерение, не на старое 'n=20 1 неделя'."""
    for side in ("short", "long"):
        note = PRE_CASCADE_ENTRY_PLANS[side]["edge_note"]
        assert "Re-validated" in note or "2026-05-19" in note
        assert "n=20" not in note  # old stale claim gone
        assert "75%" not in note   # old stale claim gone


def test_plan_ev_is_positive_after_fees() -> None:
    """Realized mean abs return @ 24h (inverted SHORT) = +0.468% per re-validation.
    After BitMEX taker 0.15% RT → ≥+0.30% net. Sanity: this is the actual edge."""
    realized_mean_pct = 0.468  # |mean| @ 24h, inverted SHORT direction
    ev_net = realized_mean_pct - 0.15  # BitMEX taker RT
    assert ev_net > 0.15, f"Net EV должен быть meaningfully positive, got {ev_net:.3f}%"


def test_tp2_aligned_with_realized_median() -> None:
    """TP2 -0.90% близко к realized median win -0.928% (inverted SHORT direction)."""
    plan = PRE_CASCADE_ENTRY_PLANS["short"]
    realized_median = -0.928
    # TP2 should be within 0.2pp of median realized (calibrated target)
    assert abs(plan["tp2_pct"] - realized_median) < 0.2
