"""Acceptance tests: observed funding coverage, clocks and each leg's cutoff.

Only private-data imports are isolated with AST. Compiled functions are the
current exact source bodies; no vendor requests, Telegram or live processes.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from services.btc_signals import engine as en
from services.btc_signals import features as fx
from tests.services.btc_signals.test_features import rich, cut

ROOT = Path(__file__).resolve().parents[2]
H = 3600


def exact(file, name, namespace):
    tree = ast.parse((ROOT / file).read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    ns = dict(namespace)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), file, "exec"), ns)
    return ns[name]


def test_observed_zero_is_known_without_any_change_in_accumulator():
    records = fx.funding_records(np.arange(0, 33, 8) * H, np.zeros(5))
    values, coverage = fx.funding_window(records, np.array([24, 31, 32]) * H, 24 * H)
    assert coverage.all()
    assert np.array_equal(values, np.zeros(3))


@pytest.mark.parametrize("hours", [24, 168, 720])
def test_full_window_must_mature_after_first_observed_payout(hours):
    first = 80 * H
    times = first + np.arange(0, hours + 17, 8) * H
    records = fx.funding_records(times, np.full(len(times), 0.01))
    query = np.array([first - H, first, first + (hours - 1) * H, first + hours * H])
    values, coverage = fx.funding_window(records, query, hours * H)
    assert np.array_equal(coverage, [False, False, False, True])
    assert np.isnan(values[:3]).all()
    assert values[-1] == pytest.approx(hours / 8 * 0.01)


def test_internal_gap_and_missing_due_payment_remain_unknown_until_covered():
    # The due payout at hour 16 is absent; later records do not backfill it.
    records = fx.funding_records(np.array([0, 8, 24, 32, 40]) * H, np.zeros(5))
    values, coverage = fx.funding_window(records, np.array([8, 15, 16, 24, 40]) * H, 8 * H)
    assert np.array_equal(coverage, [True, True, False, False, True])
    assert np.isnan(values[2:4]).all()
    assert values[0] == values[1] == values[-1] == 0


def test_schedule_is_explicit_and_can_be_hourly():
    records = fx.funding_records(np.arange(30) * H, np.full(30, 0.001), expected_interval_s=H)
    values, coverage = fx.funding_window(records, np.array([24, 29]) * H, 24 * H)
    assert coverage.all()
    assert np.allclose(values, 0.024)


def test_invalid_rate_is_missing_and_latest_duplicate_record_wins():
    records = fx.funding_records(np.array([0, 8, 16, 16, 24]) * H, [0, 0, 1, np.nan, 0])
    values, coverage = fx.funding_window(records, [24 * H], 24 * H)
    assert not coverage[0] and np.isnan(values[0])


def test_absent_metadata_never_guesses_observability_from_F():
    a, lay = rich(n=24 * 40)
    a.pop("funding_records")
    a["F"] = np.cumsum(np.ones(len(a["t"])))
    result = fx.prepare(a, lay)
    assert all(np.isnan(result[f"фандинг {name}, %"]).all() for name in ("24ч", "7д", "30д"))
    assert not result["_funding_coverage_24h"].any()


@pytest.mark.parametrize("hours", [(1000, 3500), (3500,)])
def test_prepare_prefix_unchanged_by_future_first_payout_or_resumption(hours):
    a, lay = rich(n=24 * 150)
    times = a["t"][list(hours)]
    a["funding_records"] = fx.funding_records(times, np.zeros(len(times)))
    i = 3000
    full = fx.prepare(a, lay)
    part = fx.prepare(cut(a, i + 1), tuple(x[:i + 1] for x in lay))
    for name in ("24ч", "7д", "30д"):
        assert np.isnan(full[f"фандинг {name}, %"][i])
        np.testing.assert_equal(full[f"фандинг {name}, %"][:i + 1], part[f"фандинг {name}, %"])


def test_upstream_never_places_future_payment_into_last_price_hour():
    a = {"t": np.array([100, 200]), "j": np.array([0, 0])}
    h1 = pd.DataFrame({"R": [1, 1], "B": [1, 1], "run_B": [1, 1]})
    h4 = pd.DataFrame({"atr": [1.0], "adx": [20.0], "d_G": [0.0], "run_G": [1]})
    prep = exact("research/chart_walk_20261105/entry_rules.py", "prep", {
        "np": np, "jr": SimpleNamespace(add_extra=lambda h4, d1, fund: h4),
        "rules": SimpleNamespace(prepare=lambda h1, h4: dict(a)), "cw": SimpleNamespace(T=lambda s: 0)})
    result, _ = prep(h1, h4, None, pd.Series([0.0, 0.01], index=[100, 300]), funding_interval_s=100)
    assert np.array_equal(result["F"], [0, 0])
    assert np.array_equal(result["funding_records"]["times"], [100])
    assert np.array_equal(result["funding_records"]["rates_pct"], [0])
    assert result["funding_records"]["expected_interval_s"] == 100


def basis_function():
    trade_cash = exact("research/chart_walk_20261105/ledger.py", "trade_cash", {"NOTIONAL": 1000.0, "SIDE_COST": 0.00068})
    def unit(fm, legs):
        cash = [trade_cash(fm, x[:5]) for x in legs]
        return np.array([(move - fee - fund) / 10 for move, fee, fund in cash]), np.array([x[7] for x in legs])
    return exact("research/chart_walk_20261105/basis_check_1109.py", "with_funding", {
        "np": np, "pd": pd, "fx": fx, "pl": SimpleNamespace(unit=unit)}), unit


@pytest.mark.parametrize("side", [-1, 1])
@pytest.mark.parametrize("use_timestamp", [True, False])
def test_funding_before_add_is_not_charged_or_credited_to_add(side, use_timestamp):
    times = np.array([0, 8, 16, 24]) * H
    a = {"t": times, "funding_records": fx.funding_records(times, [0, 1, 0, 0])}
    r = {"_i0": 0, "_i1": 3, "сторона": side, "вес": 1.0, "цена входа": 100,
         "цена выхода": 98, "добор": 1.0, "цена добора": 99}
    r["_add_t" if use_timestamp else "_add_i"] = times[2] if use_timestamp else 2
    function, unit = basis_function()
    fm = np.array([0.0, 1.0, 1.0, 1.0])
    actual = function(pd.DataFrame([r]), fm, a)[0]
    corrected = [(0, 3, 100, 98, side, "x", "x", .5), (2, 3, 99, 98, side, "x", "x", .5)]
    cash, weights = unit(fm, corrected)
    assert actual == pytest.approx(float(cash @ weights))


def test_missing_add_clock_or_payment_coverage_returns_unknown():
    times = np.array([0, 8, 16, 24]) * H
    row = {"_i0": 0, "_i1": 3, "сторона": -1, "вес": 1.0, "цена входа": 100,
           "цена выхода": 98, "добор": 1.0, "цена добора": 99}
    function, _ = basis_function()
    a = {"t": times, "funding_records": fx.funding_records(times, [0, 0, 0, 0])}
    assert np.isnan(function(pd.DataFrame([row]), np.zeros(4), a)[0])
    row["_add_t"] = times[2]
    a["funding_records"] = fx.funding_records(times[[0, 2, 3]], [0, 0, 0])
    assert np.isnan(function(pd.DataFrame([row]), np.zeros(4), a)[0])


def test_payout_on_add_timestamp_uses_documented_entry_exclusive_cutoff():
    times = np.array([0, 8, 16, 24]) * H
    row = {"_i0": 0, "_i1": 3, "_add_t": times[2], "сторона": 1, "вес": 1.0,
           "цена входа": 100, "цена выхода": 98, "добор": 1.0, "цена добора": 99}
    function, unit = basis_function()
    fm = np.array([0.0, 0.0, 1.0, 1.0])
    a = {"t": times, "funding_records": fx.funding_records(times, [0, 0, 1, 0])}
    expected_cash, weights = unit(fm, [(0, 3, 100, 98, 1, "x", "x", .5), (2, 3, 99, 98, 1, "x", "x", .5)])
    assert function(pd.DataFrame([row]), fm, a)[0] == pytest.approx(float(expected_cash @ weights))


@pytest.mark.parametrize("side", [-1, 1])
def test_engine_intrabar_add_includes_hour_end_payment_but_entry_does_not(side):
    times = np.arange(25) * H
    row = {"_i0": 0, "_i1": 24, "_add_t": times[16], "_add_before_close": True,
           "сторона": side, "вес": 1.0, "цена входа": 100, "цена выхода": 98,
           "добор": 1.0, "цена добора": 99}
    function, unit = basis_function()
    # Funding at original entry time is excluded. Funding at add-hour close
    # belongs to both legs, because the standing add filled before that close.
    fm = np.where(times < times[16], 1.0, 2.0)
    a = {"t": times, "funding_records": fx.funding_records(np.array([0, 8, 16, 24]) * H, [1, 0, 1, 0])}
    cash, weights = unit(fm, [(0, 24, 100, 98, side, "x", "x", .5), (15, 24, 99, 98, side, "x", "x", .5)])
    assert function(pd.DataFrame([row]), fm, a)[0] == pytest.approx(float(cash @ weights))


def test_trade_table_persists_add_clock_and_coverage():
    times = np.array([0, 8, 16, 24]) * H
    a = {"t": times}
    pos = {"entry_i": 0, "entry_t": 0, "entry": 100, "w": 1, "add_done": True,
           "add_t": int(times[2]), "add_px": 99}
    ex = {"kind": "выход", "i": 3, "t": int(times[3]), "side": -1, "tag": "под синей",
          "pos": pos, "px": 98, "why": "test", "res": 1}
    mock_fx = SimpleNamespace(prepare=lambda *args: {"_funding_coverage_24h": np.array([True, False, False, False])},
                              path=lambda *args, **kwargs: {}, history=lambda *args: {}, row=lambda *args: {})
    build = exact("research/chart_walk_20261105/trade_table.py", "build", {
        "np": np, "pd": pd, "fx": mock_fx, "LIVE_KEYS": set(),
        "fe": SimpleNamespace(ext_prepare=lambda *args: {}),
        "en": SimpleNamespace(MAIN=en.MAIN, simulate=lambda *args: ([ex], None), simulate432=lambda *args: ([], None, {})),
        "intervals": lambda *args: [], "side_at": lambda *args: 0,
        "utc": lambda value: datetime.fromtimestamp(int(value), timezone.utc).strftime("%Y-%m-%d %H:%M")})
    table = build("Binance", a, None, None)
    assert table.loc[0, "_add_t"] == times[2]
    assert table.loc[0, "_add_i"] == 2
    assert table.loc[0, "добор UTC"] == "1970-01-01 16:00"
    assert bool(table.loc[0, "_add_before_close"])
    assert bool(table.loc[0, "_funding_coverage_24h"])

