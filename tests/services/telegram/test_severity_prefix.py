"""Tests for severity prefix classification."""
from __future__ import annotations

from services.telegram.severity_prefix import (
    CRITICAL, IMPORTANT, INFO, ROUTINE,
    classify_severity, with_prefix,
)


def test_mega_liquidation_is_critical_by_qty():
    sev = classify_severity("LIQ_CASCADE", "🌋 каскад", {"qty_btc": 13.5})
    assert sev == CRITICAL


def test_mega_liquidation_is_critical_by_title():
    sev = classify_severity("LIQ_CASCADE", "🌋 МЕГА-СПАЙК LONG-ликвидаций", None)
    assert sev == CRITICAL


def test_regular_cascade_is_important():
    sev = classify_severity("LIQ_CASCADE", "⚡ Каскад LONG (2 BTC)", {"qty_btc": 3.0})
    assert sev == IMPORTANT


def test_grid_exhaustion_critical_at_4_signals():
    sev = classify_severity("GRID_EXHAUSTION", "🔝 ВЕРХ — ИМПУЛЬС ВВЕРХ (4/6)", {"signals_count": 4})
    assert sev == CRITICAL


def test_grid_exhaustion_only_important_at_3_signals():
    sev = classify_severity("GRID_EXHAUSTION", "🔝 ВЕРХ — ИМПУЛЬС ВВЕРХ (3/6)", {"signals_count": 3})
    assert sev == IMPORTANT


def test_high_confidence_setup_is_critical():
    sev = classify_severity("SETUP_ON", "🟢 LONG", {"confidence": 85})
    assert sev == CRITICAL


def test_normal_setup_is_important():
    sev = classify_severity("SETUP_ON", "🟢 LONG", {"confidence": 70})
    assert sev == IMPORTANT


def test_p15_open_is_info():
    sev = classify_severity("P15_OPEN", "🎯 P-15 LONG OPEN", None)
    assert sev == INFO


def test_p15_reentry_is_routine():
    sev = classify_severity("P15_REENTRY", "🔄 P-15 LONG REENTRY", None)
    assert sev == ROUTINE


def test_level_break_is_routine():
    sev = classify_severity("LEVEL_BREAK", "🎯 LEVEL_BREAK level=80000", None)
    assert sev == ROUTINE


def test_margin_alert_always_critical():
    sev = classify_severity("MARGIN_ALERT", "", None)
    assert sev == CRITICAL


def test_with_prefix_adds_emoji():
    out = with_prefix(CRITICAL, "ALERT")
    assert out.startswith("🔴")
    assert "ALERT" in out


def test_with_prefix_is_idempotent():
    once = with_prefix(IMPORTANT, "hello")
    twice = with_prefix(IMPORTANT, once)
    assert once == twice


def test_unknown_emitter_defaults_to_important():
    sev = classify_severity("UNKNOWN_EMITTER_FOO", "test", None)
    assert sev == IMPORTANT
