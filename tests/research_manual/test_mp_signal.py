"""Протокол §Сигнал п.2–5: касание EMA20 только в 15m-свечах №4…16, low ≤ EMA ≤ high, отмены (close за low 4h-пробоя,
новый low < low_p до подтверждения) и их приоритет, подтверждение «close выше high двух предыдущих» за ≤3 свечи и не
позже №16, вход по open следующей свечи с дрейфом ≤ 0.1A, стоп low_p − 0.1A и ширина [0.7%; 2.0%], цель 2R."""
import math

import pytest

from tests.research_manual.mp_fx import NOSLIP, drive, rp, sym15

ABOVE = (101.0, 101.5, 100.5, 101.0)        # целиком выше EMA=100 — касания нет


def _p(side=1, lo4=95.0, hi4=105.0):
    return rp.Pending("e", "ETHUSDT", side, rp.START, 0, lo4, hi4)


def test_touch_only_in_bars_4_to_16():
    bars = [ABOVE, ABOVE, (101.0, 101.5, 99.5, 101.0),      # №3 касается — не считается
            (101.0, 101.0, 99.8, 100.8),                    # №4 касается — первое допустимое касание
            (100.8, 101.6, 100.5, 101.55)]                  # №5: close > high №4 и №3 → подтверждение
    s, p = sym15(bars), _p()
    j, r = drive(p, s)
    assert (j, r) == (4, "confirm")
    assert p.touch == 4 and p.ext == 99.5 and p.A == 0.5    # low_p — от №1 до касания включительно


def test_no_touch_by_bar_16_expires():
    s, p = sym15([ABOVE] * 20), _p()
    assert drive(p, s) == (15, "expire_touch")


def test_ema_touch_is_inclusive_range_check():
    s = sym15([ABOVE, ABOVE, ABOVE, (100.5, 101.0, 100.01, 100.6)] + [ABOVE] * 13)
    p = _p()
    for j in range(4):
        assert rp.step(p, s, j) is None
    assert p.touch == 0                                     # low 100.01 > EMA 100 — не касание
    s = sym15([ABOVE, ABOVE, ABOVE, (100.5, 101.0, 100.0, 100.6)] + [ABOVE] * 13)
    p = _p()
    for j in range(4):
        rp.step(p, s, j)
    assert p.touch == 4                                     # low == EMA — касание
    below = (99.5, 99.99, 99.0, 99.5)                       # high < EMA (для LONG — не касание)
    s = sym15([ABOVE, ABOVE, ABOVE, below] + [ABOVE] * 13, atr=0.5)
    p = _p(lo4=90.0)
    for j in range(4):
        rp.step(p, s, j)
    assert p.touch == 0


def test_close_below_breakout_low_cancels_even_before_touch():
    s, p = sym15([ABOVE, (100.0, 100.5, 94.0, 94.9)] + [ABOVE] * 14), _p(lo4=95.0)
    assert drive(p, s) == (1, "cancel_close_beyond_4h")


def test_new_low_below_low_p_cancels_even_on_confirming_bar():
    bars = [ABOVE, ABOVE, ABOVE, (101.0, 101.0, 99.8, 100.8),
            (100.8, 102.0, 99.7, 101.8)]                    # close > двух high, но low < low_p=99.8
    assert drive(_p(), sym15(bars)) == (4, "cancel_new_extreme")


def test_cancel_priority_close_beyond_4h_first():
    bars = [ABOVE, ABOVE, ABOVE, (101.0, 101.0, 99.8, 100.8), (100.8, 100.9, 94.0, 94.5)]
    assert drive(_p(lo4=95.0), sym15(bars)) == (4, "cancel_close_beyond_4h")


def test_confirmation_needs_close_above_highs_of_two_previous():
    bars = [ABOVE, ABOVE, (101.0, 102.0, 100.5, 101.0),     # №3 high 102
            (101.0, 101.0, 99.8, 100.8),                    # №4 касание, high 101
            (100.8, 101.6, 100.0, 101.5),                   # №5: > high №4 (101), но ≤ high №3 (102) — нет
            (101.5, 101.8, 100.9, 101.7)]                   # №6: > high №5 (101.6) и №4 (101) — да
    s, p = sym15(bars), _p()
    assert drive(p, s) == (5, "confirm")


def test_confirmation_window_three_bars_and_bar_16_limit():
    bars = [ABOVE, ABOVE, ABOVE, (101.0, 101.0, 99.8, 100.8)] + [(100.8, 101.0, 100.0, 100.9)] * 5
    assert drive(_p(), sym15(bars)) == (6, "expire_confirm")          # №5, №6, №7 без подтверждения
    late = [ABOVE] * 14 + [(101.0, 101.0, 99.8, 100.8), (100.8, 101.0, 100.0, 100.9), (101, 103, 100.5, 102.5)]
    assert drive(_p(), sym15(late)) == (15, "expire_confirm")         # касание №15, №16 без подтверждения — срок
    last = [ABOVE] * 15 + [(101.0, 101.0, 99.8, 100.8), (101, 103, 100.5, 102.5)]
    assert drive(_p(), sym15(last)) == (15, "expire_confirm")         # касание №16 — подтверждать некогда


def test_short_mirror_touch_and_confirm():
    BELOW = (99.0, 99.5, 98.5, 99.0)
    bars = [BELOW, BELOW, BELOW, (99.0, 100.2, 99.0, 99.2),  # №4 касание сверху, high_p = 100.2
            (99.2, 99.3, 98.0, 98.4)]                       # close < low №4 (99.0) и №3 (98.5)
    p = _p(side=-1, lo4=95.0, hi4=105.0)
    assert drive(p, sym15(bars)) == (4, "confirm")
    assert p.ext == 100.2


def _drift_sym(next_open):
    bars = [ABOVE, ABOVE, ABOVE, (101.0, 101.0, 99.8, 100.8), (100.8, 101.6, 100.5, 101.55),
            (next_open, next_open + 0.2, next_open - 0.2, next_open)]
    return sym15(bars, atr=0.5)


def test_entry_drift_limit_0_1_A():
    s, p = _drift_sym(101.59), _p()
    assert drive(p, s) == (4, "confirm")
    o = rp.order_from_confirm(p, s, 4, NOSLIP)
    assert isinstance(o, dict) and o["raw"] == 101.59 and o["t"] == rp.START + 5 * rp.M15   # open свечи №6
    assert math.isclose(o["S"], 99.8 - 0.05) and math.isclose(o["TP"], 101.59 + 2 * (101.59 - 99.75))
    s, p = _drift_sym(101.61), _p()
    drive(p, s)
    assert rp.order_from_confirm(p, s, 4, NOSLIP) == "cancel_drift"                   # 0.06 > 0.1 × 0.5
    s, p = _drift_sym(101.49), _p()
    drive(p, s)
    assert rp.order_from_confirm(p, s, 4, NOSLIP) == "cancel_drift"                   # и вниз: 0.06 > 0.05


@pytest.mark.parametrize("S,ok", [(99.31, False), (99.3, True), (98.0, True), (97.99, False)])
def test_stop_width_gate_long(S, ok):
    s = sym15([ABOVE] * 2)
    o = rp.make_order(s, 0, 1, 100.0, S, NOSLIP)
    assert isinstance(o, dict) is ok
    if ok:
        assert math.isclose(o["TP"], 100 + 2 * (100 - S))


def test_stop_width_uses_slipped_entry_and_short_mirror():
    s = sym15([ABOVE] * 2)
    o = rp.make_order(s, 0, -1, 100.0, 100.7, NOSLIP)
    assert isinstance(o, dict) and math.isclose(o["TP"], 100 - 1.4)
    o = rp.make_order(s, 0, 1, 100.0, 99.3, rp.BASE)                  # E = 100.02 → ширина 0.72%
    assert math.isclose(o["E"], 100.02) and math.isclose(o["w"], (100.02 - 99.3) / 100.02)
