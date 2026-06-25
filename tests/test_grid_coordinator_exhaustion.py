"""Bottom-exhaustion detector (ревью Вина 25.06): на экстреме инвертировать
«86% вниз» → «падение выдыхается». Сценарий дна 59 438 (RSI 14, MFI 9)."""
from __future__ import annotations

from datetime import datetime, timezone

from services.grid_coordinator import loop as gc


def _details(rsi, mfi, oi, funding, px=59438.0):
    return {"rsi_btc_now": rsi, "mfi_btc_now": mfi, "oi_change_1h_pct": oi,
            "funding_rate_8h": funding, "btc_close": px}


def test_fires_at_capitulation_bottom(monkeypatch):
    # сценарий дна Вина: RSI 14, MFI 9, OI -3.43%, funding -0.0076%, кластер свипов
    monkeypatch.setattr(gc, "_recent_long_liq_btc", lambda now: 99.0)
    bx = gc.evaluate_bottom_exhaustion(
        _details(14.2, 9.1, -3.43, -0.000076), datetime.now(timezone.utc))
    assert bx["fired"] is True and bx["confirms"] == 3
    assert bx["deleverage"] and bx["squeeze"] and bx["sweep"]


def test_not_fired_if_not_extreme(monkeypatch):
    # RSI 30 — перепродан, но не экстрим → не наш кейс
    monkeypatch.setattr(gc, "_recent_long_liq_btc", lambda now: 99.0)
    bx = gc.evaluate_bottom_exhaustion(
        _details(30.0, 25.0, -3.43, -0.000076), datetime.now(timezone.utc))
    assert bx["fired"] is False and bx.get("extreme") is False


def test_not_fired_extreme_but_one_confirm(monkeypatch):
    # экстрим, но только делеверидж (нет squeeze, нет sweep) → <2 → не fired
    monkeypatch.setattr(gc, "_recent_long_liq_btc", lambda now: 2.0)
    bx = gc.evaluate_bottom_exhaustion(
        _details(15.0, 10.0, -3.43, +0.00001), datetime.now(timezone.utc))
    assert bx["fired"] is False and bx["confirms"] == 1


def test_card_inverts_reading(monkeypatch):
    monkeypatch.setattr(gc, "_recent_long_liq_btc", lambda now: 99.0)
    bx = gc.evaluate_bottom_exhaustion(
        _details(14.2, 9.1, -3.43, -0.000076), datetime.now(timezone.utc))
    card = gc._format_exhaustion_card(bx)
    assert "ВЫДЫХАЕТСЯ" in card and "ОТСКОК" in card
    assert "funding-\nsqueeze LONG" in card or "funding-squeeze LONG" in card.replace("\n", "")
    assert "НЕ прогноз" in card and "ПОДТВЕРЖДЕНИЮ" in card
    assert "86%" not in card   # не должно быть старого continuation-заголовка
