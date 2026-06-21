"""Guard от ложного «ликвидация близко».
2026-06-20: XRP орал «ликвидация −100% — близко» (liquidation_price≈0 у
флэт-грида → отрицательная дистанция), guard liq_d<15 ловил любое отрицательное."""
from __future__ import annotations

from services.morning_brief.card import _liq_dist_pct, _near_liq, LIQ_WARN_PCT


def test_zero_liq_price_returns_none():
    # liquidation_price = 0 → None (а не -100%)
    assert _liq_dist_pct("short", 0.65, 0) is None
    assert _liq_dist_pct("long", 0.65, None) is None


def test_tiny_liq_gives_negative_distance_not_warned():
    # liq≈0.001 при px 0.65 → ~-99.8% → НЕ предупреждение
    d = _liq_dist_pct("short", 0.65, 0.001)
    assert d < -99
    assert _near_liq(d) is False


def test_negative_distance_never_warns():
    assert _near_liq(-100.0) is False
    assert _near_liq(-1.0) is False


def test_real_close_distance_warns():
    assert _near_liq(5.0) is True
    assert _near_liq(0.0) is True
    assert _near_liq(LIQ_WARN_PCT - 0.1) is True


def test_far_distance_not_warned():
    assert _near_liq(60.0) is False
    assert _near_liq(LIQ_WARN_PCT) is False  # ровно на пороге — не алерт
    assert _near_liq(None) is False
