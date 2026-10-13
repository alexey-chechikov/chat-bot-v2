"""П.7 разбора GPT 13.10 (§6 «Разные определения R»): на ОДНОМ ledger (сделки и qty чистого прогона) публикуются
обе нормировки: бюджетный R = PnL / R$ (0.25% капитала) и ценовой R = ход цены / (вход − стоп); «до расходов» — тот же
ledger без комиссий, проскальзывания и фандинга (никакой отдельной симуляции с другим qty и урезанием номинала)."""
import math

import numpy as np

from tests.research_gold.gold_fx import POST_CUT_DAY, first_trade, normal_fixture, sb, set_minute

D = POST_CUT_DAY


def _trades():
    a1 = normal_fixture(D)                                      # выход по времени
    a2 = normal_fixture(D)
    set_minute(a2, D + 1, 100, open=97.5, low=97.0)             # стоп с гэпом: исполнение по open 97.5
    return [first_trade(a1, "PAXG"), first_trade(a2, "PAXG")]


def test_trade_carries_budget_and_price_r_gross_and_net_on_same_qty():
    for t in _trades():
        d = t["entry"] - t["stop"]
        gross = (t.get("exit_raw", np.nan) - t.get("entry_raw", np.nan)) * t["qty"]
        assert math.isclose(t.get("R_gross", np.nan), gross / t["r_usd"], abs_tol=1e-12), "нет бюджетного R до расходов"
        assert math.isclose(t.get("pR", np.nan), t["pnl"] / (t["qty"] * d), abs_tol=1e-12), "нет ценового R после"
        assert math.isclose(t.get("pR_gross", np.nan), (t["exit_raw"] - t["entry_raw"]) / d, abs_tol=1e-12)
        assert math.isclose(t["R"], t["pnl"] / t["r_usd"], abs_tol=1e-12)
        assert t["entry_raw"] == 104.0 and math.isclose(t["entry"], 104.0 * (1 + sb.SLIP))


def test_stats_report_both_r_units_from_the_net_ledger():
    tr = _trades()
    st = sb.stats(tr, 3000.0, split_ts=0)
    assert {"exp_R_gross", "exp_pR", "exp_pR_gross"} <= set(st), "stats не публикует обе нормировки R"
    assert math.isclose(st["exp_R_gross"], np.mean([t["R_gross"] for t in tr]), abs_tol=1e-12)
    assert math.isclose(st.get("exp_pR", np.nan), np.mean([t["pR"] for t in tr]), abs_tol=1e-12)
    assert math.isclose(st.get("exp_pR_gross", np.nan), np.mean([t["pR_gross"] for t in tr]), abs_tol=1e-12)
    assert st["exp_R"] == np.mean([t["R"] for t in tr])
    assert st.get("n_weeks") == 1
