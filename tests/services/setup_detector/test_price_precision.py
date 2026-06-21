"""Win-аудит 21.06: точность цен альтов в сетапах (XRP 1.14 не должен → 1.1)."""
from __future__ import annotations

from services.setup_detector.models import round_price, make_setup, SetupType, SetupBasis


def test_round_price_scales():
    assert round_price(64012.37) == 64012.4     # BTC — 1 знак
    assert round_price(3450.55) == 3450.6
    assert round_price(247.83) == 247.83        # сотни — 2 знака
    assert round_price(1.1474) == 1.1474        # XRP — 4 знака (был баг → 1.1)
    assert round_price(0.08123) == 0.08123
    assert round_price(None) is None


def test_xrp_setup_levels_distinct():
    s = make_setup(
        setup_type=SetupType("long_pdl_bounce"), pair="XRPUSDT", current_price=1.1474,
        regime_label="range_wide", session_label="EU",
        entry_price=1.1474, stop_price=1.0900, tp1_price=1.2100, tp2_price=1.2600,
        risk_reward=2.0, strength=6, confidence_pct=60.0,
        basis=(SetupBasis(label="x", value=1.0, weight=1.0),),
        cancel_conditions=("y",))
    # вход/стоп/тейки больше НЕ схлопываются в одно число
    assert len({s.entry_price, s.stop_price, s.tp1_price, s.tp2_price}) == 4
    assert s.stop_price == 1.09 and s.tp1_price == 1.21


def test_btc_setup_unaffected():
    s = make_setup(
        setup_type=SetupType("short_rally_fade"), pair="BTCUSDT", current_price=64000.0,
        regime_label="range_wide", session_label="EU",
        entry_price=64012.37, stop_price=64500.0, tp1_price=63500.0, tp2_price=63000.0,
        risk_reward=2.0, strength=6, confidence_pct=60.0,
        basis=(SetupBasis(label="x", value=1.0, weight=1.0),),
        cancel_conditions=("y",))
    assert s.entry_price == 64012.4 and s.stop_price == 64500.0
