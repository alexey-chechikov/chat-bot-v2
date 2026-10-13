"""П.3 разбора GPT 13.10 (§4 п.4): LONG на XAUUSDT-перпетуале платит/получает фандинг в каждый момент начисления, пока
позиция открыта: −qty × mark × rate (отрицательная ставка — поступление). Момент входа (open минуты T) — позиция
открывается после T, начисления нет; момент выхода T = минута выхода — позиция ещё открыта, начисление есть.
fundingTime биржи (…001 мс) округляется до минуты. PAXG — спот, фандинга нет."""
import math

import numpy as np

from tests.research_gold.gold_fx import POST_CUT_DAY, block, combine, first_trade, normal_fixture, set_bar, sb

D = POST_CUT_DAY
H = 3_600_000


def _xau_fixture():
    a = combine(block(D, 0, 720, 100.0), block(D + 1, 0, 360, 104.0))
    set_bar(a, D + 1, 0, o=100.5, h=101, l=99, c=100.5)
    set_bar(a, D + 1, 15, o=100.5, h=102, l=99.5, c=101.5)
    return a


def test_xau_long_pays_and_receives_funding_at_settlements_crossed():
    a = _xau_fixture()
    entry_t = (D + 1) * sb.DAY + 30 * sb.MIN
    exit_t = entry_t + 4 * H
    funding = {"t": np.array([entry_t + 2, (D + 1) * sb.DAY + 4 * H + 1, exit_t + 1, exit_t + sb.MIN + 1], dtype=np.int64),
               "rate": np.array([0.01, 0.001, -0.002, 0.01]),
               "mark": np.array([50.0, 104.5, 103.0, 50.0])}
    t = first_trade(a, "XAU", funding=funding)
    assert t["why"] == "время" and t["exit_ts"] == exit_t
    expected_fund = -t["qty"] * (104.5 * 0.001 + 103.0 * -0.002)
    expected = (t["exit"] - t["entry"]) * t["qty"] - t["fee"] + expected_fund
    assert math.isclose(t["pnl"], expected, rel_tol=0, abs_tol=1e-9), \
        f"PnL без фандинга: {t['pnl']:.6f}, с фандингом должно быть {expected:.6f}"
    assert t.get("n_funding") == 2
    assert math.isclose(t.get("funding", float("nan")), expected_fund, abs_tol=1e-12)
    assert math.isclose(t["R"], t["pnl"] / t["r_usd"], abs_tol=1e-12)


def test_missing_mark_price_falls_back_to_last_1m_close_before_settlement():
    a = _xau_fixture()
    funding = {"t": np.array([(D + 1) * sb.DAY + 4 * H], dtype=np.int64), "rate": np.array([0.0005]),
               "mark": np.array([np.nan])}
    t = first_trade(a, "XAU", funding=funding)
    expected_fund = -t["qty"] * 104.0 * 0.0005                 # close минуты 03:59 = 104
    expected = (t["exit"] - t["entry"]) * t["qty"] - t["fee"] + expected_fund
    assert math.isclose(t["pnl"], expected, abs_tol=1e-9), f"PnL {t['pnl']:.6f}, с фандингом по close {expected:.6f}"


def test_paxg_spot_has_no_funding():
    t = first_trade(normal_fixture(D), "PAXG")
    assert math.isclose(t["pnl"], (t["exit"] - t["entry"]) * t["qty"] - t["fee"], abs_tol=1e-9)
    assert t.get("funding", 0.0) == 0.0
