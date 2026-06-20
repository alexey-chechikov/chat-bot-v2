"""Launch-чеклист альт-кандидата: кап ноги-против-тренда + SL + не-резюм по режиму."""
from __future__ import annotations

from services.morning_brief.card import _launch_checklist


def test_markdown_caps_long_leg():
    out = "\n".join(_launch_checklist(18, "MARKDOWN", good_hour=True))
    assert "MARKDOWN" in out and "ЛОНГ-нога капнута" in out
    assert "maxOpL = 6" in out and "maxOpS = 18" in out   # 18//3=6
    assert "tsl = −175 ОБЯЗАТЕЛЬНО" in out
    assert "НЕ резюмировать" in out


def test_markup_caps_short_leg():
    out = "\n".join(_launch_checklist(18, "MARKUP", good_hour=True))
    assert "MARKUP" in out and "ШОРТ-нога капнута" in out
    assert "maxOpL = 18" in out and "maxOpS = 6" in out
    assert "урок SOL" in out


def test_range_symmetric_ok():
    out = "\n".join(_launch_checklist(18, "RANGE", good_hour=True))
    assert "RANGE → симметрично можно" in out
    assert "maxOpL = maxOpS = 18" in out


def test_unknown_regime_caps_both():
    out = "\n".join(_launch_checklist(18, None, good_hour=True))
    assert "режим неясен" in out
    assert "кап обе ноги до 6" in out


def test_bad_hour_warned():
    out = "\n".join(_launch_checklist(18, "RANGE", good_hour=False))
    assert "плохой час" in out and "16–20 мск" in out


def test_min_cap_floor():
    # маленький ordcnt → кап не ниже 3
    out = "\n".join(_launch_checklist(6, "MARKDOWN", good_hour=True))
    assert "maxOpL = 3" in out  # max(3, 6//3=2) = 3
