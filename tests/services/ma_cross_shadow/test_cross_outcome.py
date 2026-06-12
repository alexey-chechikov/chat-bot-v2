"""cross-to-cross outcome (ревью Вина): новый кросс закрывает прошлый сигнал
полем outcome_cross = удержание до обратного кросса, с комиссией."""
from __future__ import annotations

from services.ma_cross_shadow.tracker import _close_prev_cross, FEE_PCT


def test_close_prev_long_profit():
    recs = [{"symbol": "BTCUSDT", "dir": "LONG", "entry": 100.0, "outcomes": {}}]
    _close_prev_cross(recs, "BTCUSDT", 110.0)  # вырос 100→110 при LONG
    assert recs[0]["outcome_cross"] == round(10.0 - FEE_PCT, 3)  # +10% − fee


def test_close_prev_short_profit():
    recs = [{"symbol": "BTCUSDT", "dir": "SHORT", "entry": 100.0, "outcomes": {}}]
    _close_prev_cross(recs, "BTCUSDT", 90.0)   # упал 100→90 при SHORT = профит
    assert recs[0]["outcome_cross"] == round(10.0 - FEE_PCT, 3)


def test_close_prev_only_latest_open_same_symbol():
    recs = [
        {"symbol": "BTCUSDT", "dir": "LONG", "entry": 100.0, "outcome_cross": 5.0},  # уже закрыт
        {"symbol": "SOLUSDT", "dir": "LONG", "entry": 60.0, "outcomes": {}},          # другой символ
        {"symbol": "BTCUSDT", "dir": "SHORT", "entry": 120.0, "outcomes": {}},        # последний открытый BTC
    ]
    _close_prev_cross(recs, "BTCUSDT", 108.0)
    assert recs[0]["outcome_cross"] == 5.0            # не тронут
    assert "outcome_cross" not in recs[1]             # SOL не тронут
    # SHORT 120→108 = +10% − fee
    assert recs[2]["outcome_cross"] == round(10.0 - FEE_PCT, 3)


def test_no_open_signal_noop():
    recs = [{"symbol": "BTCUSDT", "dir": "LONG", "entry": 100.0, "outcome_cross": 1.0}]
    _close_prev_cross(recs, "BTCUSDT", 110.0)
    assert recs[0]["outcome_cross"] == 1.0  # уже закрыт — не перезаписываем
