"""Режим-условный гейт валид-эджей + actionable-карточка «ОТКРОЙ СЕЙЧАС».
2026-06-21: оператор «вижу только жди/закрывай» — эджи резались conf-70."""
from __future__ import annotations

from services.setup_detector.edge_stats import (
    edge_for, is_countertrend, direction_of, armed_setups_for_regime, MIN_REGIME_PF)
from services.setup_detector.models import SetupType, SetupBasis, make_setup
from services.setup_detector.telegram_card import format_actionable_card


def test_rally_fade_armed_in_range_wide():
    e = edge_for("short_rally_fade", "range_wide")
    assert e is not None and e["regime_pf"] > 5 and e["regime_known"]


def test_rally_fade_silent_in_range_tight():
    # PF 0.6 ≤ 1.2 → молчим (именно тут он теряет)
    assert edge_for("short_rally_fade", "range_tight") is None


def test_rally_fade_silent_in_unknown_regime():
    # нет ARMED-cell (trend_down) → не угадываем
    assert edge_for("short_rally_fade", "trend_down") is None


def test_pdl_bounce_armed_in_trend_down():
    e = edge_for("long_pdl_bounce", "trend_down")
    assert e is not None and e["regime_pf"] > MIN_REGIME_PF


def test_div_bos_always_armed():
    e = edge_for("long_div_bos_15m", "whatever_regime")
    assert e is not None and e["regime_known"] is False


def test_double_top_armed_in_niche_only():
    # «не убивать»: ВСЕГО PF 0.73, но range_wide ARMED, trend_down dead
    assert edge_for("short_double_top", "range_wide") is not None
    assert edge_for("short_double_top", "trend_down") is None


def test_pdh_rejection_armed_in_trend_up_only():
    assert edge_for("short_pdh_rejection", "trend_up") is not None
    assert edge_for("short_pdh_rejection", "range_wide") is None


def test_truly_dead_type_returns_none_everywhere():
    # multi_divergence / short_div_bos_15m — нет ни одной ARMED-ниши
    assert edge_for("long_multi_divergence", "range_wide") is None
    assert edge_for("short_div_bos_15m", "trend_down") is None


def test_armed_setups_for_regime_lists_niches():
    armed = armed_setups_for_regime("range_wide")
    types = {t for t, _ in armed}
    assert "short_rally_fade" in types and "long_pdl_bounce" in types
    assert "short_double_top" in types          # ниша флэта
    assert "short_div_bos_15m" not in types     # мёртвый везде
    # отсортировано по убыванию regime_pf
    pfs = [e["regime_pf"] for _, e in armed]
    assert pfs == sorted(pfs, reverse=True)


def test_countertrend_flags():
    assert is_countertrend("long_pdl_bounce", "MARKDOWN") is True   # лонг в даунтренде
    assert is_countertrend("short_rally_fade", "MARKDOWN") is False
    assert is_countertrend("short_rally_fade", "MARKUP") is True
    assert direction_of("short_rally_fade") == "SHORT"


def _mk(stype: str, regime: str):
    return make_setup(
        setup_type=SetupType(stype), pair="BTCUSDT", current_price=64800.0,
        regime_label=regime, session_label="EU",
        entry_price=64820.0, stop_price=65400.0, tp1_price=63900.0, tp2_price=63200.0,
        risk_reward=1.96, strength=7, confidence_pct=64.0,
        basis=(SetupBasis(label="rally into PDH", value=1.0, weight=1.0),),
        cancel_conditions=("закрытие выше 65,400",), recommended_size_btc=0.05)


def test_actionable_card_has_open_and_stats():
    s = _mk("short_rally_fade", "range_wide")
    e = edge_for("short_rally_fade", "range_wide")
    card = format_actionable_card(s, e, countertrend=False)
    assert "🎯 ОТКРОЙ" in card and "SHORT" in card
    assert "ВХОД" in card and "СТОП" in card and "TP1" in card
    assert "PF(режим range_wide) 7.3" in card
    assert "КОНТРТРЕНД" not in card


def test_actionable_card_countertrend_flag():
    s = _mk("long_pdl_bounce", "trend_down")
    e = edge_for("long_pdl_bounce", "trend_down")
    card = format_actionable_card(s, e, countertrend=True)
    assert "⚠️ КОНТРТРЕНД" in card
