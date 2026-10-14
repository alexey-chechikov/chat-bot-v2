"""Протокол ATLAS 14.10, тест 1: знак и нормировка дельты, пороги только по прошлому, правила сигнала, волатильность."""
from types import SimpleNamespace

import numpy as np
import pytest

from tests.research_atlas.atlas_fx import (DAY0, INST, bar_id, d1, days, drop_minute, info_of, sb, set_bar)


def test_nd_sign_and_normalisation_is_by_bar_sums():
    a = days(1)
    set_bar(a, bar_id(DAY0, 0), tb_frac=1.0)                       # все покупки агрессором → +1
    set_bar(a, bar_id(DAY0, 1), tb_frac=0.0)                       # все продажи агрессором → −1
    mk = (a["ts"] >= bar_id(DAY0, 2) * sb.BAR) & (a["ts"] < bar_id(DAY0, 3) * sb.BAR)
    i0 = int(np.flatnonzero(mk)[0])
    a["volume"][mk], a["taker_buy"][mk] = 1.0, 0.0
    a["volume"][i0], a["taker_buy"][i0] = 10.0, 10.0               # сумма: (2·10 − 24) / 24, не среднее по минутам
    set_bar(a, bar_id(DAY0, 3), volume=0.0, tb_frac=0.0)           # нулевой объём → NA
    m = sb.Market(a, INST, False)
    assert m.nd[0] == pytest.approx(1.0)
    assert m.nd[1] == pytest.approx(-1.0)
    assert m.nd[2] == pytest.approx((2 * 10 - 24) / 24)
    assert np.isnan(m.nd[3])
    assert np.all(np.abs(m.nd[np.isfinite(m.nd)]) <= 1.0 + 1e-12)


def test_bar_nd_formula_and_zero_volume():
    out = sb.bar_nd([10.0, 10.0, 0.0], [7.0, 2.0, 0.0])
    assert out[0] == pytest.approx(0.4) and out[1] == pytest.approx(-0.6) and np.isnan(out[2])


def test_market_without_taker_buy_has_no_delta():
    a = days(1)
    a.pop("taker_buy")
    m = sb.Market(a, INST, False)
    assert m.nd is None
    with pytest.raises(ValueError):
        m.nd_quantile(0.1)


def _day_bars(m, day):
    return np.flatnonzero(m.bar_day == day)


def test_thresholds_use_only_the_previous_20_complete_days():
    a = days(23, seed=1)
    m = sb.Market(a, INST, False)
    p10, p90 = d1.thresholds(m)
    assert np.all(np.isnan(p10[_day_bars(m, DAY0 + 19)]))        # раньше только 19 полных дней
    b20 = _day_bars(m, DAY0 + 20)
    prior = np.isin(m.bar_day, np.arange(DAY0, DAY0 + 20))
    assert np.allclose(p10[b20], np.quantile(m.nd[prior], 0.10))
    assert np.allclose(p90[b20], np.quantile(m.nd[prior], 0.90))
    b22 = _day_bars(m, DAY0 + 22)
    prior22 = np.isin(m.bar_day, np.arange(DAY0 + 2, DAY0 + 22))
    assert np.allclose(p10[b22], np.quantile(m.nd[prior22], 0.10))


def test_thresholds_do_not_see_the_current_day_or_future():
    a = days(23, seed=2)
    base = sb.Market(a, INST, False).nd_quantile(0.10)
    b = {k: v.copy() for k, v in a.items()}
    day21 = (b["ts"] // sb.DAY) >= DAY0 + 21
    b["taker_buy"][day21] = 0.0                                    # день сигнала и будущее — сплошные продажи
    m2 = sb.Market(b, INST, False)
    p2 = m2.nd_quantile(0.10)
    idx21 = _day_bars(m2, DAY0 + 21)
    assert np.allclose(p2[idx21], base[idx21]), "порог дня 21 изменился от данных дня 21 и позже"
    idx22 = _day_bars(m2, DAY0 + 22)
    assert not np.allclose(p2[idx22], base[idx22]), "день 22 обязан видеть день 21 (он в прошлом)"


def test_incomplete_day_is_skipped_not_counted():
    a = days(22, seed=3)
    a = drop_minute(a, (DAY0 + 5) * sb.DAY + 7 * sb.MIN)          # день 5 — 1439 минут, неполный
    m = sb.Market(a, INST, False)
    assert DAY0 + 5 not in m.complete_days
    p10 = m.nd_quantile(0.10)
    assert np.all(np.isnan(p10[_day_bars(m, DAY0 + 20)]))        # до дня 20 полных только 19
    want = np.isin(m.bar_day, [d for d in range(DAY0, DAY0 + 21) if d != DAY0 + 5])
    assert np.allclose(p10[_day_bars(m, DAY0 + 21)], np.quantile(m.nd[want], 0.10))


def test_signal_rules_divergence_and_same_direction():
    nd = np.array([-0.9, -0.9, -0.9, 0.9, 0.9, 0.9, 0.0, np.nan, -0.9])
    o = np.array([100, 100, 100, 100, 100, 100, 100, 100, 100], dtype=float)
    c = np.array([101, 100, 99, 101, 100, 99, 101, 101, 101], dtype=float)
    p10 = np.array([-0.5] * 8 + [np.nan])
    p90 = np.array([0.5] * 8 + [np.nan])
    m = SimpleNamespace(nd=nd, b_o=o, b_c=c)
    assert d1.signal_side(m, p10, p90, "div").tolist() == [1, 1, 0, 0, -1, -1, 0, 0, 0]
    assert d1.signal_side(m, p10, p90, "same").tolist() == [0, 0, 1, -1, 0, 0, 0, 0, 0]


def test_vol_feature_uses_only_the_20_bars_before_and_needs_them_contiguous():
    rng = np.random.default_rng(4)
    a = days(2, seed=4)
    for k in range(192):
        lvl = 100 + rng.normal()
        set_bar(a, bar_id(DAY0, 0) + k, o=lvl, h=lvl + rng.uniform(0.1, 2), l=lvl - rng.uniform(0.1, 2), c=lvl)
    m = sb.Market(a, INST, False)
    v = d1.vol_feature(m)
    assert np.all(np.isnan(v[:20])) and np.isfinite(v[20])
    s = 57
    assert v[s] == pytest.approx((m.b_h[s - 20:s].max() - m.b_l[s - 20:s].min()) / m.b_c[s - 1])
    b = {k: x.copy() for k, x in a.items()}
    set_bar(b, bar_id(DAY0, 0) + s, h=1e6, l=1e-6)                 # сама свеча s не входит
    assert d1.vol_feature(sb.Market(b, INST, False))[s] == pytest.approx(v[s])
    g = drop_minute(a, (bar_id(DAY0, 0) + 30) * sb.BAR + 3 * sb.MIN)   # свеча 30 неполная → выпала
    mg = sb.Market(g, INST, False)
    vg = d1.vol_feature(mg)
    ids = mg.b_id - bar_id(DAY0, 0)
    assert np.all(np.isnan(vg[(ids >= 31) & (ids <= 50)])) and np.all(np.isfinite(vg[ids >= 51]))


def test_buckets_and_terciles():
    a = days(1)
    m = sb.Market(a, INST, False)
    bk = d1.bucket6h(m)
    assert bk[0] == 0 and bk[23] == 0 and bk[24] == 1 and bk[71] == 2 and bk[72] == 3 and bk[95] == 3
    cuts = d1.tercile_cuts(np.arange(1.0, 10.0), np.ones(9, dtype=bool))
    assert d1.tercile(np.array([1.0, 5.0, 9.0, np.nan]), cuts).tolist() == [0, 1, 2, -1]


def test_prepared_pool_only_has_bars_with_thresholds_volatility_and_exit():
    a = days(22, seed=5)
    p = d1.Prepared(a, info_of(a), INST)
    assert len(p.pool) and np.all(np.isfinite(p.p10[p.pool])) and np.all(p.terc[p.pool] >= 0)
    assert np.all(p.i_out[p.pool] >= 0)
    assert p.m.bar_day[p.pool].min() == DAY0 + 20
