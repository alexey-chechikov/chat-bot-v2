"""Tests for twap_defender.state detector."""
from __future__ import annotations

from services.twap_defender.state import (
    BLEED_THRESHOLD_USD,
    MIN_GROWTH_30MIN_USD,
    detect_bleed,
    format_tg_card,
)


def _bot(side="short", pos_btc=-0.7):
    return {"bot_id": "999", "alias": "T1", "tier": "T1",
            "side": side, "position_btc": pos_btc}


def test_below_threshold_no_alert():
    # |pos| = 0.05 BTC × $80k = $4k < $10k threshold
    bot = _bot(pos_btc=-0.05)
    assert detect_bleed(bot, position_30min_ago_btc=-0.01, btc_mid=80_000) is None


def test_growing_above_threshold_short():
    # |pos| now = 0.7 × $80k = $56k > $50k.
    # 30min ago: 0.5 × $80k = $40k. Δ = $16k > $1k min.
    bot = _bot(pos_btc=-0.7)
    alert = detect_bleed(bot, position_30min_ago_btc=-0.5, btc_mid=80_000)
    assert alert is not None
    assert alert["suggested_side"] == "buy"  # opposite of SHORT
    assert alert["delta_30min_usd"] == 16_000
    assert alert["position_usd_abs"] == 56_000


def test_not_growing_no_alert():
    # Position stable: 0.7 BTC both then and now → delta = 0
    bot = _bot(pos_btc=-0.7)
    assert detect_bleed(bot, position_30min_ago_btc=-0.7, btc_mid=80_000) is None


def test_growth_under_min_threshold_no_alert():
    # Pos $11k now, $10.7k 30min ago → delta $300 < $500 min growth
    bot = _bot(pos_btc=-0.1375)  # 0.1375 × 80k = $11k
    assert detect_bleed(bot, position_30min_ago_btc=-0.1338, btc_mid=80_000) is None


def test_long_bots_filtered_out():
    """LONG-side фильтруется: TWAP defender работает ТОЛЬКО для SHORT.
    LONG-D/V5 нормально работают $25-35k, asymmetric bleed их не касается."""
    bot = _bot(side="long", pos_btc=55_000)
    alert = detect_bleed(bot, position_30min_ago_btc=20_000, btc_mid=80_000)
    assert alert is None  # SIDE FILTER — даже большая LONG позиция не триггерит


def test_no_history_skips():
    bot = _bot(pos_btc=-0.7)
    assert detect_bleed(bot, position_30min_ago_btc=None, btc_mid=80_000) is None


def test_format_tg_card_contains_key_fields():
    bot = _bot(pos_btc=-0.7)
    alert = detect_bleed(bot, position_30min_ago_btc=-0.5, btc_mid=80_000)
    text = format_tg_card(alert, step=3, max_steps=12)
    assert "TWAP DEFENDER" in text
    assert "step 3/12" in text
    assert "T1" in text
    assert "BUY" in text  # SHORT bot → BUY contra
    assert "$56,000" in text or "$56" in text


def test_thresholds_match_spec():
    assert BLEED_THRESHOLD_USD == 10_000.0
    assert MIN_GROWTH_30MIN_USD == 500.0
