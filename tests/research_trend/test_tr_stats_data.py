"""Протокол §1, §4, §6 (docs/TREND_4H_RECHECK_PROTOCOL_2026-10-15.md): 4h-свечи из минут (полнота по ohlc_grid,
пустые выпадают, якорь), индикаторы — живые tools/trend_state, C1 без наложения позиций, трети P1, бутстрап по
ISO-неделям, ворота и статусы."""
import numpy as np
import pandas as pd
import pytest

from tests.research_trend.tr_fx import H4, MIN, START, drop, flat, mi, rp, setm, st


def test_valid_mask_matches_ohlc_grid_valid_bar():
    from scripts.ohlc_grid import valid_bar
    rows = [(1, 2, 0.5, 1.5, 0), (1, 1, 1, 1, 0), (1, 0.9, 0.5, 0.8, 1), (1, 2, 1.1, 1.5, 1), (1, 2, 0, 1, 1),
            (1, 2, 0.5, 1, -1), (np.nan, 2, 0.5, 1, 1), (1, np.inf, 0.5, 1, 1), (2, 2, 1, 1, 3)]
    a = np.array(rows, float)
    got = rp.valid_mask(a[:, 0], a[:, 1], a[:, 2], a[:, 3], a[:, 4])
    assert got.tolist() == [valid_bar(r) for r in rows]


def test_bars_ohlc_completeness_and_empty_bins():
    m = flat(10)
    setm(m, mi(2, 0), o=101.0)
    setm(m, mi(2, 17), h=105.0)
    setm(m, mi(2, 99), l=95.0)
    setm(m, mi(2, 239), c=99.0)
    m = drop(m, list(range(mi(5, 0), mi(6, 0))) + [mi(7, 3)])    # свеча 5 пустая, свеча 7 без одной минуты
    s = rp.Series("ETHUSDT", m["ts"], m["o"], m["h"], m["l"], m["c"], m["v"])
    assert s.nb == 9 and (START + 5 * H4) not in s.bstart.tolist()     # пустая свеча выпала (resample + dropna)
    j = 2
    assert (s.bo[j], s.bh[j], s.bl[j], s.bc[j]) == (101.0, 105.0, 95.0, 99.0)
    j7 = s.bstart.tolist().index(START + 7 * H4)
    assert not s.complete[j7] and s.complete[j7 - 1] and s.complete[j7 + 1]


def test_invalid_minute_makes_bar_incomplete():
    m = flat(4)
    m["l"][mi(1, 10)] = 0.0                       # low ≤ 0 — невалидная минута по ohlc_grid
    s = rp.Series("ETHUSDT", m["ts"], m["o"], m["h"], m["l"], m["c"], m["v"])
    assert s.complete.tolist() == [True, False, True, True]


def test_anchor_offset_and_trailing_incomplete_trimmed():
    m = flat(10)
    s = rp.Series("ETHUSDT", m["ts"], m["o"], m["h"], m["l"], m["c"], m["v"], offset_h=1)
    assert s.bstart[0] == START - 3 * 3_600_000 and not s.complete[0]   # первая свеча якоря 01 — неполная
    assert s.complete[-1] and s.bend[-1] == START + 9 * H4 + 3_600_000   # хвостовая неполная отброшена
    assert s.n_min == int(s.mi1[-1])


def test_data_end_is_last_complete_bar():
    m = flat(6)
    m = drop(m, list(range(mi(5, 100), mi(6, 0))))    # последняя свеча формируется
    valid = rp.valid_mask(m["o"], m["h"], m["l"], m["c"], m["v"])
    assert rp.data_end_ms(m["ts"], m["o"], m["h"], m["l"], m["c"], valid) == START + 5 * H4


def test_indicators_are_live_trend_state():
    from tools.trend_state import _adx, _atr
    rng = np.random.default_rng(1)
    m = flat(40)
    walk = 100 + np.cumsum(rng.normal(0, 0.05, len(m["ts"])))
    m["o"], m["c"] = walk.copy(), walk.copy()
    m["h"], m["l"] = walk + 0.02, walk - 0.02
    s = rp.Series("ETHUSDT", m["ts"], m["o"], m["h"], m["l"], m["c"], m["v"])
    df = pd.DataFrame({"high": s.bh, "low": s.bl, "close": s.bc})
    assert np.allclose(s.atr, _atr(df).to_numpy(), equal_nan=True)
    assert np.allclose(s.adx, _adx(df)[0].to_numpy(), equal_nan=True)
    hh, ll = s.channel(30)
    assert np.isnan(hh[29]) and hh[30] == pytest.approx(s.bh[:30].max()) and ll[31] == pytest.approx(s.bl[1:31].min())


def _strata():
    c = np.arange(0, 200, 3, dtype=np.int64)
    return {(1, 0, 0, 0): {"c": c, "x": c + 7, "R": np.ones(len(c)), "net": np.ones(len(c)),
                           "cens": np.zeros(len(c), bool), "period": np.zeros(len(c), int)}}


def test_c1_counts_and_seed_reproducible():
    a = rp.c1_replicate(_strata(), [(1, 0, 0, 0)] * 15, np.random.default_rng(20261015))
    b = rp.c1_replicate(_strata(), [(1, 0, 0, 0)] * 15, np.random.default_rng(20261015))
    assert a == b and len(a[0]) + a[1] == 15 and len(a[0]) > 0


def test_c1_intervals_disjoint_by_construction():
    strata = _strata()
    placed = []

    class G:
        def __init__(self):
            self.r = np.random.default_rng(7)

        def integers(self, n):
            return int(self.r.integers(n))

    # обёртка: восстанавливаем выбранные интервалы через монотонный R = индекс кандидата
    st0 = strata[(1, 0, 0, 0)]
    st0["R"] = np.arange(len(st0["c"]), dtype=float)
    got, dropped = rp.c1_replicate(strata, [(1, 0, 0, 0)] * 20, G())
    for g in got:
        k = int(g[0])
        assert g[4] == int(st0["x"][k] - st0["c"][k])               # длительность в свечах
        placed.append((int(st0["c"][k]), int(st0["x"][k])))
    placed.sort()
    for (a0, a1), (b0, b1) in zip(placed, placed[1:]):
        assert a1 < b0                             # свеча следующего входа строго после свечи выхода предыдущей


def test_c1_literal_sequential_moves_forward():
    strata = _strata()
    st0 = strata[(1, 0, 0, 0)]
    st0["R"] = np.arange(len(st0["c"]), dtype=float)

    class G:
        def __init__(self):
            self.r = np.random.default_rng(3)

        def integers(self, n):
            return int(self.r.integers(n))

    got, dropped = rp.c1_replicate(strata, [(1, 0, 0, 0)] * 30, G(), literal=True)
    cs = [int(st0["c"][int(g[0])]) for g in got]
    xs = [int(st0["x"][int(g[0])]) for g in got]
    assert all(b > a for a, b in zip(xs, cs[1:]))
    assert dropped > 0                             # буквальный вариант уходит к концу периода и теряет входы


def test_c1_nonoverlap_prefers_short_trades_independent_does_not():
    """Диагностика смещения R16: при запрете наложения длинные кандидаты реже помещаются между уже поставленными
    позициями; независимый выбор (без одной позиции) берёт кандидатов без оглядки на длительность."""
    c = np.arange(0, 400, dtype=np.int64)
    dur = np.where(c % 2 == 0, 1, 40)                # чётные — короткие (1 свеча), нечётные — длинные (40 свечей)
    strata = {(1, 0, 0, 0): {"c": c, "x": c + dur, "R": np.where(dur > 1, 1.0, -1.0), "net": np.zeros(len(c)),
                             "cens": np.zeros(len(c), bool), "period": np.zeros(len(c), int)}}
    keys = [(1, 0, 0, 0)] * 60
    non = [g for r in range(30) for g in rp.c1_replicate(strata, keys, np.random.default_rng(r))[0]]
    ind = [g for r in range(30) for g in rp.c1_replicate(strata, keys, np.random.default_rng(r), independent=True)[0]]
    share_long = lambda gs: np.mean([g[4] > 1 for g in gs])   # noqa: E731
    assert abs(share_long(ind) - 0.5) < 0.05
    assert share_long(non) < share_long(ind) - 0.1


def test_c1_missing_stratum_drops():
    got, dropped = rp.c1_replicate(_strata(), [(-1, 0, 0, 0)], np.random.default_rng(1))
    assert got == [] and dropped == 1


def test_thirds_are_532_days():
    assert st.THIRD == 532 * 86_400_000
    assert st.THIRDS[0][0] == 1577836800000 and st.THIRDS[-1][1] == 1715731200000


def _tr(ts, R, period="P1", cens=False):
    return {"entry_ts": ts, "R": R, "net": R * 50, "R_gross": R, "fee_in": 0.0, "fee_out": 0.0, "funding": 0.0,
            "d": 1, "censored": cens, "period": period, "kind": "censored" if cens else "close_exit"}


def test_block_and_thirds():
    t = [_tr(st.THIRDS[0][0] + DAY, 1.0), _tr(st.THIRDS[2][0] + DAY, -0.5), _tr(st.THIRDS[2][0] + 2 * DAY, 2.0),
         _tr(st.THIRDS[2][0] + 3 * DAY, 9.0, cens=True)]
    b = st.block(t)
    assert b["n"] == 3 and b["censored"] == 1 and b["mean_R"] == pytest.approx(2.5 / 3)
    th = st.thirds(t)
    assert [x["n"] for x in th] == [1, 0, 2] and th[2]["mean_R"] == pytest.approx(0.75)


DAY = 86_400_000


def test_weekly_ci_deterministic_and_counts_empty_weeks():
    ts = [st.P1_START + k * 7 * DAY for k in range(0, 40)]
    R = [0.5 if k % 2 else -0.2 for k in range(40)]
    a = st.weekly_ci(ts, R, st.P1_START, st.P1_START + 80 * 7 * DAY, draws=999)
    b = st.weekly_ci(ts, R, st.P1_START, st.P1_START + 80 * 7 * DAY, draws=999)
    assert a == b and a["weeks_nonempty"] == 40 and a["weeks_all"] >= 80
    assert a["all"][0] < 0.15 < a["all"][1]


def _g(**kw):
    g = {"mean_R": 0.1, "mean_R_slip2": 0.05, "n": 150, "weeks_nonempty": 60, "ci_all": [0.01, 0.2],
         "third3_mean_R": 0.1, "third3_n": 40, "p2_mean_R": 0.1, "p2_n": 80,
         "neighbors": {"(20,3)": 0.1, "(45,3)": 0.1, "(30,2.5)": 0.1, "(30,4)": 0.1},
         "offsets": {"00": 0.1, "01": 0.1, "02": 0.1, "03": 0.1}, "c1_rank": 0.01}
    g.update(kw)
    return g


def test_gates_and_status():
    rows = st.gates(_g())
    assert all(r["pass"] for r in rows) and st.status(0.1, 150, rows) == "Квалифицирована"
    rows = st.gates(_g(c1_rank=0.2))
    assert [r["gate"] for r in rows if not r["pass"]] == [7]
    assert st.status(0.1, 150, rows) == "Не квалифицирована"
    rows = st.gates(_g(mean_R=-0.01, n=80))
    assert st.status(-0.01, 80, rows) == "Отвергнута (n < 100)"
    rows = st.gates(_g(neighbors={"(20,3)": 0.1, "(45,3)": -0.01, "(30,2.5)": 0.1, "(30,4)": 0.1}))
    assert [r["gate"] for r in rows if not r["pass"]] == [5]
    rows = st.gates(_g(ci_all=[-0.01, 0.2]))
    assert [r["gate"] for r in rows if not r["pass"]] == [3]


def test_equity_curve_floating_and_realized():
    bend = START + np.arange(1, 6) * H4
    bc = np.array([100.0, 98.0, 103.0, 101.0, 101.0])
    mk = {"ETHUSDT": {"bend": bend, "bc": bc, "f_t": np.zeros(0, np.int64), "f_cum": np.zeros(1)}}
    t = {"sym": "ETHUSDT", "d": 1, "qty": 1.0, "entry_ts": int(bend[0]), "exit_ts": int(bend[3]), "entry_fill": 100.0,
         "fee_in": 0.0, "net": 1.0, "censored": False}
    grid, eq = st.equity_curve([t], mk)
    assert eq.tolist() == [0.0, -2.0, 3.0, 1.0, 1.0]
    dd = st.max_dd(grid, eq)
    assert dd["max_dd"] == -2.0 and dd["final"] == 1.0
