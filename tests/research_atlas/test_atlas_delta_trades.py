"""Протокол ATLAS 14.10: время входа/выхода и одна позиция, расходы, контроль по стратам, статусы, версия Cn теста 2,
неизменность PAXG/XAU."""
from types import SimpleNamespace

import numpy as np
import pytest

from tests.research_atlas.atlas_fx import DAY0, INST, bar_id, d1, days, info_of, sb, set_bar

import delta_test2 as d2  # noqa: E402  (путь research/atlas_data добавлен в atlas_fx)


def _minute_open_ramp(n_days=1):
    a = days(n_days)
    a["open"] = 100.0 + 0.01 * np.arange(len(a["ts"]))           # open минуты однозначно говорит, какая это минута
    a["close"] = a["open"].copy()
    a["high"], a["low"] = a["open"].copy(), a["open"].copy()
    return a


def test_entry_is_next_bar_open_and_exit_is_open_four_bars_later():
    a = _minute_open_ramp()
    m = sb.Market(a, INST, False)
    i_in, i_out = d1.entry_exit(m)
    s = 10
    assert a["ts"][i_in[s]] == (m.b_id[s] + 1) * sb.BAR             # open свечи s+1
    assert a["ts"][i_out[s]] == (m.b_id[s] + 5) * sb.BAR            # 4 свечи (1 ч) после входа
    assert a["ts"][i_out[s]] - a["ts"][i_in[s]] == sb.HOUR
    assert i_out[91] == -1 and i_out[90] >= 0                       # выхода за концом данных нет — сделки нет


def test_one_position_signal_bar_must_start_at_or_after_exit():
    a = _minute_open_ramp()
    m = sb.Market(a, INST, False)
    i_in, i_out = d1.entry_exit(m)
    side = np.zeros(len(m.b_id), dtype=np.int8)
    side[[10, 12, 14, 15, 93]] = [1, -1, 1, -1, 1]
    taken, busy, no_fill = d1.run_events(m, side, i_in, i_out)
    assert taken.tolist() == [10, 15]                               # 12 и 14 — во время позиции; 15 начинается на выходе
    assert busy == 2 and no_fill == 1                               # у 93 нет минуты выхода


def test_trade_return_long_short_and_costs():
    g_long = d1.trade_return(100.0, 101.0, 1.0)
    g_short = d1.trade_return(100.0, 99.0, -1.0)
    assert g_long == pytest.approx(0.01) and g_short == pytest.approx(0.01)
    n_long = d1.trade_return(100.0, 101.0, 1.0, d1.SLIP, d1.TAKER)
    f_in, f_out = 100.0 * (1 + d1.SLIP), 101.0 * (1 - d1.SLIP)
    assert n_long == pytest.approx((f_out - f_in - d1.TAKER * (f_in + f_out)) / 100.0)
    n_short = d1.trade_return(100.0, 99.0, -1.0, d1.SLIP, d1.TAKER)
    f_in, f_out = 100.0 * (1 - d1.SLIP), 99.0 * (1 + d1.SLIP)
    assert n_short == pytest.approx((f_in - f_out - d1.TAKER * (f_in + f_out)) / 100.0)
    flat = d1.trade_return(100.0, 100.0, 1.0, d1.SLIP, d1.TAKER)
    assert flat == pytest.approx(-(2 * d1.SLIP + 2 * d1.TAKER), abs=1e-6)   # круг ≈ 0.136% цены
    flat2 = d1.trade_return(100.0, 100.0, -1.0, d1.SLIP2, d1.TAKER)
    assert flat2 == pytest.approx(-(2 * d1.SLIP2 + 2 * d1.TAKER), abs=1e-6)


def test_run_rule_trade_prices_match_minutes():
    a = days(22, seed=7, drift=0.001)                              # у каждой минуты свой open
    p = d1.Prepared(a, info_of(a), INST)
    r = d1.run_rule(p, "div", n_ctl=20)
    assert r["trades"], "фикстура не дала сделок"
    ts = a["ts"]
    for t in r["trades"][:20]:
        assert t["entry_ts"] == t["sig_ts"] + sb.BAR and t["exit_ts"] == t["entry_ts"] + sb.HOUR
        assert t["entry"] == a["open"][np.searchsorted(ts, t["entry_ts"])]
        assert t["exit"] == a["open"][np.searchsorted(ts, t["exit_ts"])]
        assert (t["side"] > 0 and t["nd"] <= t["p10"]) or (t["side"] < 0 and t["nd"] >= t["p90"])
    gaps = np.diff([t["entry_ts"] for t in r["trades"]])
    assert np.all(gaps >= sb.HOUR + sb.BAR)                         # позиции не пересекаются


def test_matched_control_keeps_composition_without_replacement():
    pool_key = np.array([1, 1, 2, 2])
    pool_val = np.array([10.0, 20.0, 0.0, 3.0])
    means, thin = d1.matched_means(pool_key, pool_val, np.array([1, 1, 2]), n_ctl=200, seed=1)
    assert set(np.round(means, 9).tolist()) == {10.0, 11.0}         # страта 1 — обе свечи без повтора, страта 2 — одна
    assert thin == {}
    again, _ = d1.matched_means(pool_key, pool_val, np.array([1, 1, 2]), n_ctl=200, seed=1)
    assert np.array_equal(means, again)
    _, thin = d1.matched_means(pool_key, pool_val, np.array([1, 1, 1]), n_ctl=5, seed=1)
    assert thin == {1: [3, 2]}                                      # кандидатов меньше, чем целей, — помечено
    with pytest.raises(ValueError):
        d1.matched_means(pool_key, pool_val, np.array([3]), n_ctl=5)


def test_control_rank_counts_ties_against_the_signal():
    assert d1.ctl_rank(5.0, [1.0, 5.0, 6.0]) == (pytest.approx(3 / 4), 2)
    assert d1.ctl_rank(None, [1.0]) == (None, None)


def _trend(drift, price):
    a = days(22, seed=8, drift=drift, price=price)                 # ход за час ≥ 0.18% цены > круга 0.136%
    p = d1.Prepared(a, info_of(a), INST)
    return d1.run_rule(p, "div", n_ctl=50)


def test_control_trades_random_bars_in_the_same_side():
    up = _trend(0.2, 1000.0)                                       # рост: сделки div — только LONG
    assert up["stats"]["by_side"]["SHORT"]["n"] == 0 and up["stats"]["n"] > 0
    assert up["control"]["ctl_median"] > 0                          # случайные свечи тоже куплены — в плюсе
    dn = _trend(-0.2, 10000.0)                                     # падение: сделки div — только SHORT
    assert dn["stats"]["by_side"]["LONG"]["n"] == 0 and dn["stats"]["n"] > 0
    assert dn["control"]["ctl_median"] > 0


def test_status_rules():
    ok = dict(n=150, mean=0.001, hold_mean=0.001, ci_lo=0.0001, mean2x=0.0005, rank=0.01)
    assert d1.atlas_status(**ok)[0] == "Кандидат на малый тест исполнения"
    assert d1.atlas_status(**{**ok, "hold_mean": -0.0001})[0] == "Отвергнута"
    assert d1.atlas_status(**{**ok, "mean": 0.0})[0] == "Отвергнута"
    assert d1.atlas_status(**{**ok, "n": 99})[0] == "Недостаточно данных"
    assert d1.atlas_status(**{**ok, "ci_lo": -0.0001})[0] == "Недостаточно данных"
    assert d1.atlas_status(**{**ok, "rank": 0.2})[0] != "Кандидат на малый тест исполнения"
    assert d1.atlas_status(**{**ok, "rank": None})[0] != "Кандидат на малый тест исполнения"
    assert d1.atlas_status(**{**ok, "mean2x": -0.0001})[0] != "Кандидат на малый тест исполнения"


# ---------- тест 2: версия Cn ----------

def _sweep_fixture(sig_tb_frac):
    """21 полный день по 100 (уровень дня 21 = 100), день 21: сигнальная 00:00 (low 99 < 100 < close 100.5),
    подтверждение 00:15 (close 101.5 > high 101, выше VWAP), вход 00:30 по 104."""
    a = days(21, seed=9)
    tail = days(1, start_day=DAY0 + 21, price=104.0, seed=10)
    tail = {k: v[:360] for k, v in tail.items()}
    a = {k: np.concatenate([a[k], tail[k]]) for k in a}
    set_bar(a, bar_id(DAY0 + 21, 0), o=100.5, h=101, l=99, c=100.5, tb_frac=sig_tb_frac)
    set_bar(a, bar_id(DAY0 + 21, 1), o=100.5, h=102, l=99.5, c=101.5)
    return a


def test_cn_keeps_b_signal_only_when_signal_bar_delta_is_at_or_below_p10():
    sell = sb.Market(_sweep_fixture(0.0), INST, False)             # nd −1 ≤ P10
    buy = sb.Market(_sweep_fixture(1.0), INST, False)              # nd +1 > P10
    for m in (sell, buy):
        assert len(sb.simulate(m, "B", 3000.0, "net")["trades"]) == 1
    t = sb.simulate(sell, "Cn", 3000.0, "net")["trades"]
    assert len(t) == 1 and t[0]["entry_ts"] == (DAY0 + 21) * sb.DAY + 30 * sb.MIN
    assert sb.simulate(buy, "Cn", 3000.0, "net")["trades"] == []
    b = int(np.searchsorted(sell.b_id, bar_id(DAY0 + 21, 0)))
    assert sell.nd[b] == pytest.approx(-1.0) and sell.nd_quantile(0.10)[b] > -1.0


def test_cn_needs_twenty_prior_complete_days():
    a = _sweep_fixture(0.0)
    keep = a["ts"] >= (DAY0 + 2) * sb.DAY                          # до дня 21 только 19 полных дней
    m = sb.Market({k: v[keep] for k, v in a.items()}, INST, False)
    assert len(sb.simulate(m, "B", 3000.0, "net")["trades"]) == 1
    assert sb.simulate(m, "Cn", 3000.0, "net")["trades"] == []


def test_cn_control_samples_b_trades_of_the_same_strata():
    b_id = np.arange(10, dtype=np.int64)
    terc = np.array([0, 0, 1, 1, 2, 2, 0, 1, 2, -1])
    bkt = np.zeros(10, dtype=int)
    p = SimpleNamespace(m=SimpleNamespace(b_id=b_id), terc=terc, strata=lambda idx: bkt[idx] * 10 + terc[idx])
    tr_b = [{"sig_ts": int(i * sb.BAR), "entry_ts": int(i * sb.BAR + 1), "R": float(r)}
            for i, r in zip(range(9), [1, 1, -1, -1, 5, 5, 1, -1, 5])]
    tr_c = [tr_b[0], tr_b[4]]                                       # страты терциль 0 и терциль 2
    c = d2.cn_control(p, tr_b, tr_c, n_ctl=100, seed=3)
    assert c["real_mean_R"] == pytest.approx(3.0) and c["cn_in_b"] == 2
    assert c["ctl_median_R"] == pytest.approx(3.0) and c["k"] == 100 and c["rank"] == pytest.approx(1.0)
    assert c["composition"] == {0: 1, 2: 1}


def test_gold_instruments_and_versions_unchanged_by_atlas_additions():
    assert sb.INST["PAXG"] == dict(file="backtests/frozen/PAXGUSDT_1m_2y.csv", tick=0.01,
                                   tick_before=(sb.PAXG_TICK_CUT, 1.0), step=0.0001, min_qty=0.0001, min_notional=5.0,
                                   taker=0.0010, maker=0.0010, lev=1.0, min_rows=1, funding_file=None)
    assert sb.INST["XAU"] == dict(file="backtests/frozen/XAUUSDT_PERP_1m.csv", tick=0.01, tick_before=None, step=0.001,
                                  min_qty=0.001, min_notional=5.0, taker=0.0005, maker=0.0002, lev=20.0, min_rows=720,
                                  funding_file="backtests/frozen/XAUUSDT_PERP_funding.csv")
    from tests.research_gold.gold_fx import POST_CUT_DAY, normal_fixture
    a = normal_fixture(POST_CUT_DAY)
    with_tb = {**a, "taker_buy": a["volume"] * 0.5}
    for ver in ("A", "B", "E"):
        x = sb.simulate(sb.Market(a, "PAXG", False), ver, 3000.0, "net")["trades"]
        y = sb.simulate(sb.Market(with_tb, "PAXG", False), ver, 3000.0, "net")["trades"]
        assert x == y, f"{ver}: taker_buy в данных изменил сделки"
