"""Сторож: РАБОТАЕТ / ПЛАТО / ЗАТЯЖНОЕ ПЛАТО / РЕЗКИЙ НАБОР."""
from __future__ import annotations

import pytest

from services.bot_watch.loop import (HOUR, LONG_PLATEAU, PLATEAU, SHARP,
                                     WORKING, bag_usd, card, classify,
                                     flat_limit, growth4, notional_usd,
                                     plateau_hours, should_alert, value_at)

CFG = {"min_history_hours": 72, "flat_share": 0.10, "plateau_hours": 24,
       "long_plateau_hours": 96, "fast_min_mult": 3.0}


def working_history(hours=24 * 10, pos=0.3):
    """Бот работает: 6 часов в позиции, 6 часов в нуле."""
    return [[k * HOUR, pos if (k // 6) % 2 else 0.0, -1.0] for k in range(hours)]


def test_value_at_picks_last_not_after():
    s = [[0.0, 1, 0], [HOUR, 2, 0], [2 * HOUR, 3, 0]]
    assert value_at(s, 1.5 * HOUR)[1] == 2
    assert value_at(s, -1) is None


def test_flat_limit_needs_history_and_scales_with_bot():
    assert flat_limit(working_history(hours=24), CFG) is None
    lim = flat_limit(working_history(pos=0.3), CFG)
    assert lim == pytest.approx(0.03)


def test_small_position_of_mostly_flat_bot_is_not_an_alarm():
    """17.09: 0.214 ETH у бота, который часто стоит в нуле, сторож назвал
    «×3.6 от обычной». По плато это просто работа: позиция недавно была в нуле."""
    s = working_history(pos=0.5)
    s.append([s[-1][0] + HOUR, 0.214, -4.6])
    lim = flat_limit(s, CFG)
    ph, exact = plateau_hours(s, lim)
    assert exact and ph < 24
    g4 = growth4(s, len(s) - 1, lim)
    assert classify(ph, g4, 99.0, True, CFG) == WORKING


def test_plateau_counts_hours_since_last_flat():
    s = working_history(hours=234)             # последний сэмпл — в нуле
    t0 = s[-1][0]
    for k in range(1, 101):                    # 100 часов без возврата к нулю
        s.append([t0 + k * HOUR, 0.3, -5.0 - k])
    lim = flat_limit(s, CFG)
    ph, exact = plateau_hours(s, lim)
    assert exact and ph == pytest.approx(100, abs=1)
    assert classify(ph, 1.0, 99.0, True, CFG) == LONG_PLATEAU
    assert classify(30.0, 1.0, 99.0, True, CFG) == PLATEAU


def test_plateau_without_flat_in_history_is_lower_bound():
    s = [[k * HOUR, 0.3, -1.0] for k in range(200)]
    ph, exact = plateau_hours(s, 0.03)
    assert not exact and ph == pytest.approx(199)


def test_sharp_on_fast_growth():
    s = working_history()
    t0 = s[-1][0]
    s.append([t0 + HOUR, 0.3, -1.0])
    s.append([t0 + 5 * HOUR, 3.0, -30.0])      # ×10 за 4 часа
    lim = flat_limit(s, CFG)
    g4 = growth4(s, len(s) - 1, lim)
    assert g4 > 3
    assert classify(5.0, g4, 3.0, True, CFG) == SHARP


def test_alert_once_per_window_and_cooldown():
    now = 500 * HOUR
    assert should_alert(PLATEAU, LONG_PLATEAU, None, now, 6)
    assert not should_alert(LONG_PLATEAU, LONG_PLATEAU, None, now, 6,
                            window_alerted=True)
    assert not should_alert(WORKING, PLATEAU, None, now, 6)
    assert not should_alert(SHARP, LONG_PLATEAU, None, now, 6,
                            window_alerted=True)       # окно уже сообщено
    assert should_alert(PLATEAU, SHARP, None, now, 6)
    assert not should_alert(SHARP, SHARP, None, now, 6)
    assert not should_alert(WORKING, SHARP, now - 2 * HOUR, now, 6)


def test_long_plateau_not_lost_behind_cooldown():
    """Вход в затяжное плато в паузе — тревога уходит после паузы."""
    now = 500 * HOUR
    assert not should_alert(PLATEAU, LONG_PLATEAU, now - 2 * HOUR, now, 6)
    assert should_alert(LONG_PLATEAU, LONG_PLATEAU, now - 7 * HOUR, now, 6)


def test_units_inverse_and_linear():
    assert bag_usd(-0.0012, balance=-0.0007, avg_price=79484) == \
        pytest.approx(-95.38, abs=0.01)
    assert bag_usd(-24.3, balance=412.0, avg_price=4500) == -24.3
    assert notional_usd(2200.0, balance=-0.0007, avg_price=79484) == 2200.0
    assert notional_usd(0.214, balance=2576.0, avg_price=2300) == \
        pytest.approx(492.2)


def test_card_long_plateau_in_dollars():
    text = card("LONG COIN", LONG_PLATEAU, 24 * 14.2, True, 1.0, 3.0,
                2200.0, -95.4, 2160.92)
    assert "ЗАТЯЖНОЕ ПЛАТО · LONG COIN" in text
    assert "14.2 сут" in text
    assert "$-95" in text and "4.4% депозита" in text and "-4.3% позиции" in text
    assert "-0.00" not in text
