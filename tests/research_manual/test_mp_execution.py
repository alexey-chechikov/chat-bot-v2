"""Протокол §Исполнение и риск: цель-мейкер только при high ≥ TP + тик, стоп раньше цели в одной минуте, гэп через стоп —
по open минуты, выход по времени через 8 ч по open, фандинг LONG платит / SHORT получает qty×mark×rate по каждому
начислению entry < t ≤ exit, размер B / (|E − S*| + fee_in×E + fee_out×S*) вниз по шагу, minNotional 5. Один цикл
исполнения simulate() → exits() → settle()."""
import math

import numpy as np
import pytest

from tests.research_manual.mp_fx import (MIN, NOSLIP, START, drop_min, flat_minutes, funding_df, rp, set_min,
                                         sym_from_minutes)

I0 = 60
T0 = START + I0 * MIN


def _run(m, side=1, S=99.0, TP=102.0, i0=I0):
    s = sym_from_minutes(m)
    k, x, t = rp.exits(s, np.array([i0]), np.array([side]), np.array([S]), np.array([TP]), 480)
    return int(k[0]), float(x[0]), int(t[0])


def test_maker_tp_needs_high_at_least_tp_plus_tick():
    m = flat_minutes(2880)
    set_min(m, T0 + 5 * MIN, h=102.0)                  # ровно цель — лимит не исполнен
    set_min(m, T0 + 6 * MIN, h=102.01)                 # цель + тик ETH 0.01
    assert _run(m) == (rp.TP, 102.0, T0 + 6 * MIN + MIN - 1)


def test_short_maker_tp_needs_low_at_most_tp_minus_tick():
    m = flat_minutes(2880)
    set_min(m, T0 + 7 * MIN, l=98.0)
    set_min(m, T0 + 8 * MIN, l=97.99)
    assert _run(m, side=-1, S=101.0, TP=98.0) == (rp.TP, 98.0, T0 + 8 * MIN + MIN - 1)


def test_stop_first_when_stop_and_target_in_same_minute():
    m = flat_minutes(2880)
    set_min(m, T0 + 5 * MIN, l=98.9, h=102.5)
    assert _run(m) == (rp.SL, 99.0, T0 + 5 * MIN + MIN - 1)


def test_gap_through_stop_fills_at_minute_open_with_slippage():
    m = flat_minutes(2880)
    set_min(m, T0 + 5 * MIN, o=98.5, h=98.6, l=98.4, c=98.5)
    assert _run(m) == (rp.SL_GAP, 98.5, T0 + 5 * MIN)
    s = sym_from_minutes(m)
    st = rp.simulate(s, I0, 1, 100.0, 100.02, 99.0, 102.06, 7.5, rp.BASE)
    assert math.isclose(st["X"][0], 98.5 * (1 - 0.0002)) and st["R"][0] < -1


def test_short_gap_through_stop():
    m = flat_minutes(2880)
    set_min(m, T0 + 9 * MIN, o=101.5, h=101.6, l=101.4, c=101.5)
    assert _run(m, side=-1, S=101.0, TP=98.0) == (rp.SL_GAP, 101.5, T0 + 9 * MIN)


def test_timeout_8h_market_exit_at_open():
    m = flat_minutes(2880)
    set_min(m, T0 + 480 * MIN, o=100.7)
    assert _run(m) == (rp.TIME, 100.7, T0 + 480 * MIN)
    set_min(m, T0 + 479 * MIN, h=102.01)               # последняя минута окна ещё исполняет цель
    assert _run(m)[0] == rp.TP


def test_missing_minute_before_exit_censors_but_earlier_exit_kept():
    m = drop_min(flat_minutes(2880), T0 + 100 * MIN)
    assert _run(m)[0] == rp.CENS
    set_min(m, T0 + 50 * MIN, l=98.0)
    assert _run(m)[0] == rp.SL


def test_stop_loss_without_gap_is_exactly_minus_one_r():
    m = flat_minutes(2880)
    set_min(m, T0 + 5 * MIN, l=98.9)
    s = sym_from_minutes(m)
    E = 100.0 * 1.0002
    st = rp.simulate(s, I0, 1, 100.0, E, 99.0, E + 2 * (E - 99.0), 7.5, rp.BASE)
    assert rp.KIND[int(st["kind"][0])] == "SL" and math.isclose(st["R"][0], -1.0, abs_tol=1e-12)
    assert math.isclose(st["R_gross"][0], (99.0 - 100.0) * st["q"][0] / st["risk_usd"][0])


def _fund_case(side, i0, rows):
    m = flat_minutes(2880)
    s = sym_from_minutes(m, funding=funding_df(rows))
    S = 99.0 if side > 0 else 101.0
    TP = 102.0 if side > 0 else 98.0
    return rp.simulate(s, i0, side, 100.0, 100.0, S, TP, 7.5, NOSLIP)


def test_funding_long_pays_short_receives_positive_rate():
    rows = [(START + 8 * 3_600_000 + 1, 0.0001, 100.5), (START + 16 * 3_600_000 + 1, 0.0003, 100.0)]
    lg = _fund_case(1, 7 * 60, rows)                   # 07:00 → TIME 15:00: одно начисление (08:00)
    assert lg["funding_n"][0] == 1 and math.isclose(lg["funding"][0], lg["q"][0] * 100.5 * 0.0001)
    sh = _fund_case(-1, 7 * 60, rows)
    assert sh["funding_n"][0] == 1 and math.isclose(sh["funding"][0], -sh["q"][0] * 100.5 * 0.0001)
    fee = lambda st: st["fee_in"][0] + st["fee_out"][0]                     # noqa: E731
    assert math.isclose(lg["pnl"][0], -fee(lg) - lg["funding"][0])       # цена плоская
    assert math.isclose(sh["pnl"][0], -fee(sh) - sh["funding"][0]) and sh["funding"][0] < 0


def test_funding_negative_rate_long_receives():
    st = _fund_case(1, 7 * 60, [(START + 8 * 3_600_000 + 1, -0.0002, 100.0)])
    assert st["funding"][0] < 0 and math.isclose(st["funding"][0], -st["q"][0] * 100.0 * 0.0002)


def test_funding_boundaries_entry_minute_excluded_exit_minute_included():
    rows = [(START + 8 * 3_600_000 + 1, 0.0001, 100.0), (START + 16 * 3_600_000 + 2, 0.0005, 100.0)]
    st = _fund_case(1, 8 * 60, rows)                   # вход 08:00 (не платит), выход по open 16:00 (платит)
    assert rp.KIND[int(st["kind"][0])] == "TIME" and st["xt"][0] == START + 16 * 3_600_000
    assert st["funding_n"][0] == 1 and math.isclose(st["funding"][0], st["q"][0] * 100.0 * 0.0005)


def test_sizing_rounds_down_to_qty_step():
    q, per = rp.size(7.5, 100.0, 99.0, 1, rp.BASE, 0.001)
    exp_per = (100.0 - 99.0 * 0.9998) + 0.00048 * 100.0 + 0.00048 * 99.0 * 0.9998
    assert math.isclose(per, exp_per)
    assert q * per <= 7.5 < (q + 0.001) * per and math.isclose(q / 0.001, round(q / 0.001))
    q, per = rp.size(7.5, 100.0, 101.0, -1, rp.BASE, 0.001)                # SHORT: S* = S × (1 + slip)
    assert math.isclose(per, (101.0 * 1.0002 - 100.0) + 0.00048 * 100.0 + 0.00048 * 101.0 * 1.0002)
    q, per = rp.size(7.5, 0.5, 0.495, 1, rp.BASE, 1.0)                     # XRP — целые монеты
    assert q == int(q) and q * per <= 7.5 < (q + 1) * per


def test_min_notional_blocks_tiny_size():
    s = sym_from_minutes(flat_minutes(2880))
    st = rp.simulate(s, I0, 1, 100.0, 100.0, 99.0, 102.0, 0.04, NOSLIP)     # q = 0.036 → $3.6 < $5
    assert not st["ok"][0]
    st = rp.simulate(s, I0, 1, 100.0, 100.0, 99.0, 102.0, 0.06, NOSLIP)     # q = 0.054 → $5.4
    assert st["ok"][0]


@pytest.mark.parametrize("n", [1, 7])
def test_one_execution_engine_vectorized_equals_single(n):
    m = flat_minutes(2880)
    rng = np.random.default_rng(3)
    for k in range(200, 1800):
        d = rng.normal(0, 0.3)
        set_min(m, START + k * MIN, o=100 + d, h=100 + abs(d) + 0.4, l=100 - abs(d) - 0.4, c=100 + d / 2)
    s = sym_from_minutes(m)
    i0 = np.arange(n) * 97 + 300
    raw = s.o[i0]
    E = raw * 1.0002
    S = E * (1 - 0.008)
    TP = E + 2 * (E - S)
    vec = rp.simulate(s, i0, 1, raw, E, S, TP, 7.5, rp.BASE)
    for k in range(n):
        one = rp.simulate(s, i0[k], 1, raw[k], E[k], S[k], TP[k], 7.5, rp.BASE)
        assert one["kind"][0] == vec["kind"][k] and math.isclose(one["R"][0], vec["R"][k])
