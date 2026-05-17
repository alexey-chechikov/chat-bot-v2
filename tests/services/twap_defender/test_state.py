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
    # |pos| = 0.5 BTC × $80k = $40k < $50k threshold
    bot = _bot(pos_btc=-0.5)
    assert detect_bleed(bot, position_30min_ago_btc=-0.1, btc_mid=80_000) is None


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
    # Pos $51k now, $50.5k 30min ago → delta $500 < $1k min growth
    bot = _bot(pos_btc=-0.6375)  # 0.6375 × 80k ≈ 51k
    assert detect_bleed(bot, position_30min_ago_btc=-0.63, btc_mid=80_000) is None


def test_long_bot_position_is_usd_already():
    # LONG bots use linear XBTUSDT — position field is in USDT, NOT BTC.
    # pos=55000 USDT > $50k threshold; pos_30=45000 → delta $10k.
    bot = _bot(side="long", pos_btc=55_000)
    alert = detect_bleed(bot, position_30min_ago_btc=45_000, btc_mid=80_000)
    assert alert is not None
    assert alert["suggested_side"] == "sell"  # opposite of LONG
    assert alert["position_usd_abs"] == 55_000  # NOT 55000 × 80000
    assert alert["delta_30min_usd"] == 10_000


def test_long_bot_below_threshold_in_usd():
    # LONG pos 27200 USDT < $50k threshold → no alert
    bot = _bot(side="long", pos_btc=27_200)
    assert detect_bleed(bot, position_30min_ago_btc=20_000, btc_mid=80_000) is None


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
    assert BLEED_THRESHOLD_USD == 50_000.0
    assert MIN_GROWTH_30MIN_USD == 1_000.0
