"""Tests for weak-conviction filter on 2BTC tier cascade alerts.

Bug operator reported 2026-05-19: 2.32 BTC OKX-only triggered full
"INVERTED SHORT setup" card with entry/stop/TP plan + half-size note. The
plan is -EV after fees (long_2btc inverted 4h DOWN 51.2%, mean inverted
+0.091%, -0.06% net after 0.15% taker RT). Should be suppressed entirely.
"""
from __future__ import annotations

from services.cascade_alert.loop import (
    INVERTED_PLAYS,
    THRESHOLD_BTC,
    THRESHOLD_BTC_MEDIUM,
    _is_weak_conviction,
)


def test_long_2btc_inverted_removed_minus_ev() -> None:
    """2BTC INVERTED plays убраны — после fees они -EV."""
    assert ("long", 2.0) not in INVERTED_PLAYS
    assert ("short", 2.0) not in INVERTED_PLAYS


def test_5btc_inverted_kept() -> None:
    """5BTC и mega tier INVERTED остаются — edge достаточный после fees."""
    assert ("long", 5.0) in INVERTED_PLAYS
    assert ("short", 5.0) in INVERTED_PLAYS
    assert ("long", 10.0) in INVERTED_PLAYS


def test_weak_2btc_single_exchange_suppressed() -> None:
    """Точный кейс который оператор показал: 2.32 BTC OKX-only → suppress."""
    suppress, reason = _is_weak_conviction(
        threshold=THRESHOLD_BTC_MEDIUM, qty=2.32,
        by_exchange={"okx": {"long": 2.32, "short": 0.0}},
    )
    assert suppress
    assert "qty 2.32/2.0" in reason or "single_exchange" in reason


def test_weak_2btc_high_qty_multi_exchange_not_suppressed() -> None:
    """2.8 BTC многоэкзовый (порог × 1.4) — не suppress."""
    suppress, _reason = _is_weak_conviction(
        threshold=THRESHOLD_BTC_MEDIUM, qty=2.8,
        by_exchange={"bybit": {"long": 1.5, "short": 0.0},
                      "okx": {"long": 1.3, "short": 0.0}},
    )
    assert not suppress


def test_weak_2btc_just_above_threshold_suppressed_even_multi() -> None:
    """2.25 BTC (×1.13 порога) — даже multi-exchange suppress."""
    suppress, reason = _is_weak_conviction(
        threshold=THRESHOLD_BTC_MEDIUM, qty=2.25,
        by_exchange={"bybit": {"long": 1.2, "short": 0.0},
                      "okx": {"long": 1.05, "short": 0.0}},
    )
    assert suppress
    assert "below ×1.3" in reason


def test_5btc_tier_single_exchange_always_fires() -> None:
    """5BTC tier даже single-exchange = fires (strong tier exempt)."""
    suppress, _ = _is_weak_conviction(
        threshold=THRESHOLD_BTC, qty=6.0,
        by_exchange={"okx": {"long": 6.0, "short": 0.0}},
    )
    assert not suppress


def test_mega_tier_single_exchange_fires() -> None:
    """Mega 10BTC даже single-exchange = fires (rare events worth attention)."""
    suppress, _ = _is_weak_conviction(
        threshold=10.0, qty=11.0,
        by_exchange={"okx": {"long": 0.0, "short": 11.0}},
    )
    assert not suppress
