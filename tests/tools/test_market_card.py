"""Ядро вывода market_card: связка OI×тейкеры и названия ситуаций.

Оператор 2026-07-22: «пусть бот сделает вывод по баллам из факторов,
а не просто приведёт статистику».
"""
from __future__ import annotations

from tools.market_card import score_fuel, score_structure, verdict

RNG = {"hi": 66546.0, "lo": 64173.0, "height": 2373.0,
       "inside_frac": 0.89, "valid": True, "bars": 72}


def test_new_longs_score_positive():
    pts, why = score_fuel(0.5, oi=0.8, taker=1.5, vol_ratio=1.4, funding_pct=0.0)
    assert pts >= 3
    assert "НОВЫЕ ЛОНГИ" in " ".join(why)


def test_short_covering_scores_negative():
    """Покупки при падающем OI — вынос шортов, а не спрос."""
    pts, why = score_fuel(0.4, oi=-0.56, taker=2.5, vol_ratio=1.5, funding_pct=0.0)
    assert pts < 0
    assert "ЗАКРЫТИЕ ШОРТОВ" in " ".join(why)


def test_volume_modifier_cannot_flip_conclusion():
    """Главный дефект 2026-07-22: объём и тейкеры гасили сигнал OI.
    Модификатор больше не переворачивает знак."""
    strong_vol, _ = score_fuel(0.4, oi=-0.6, taker=2.5, vol_ratio=3.0,
                               funding_pct=0.0)
    assert strong_vol < 0            # даже при огромном объёме это вынос
    weak_vol, _ = score_fuel(0.4, oi=0.8, taker=1.5, vol_ratio=0.2,
                             funding_pct=0.0)
    assert weak_vol > 0              # и наоборот


def test_long_liquidation_scores_negative():
    pts, why = score_fuel(-0.5, oi=-0.7, taker=0.6, vol_ratio=1.0, funding_pct=0.0)
    assert pts < 0
    assert "РАЗГРУЖАЮТ" in " ".join(why)


def test_no_flow_is_zero():
    pts, _ = score_fuel(0.0, oi=0.05, taker=1.0, vol_ratio=1.0, funding_pct=0.0)
    assert pts == 0


def test_verdict_squeeze_into_top():
    name, meaning, invalid = verdict(-2, 0, RNG, px=66200.0, px_chg_1h=0.4)
    assert "ВЫНОСЕ" in name
    assert "граница скорее удержит" in meaning
    assert "66,546" in invalid          # отмена = конкретный уровень


def test_verdict_paid_breakout():
    name, meaning, invalid = verdict(3, 2, RNG, px=66900.0, px_chg_1h=1.0)
    assert "ОПЛАЧЕН" in name and "продолжение" in meaning
    assert "66,546" in invalid


def test_verdict_false_breakout():
    name, meaning, _ = verdict(-3, 2, RNG, px=66900.0, px_chg_1h=1.0)
    assert "ЛОЖНЫЙ" in name
    assert "возвращаются" in meaning


def test_verdict_dead_range_is_grid_friendly():
    name, meaning, _ = verdict(0, 0, RNG, px=65300.0, px_chg_1h=0.0)
    assert "ДЕНЕГ НЕТ" in name
    assert "гридов" in meaning


def test_structure_counts_liquidation_asymmetry():
    liq = [{"lo": 66000, "hi": 66500, "qty": 30.0, "long": 27.0, "short": 3.0}]
    pts, why = score_structure(66200.0, RNG, liq, g_ls=1.19, t_ls=1.55)
    assert pts < 0
    assert "ЛОНГИ" in " ".join(why)
