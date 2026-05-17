"""Filter-behavior tests for bot_brain pause rules.

Operator 2026-05-17 directive: pause only on TRULY strong one-sided moves,
not micro 0.3-1% spikes. T2/T3 NEVER auto-paused. These tests assert each
gate (tier filter, price-move gate, liq-cluster qty minimum) correctly
suppresses spurious pause proposals.
"""
from __future__ import annotations

from services.bot_brain.rules import (
    PAUSE_ALLOWED_TIERS, MIN_PRICE_MOVE_15M_PCT, MIN_LIQ_CLUSTER_QTY_BTC,
    r1_5_pre_cascade_short_pause, r2_5_pre_cascade_long_pause,
    r1_6_pre_cascade_short_HIGH, r1_cascade_short_pause, r2_cascade_long_pause,
    _pause_eligible,
)


# ─── Test fixtures (snapshot factories) ──────────────────────────────────────

def _bot(tier, side, **kw):
    return {"bot_id": f"id_{tier}", "tier": tier, "side": side,
            "paused_by_guard": kw.get("paused", False), **kw}


def _btc_market(*, price_change_15m=0.0, taker=50.0, funding=0.0,
                liq_cluster_short_qty=0.0, liq_cluster_long_qty=0.0,
                cascades_short=False, cascades_long=False):
    """Build a BTCUSDT market dict for snapshot fixture."""
    casc = []
    if cascades_short:
        casc.append({"type": "short_5.0", "ts": "t", "age_min": 5.0})
    if cascades_long:
        casc.append({"type": "long_5.0", "ts": "t", "age_min": 5.0})
    clusters = []
    if liq_cluster_short_qty > 0:
        clusters.append({"ts": "t", "side": "short",
                         "qty_btc": liq_cluster_short_qty, "age_min": 5.0})
    if liq_cluster_long_qty > 0:
        clusters.append({"ts": "t", "side": "long",
                         "qty_btc": liq_cluster_long_qty, "age_min": 5.0})
    return {
        "mid": 78000, "price_change_15m_pct": price_change_15m,
        "taker_buy_pct": taker, "funding_rate_8h": funding,
        "cascades_recent": casc, "liq_cluster_fires_recent": clusters,
        "tv_alerts_recent": [],
    }


def _snap(market, bots):
    return {"ts": "test", "market": {"BTCUSDT": market}, "bots": bots}


# ─── Per-tier filter ─────────────────────────────────────────────────────────

def test_pause_eligible_excludes_T2():
    bot = _bot("T2", "short")
    mkt = _btc_market(price_change_15m=+3.0)  # strong move
    eligible, reason = _pause_eligible(bot, mkt, expected_price_dir="up")
    assert not eligible
    assert "T2 excluded" in reason


def test_pause_eligible_excludes_T3():
    bot = _bot("T3", "short")
    mkt = _btc_market(price_change_15m=+3.0)
    eligible, _ = _pause_eligible(bot, mkt, expected_price_dir="up")
    assert not eligible


def test_pause_eligible_allows_T1():
    bot = _bot("T1", "short")
    mkt = _btc_market(price_change_15m=+3.0)
    eligible, _ = _pause_eligible(bot, mkt, expected_price_dir="up")
    assert eligible


def test_pause_eligible_allows_TB():
    bot = _bot("TB", "short", testbed=True)
    mkt = _btc_market(price_change_15m=+3.0)
    eligible, _ = _pause_eligible(bot, mkt, expected_price_dir="up")
    assert eligible


def test_pause_eligible_excludes_already_paused():
    bot = _bot("T1", "short", paused=True)
    mkt = _btc_market(price_change_15m=+3.0)
    eligible, reason = _pause_eligible(bot, mkt, expected_price_dir="up")
    assert not eligible
    assert "already paused" in reason


# ─── Price-movement gate ─────────────────────────────────────────────────────

def test_pause_eligible_rejects_micro_move_short():
    """SHORT pause requires BTC up ≥ 1.5% in 15m. Below = skip."""
    bot = _bot("T1", "short")
    mkt = _btc_market(price_change_15m=+0.3)
    eligible, reason = _pause_eligible(bot, mkt, expected_price_dir="up")
    assert not eligible
    assert "+0.30%" in reason


def test_pause_eligible_rejects_wrong_direction_short():
    """SHORT pause expects price UP. If price moved DOWN, skip."""
    bot = _bot("T1", "short")
    mkt = _btc_market(price_change_15m=-2.0)
    eligible, _ = _pause_eligible(bot, mkt, expected_price_dir="up")
    assert not eligible


def test_pause_eligible_accepts_strong_up_move():
    bot = _bot("T1", "short")
    mkt = _btc_market(price_change_15m=+1.8)
    eligible, _ = _pause_eligible(bot, mkt, expected_price_dir="up")
    assert eligible


def test_pause_eligible_skips_gate_when_require_strong_move_false():
    """Reactive cascade rules pass require_strong_move=False — cascade itself
    confirms move happened, no re-check needed."""
    bot = _bot("T1", "short")
    mkt = _btc_market(price_change_15m=+0.3)  # tiny move
    eligible, _ = _pause_eligible(bot, mkt, expected_price_dir="up",
                                    require_strong_move=False)
    assert eligible


# ─── liq-cluster qty minimum ─────────────────────────────────────────────────

def test_r1_5_rejects_small_cluster():
    """Cluster qty 0.8 BTC < 1.5 threshold → no proposal."""
    bot = _bot("T1", "short")
    mkt = _btc_market(liq_cluster_short_qty=0.8, price_change_15m=+2.0)
    proposals = r1_5_pre_cascade_short_pause(_snap(mkt, [bot]))
    assert proposals == []


def test_r1_5_accepts_strong_cluster_with_price_move():
    bot = _bot("T1", "short")
    mkt = _btc_market(liq_cluster_short_qty=2.0, price_change_15m=+2.0)
    proposals = r1_5_pre_cascade_short_pause(_snap(mkt, [bot]))
    assert len(proposals) == 1
    assert proposals[0].action == "pause"
    assert proposals[0].tier == "T1"


def test_r1_5_blocks_T2_even_with_strong_signals():
    """Critical operator policy: T2 never paused regardless of signal."""
    bot = _bot("T2", "short")
    mkt = _btc_market(liq_cluster_short_qty=3.0, price_change_15m=+3.0)
    proposals = r1_5_pre_cascade_short_pause(_snap(mkt, [bot]))
    assert proposals == []


def test_r1_5_no_proposal_on_micro_move():
    """Strong cluster + tiny move → skip (operator: 0.3% movement shouldn't fire)."""
    bot = _bot("T1", "short")
    mkt = _btc_market(liq_cluster_short_qty=2.0, price_change_15m=+0.3)
    proposals = r1_5_pre_cascade_short_pause(_snap(mkt, [bot]))
    assert proposals == []


def test_r1_6_requires_all_three_gates():
    """R1.6: cluster + taker<42 + strong price move. Each gate independently fails."""
    bot = _bot("T1", "short")
    # All gates pass
    mkt_pass = _btc_market(liq_cluster_short_qty=2.0, taker=40.0, price_change_15m=+2.0)
    assert len(r1_6_pre_cascade_short_HIGH(_snap(mkt_pass, [bot]))) == 1
    # Cluster too small
    mkt_small_cluster = _btc_market(liq_cluster_short_qty=0.5, taker=40.0, price_change_15m=+2.0)
    assert r1_6_pre_cascade_short_HIGH(_snap(mkt_small_cluster, [bot])) == []
    # Taker not below 42
    mkt_taker = _btc_market(liq_cluster_short_qty=2.0, taker=55.0, price_change_15m=+2.0)
    assert r1_6_pre_cascade_short_HIGH(_snap(mkt_taker, [bot])) == []
    # Price move too small
    mkt_micro = _btc_market(liq_cluster_short_qty=2.0, taker=40.0, price_change_15m=+0.4)
    assert r1_6_pre_cascade_short_HIGH(_snap(mkt_micro, [bot])) == []


# ─── Reactive cascade rules (R1, R2) — gate only on tier ─────────────────────

def test_r1_cascade_short_skips_T2():
    bot = _bot("T2", "short")
    mkt = _btc_market(cascades_short=True, price_change_15m=+0.2)
    proposals = r1_cascade_short_pause(_snap(mkt, [bot]))
    assert proposals == []


def test_r1_cascade_short_fires_for_T1_even_micro_move():
    """Reactive rule: cascade ALREADY fired = confirmed event, no price re-check."""
    bot = _bot("T1", "short")
    mkt = _btc_market(cascades_short=True, price_change_15m=+0.2)
    proposals = r1_cascade_short_pause(_snap(mkt, [bot]))
    assert len(proposals) == 1


def test_r2_cascade_long_skips_already_paused():
    """Paused bot not re-proposed."""
    bot = _bot("LONG-D", "long", paused=True)
    mkt = _btc_market(cascades_long=True)
    proposals = r2_cascade_long_pause(_snap(mkt, [bot]))
    assert proposals == []


# ─── Sanity: PAUSE_ALLOWED_TIERS matches operator directive ──────────────────

def test_pause_allowed_tiers_excludes_T2_T3():
    """Spec lock: T2/T3 must remain in the no-auto-pause set."""
    assert "T2" not in PAUSE_ALLOWED_TIERS
    assert "T3" not in PAUSE_ALLOWED_TIERS
    assert "T1" in PAUSE_ALLOWED_TIERS
    assert "TB" in PAUSE_ALLOWED_TIERS


def test_thresholds_match_operator_policy():
    """Operator: pause on truly strong moves, not 1% micro-spikes.
    MIN_PRICE_MOVE_15M_PCT ≥ 1.0 (we use 1.5)."""
    assert MIN_PRICE_MOVE_15M_PCT >= 1.0
    assert MIN_LIQ_CLUSTER_QTY_BTC >= 1.0  # raised from 0.5 baseline
