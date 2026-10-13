"""П.4 разбора GPT 13.10 (§5, EOF 238–241 и цикл сигналов 156): (а) ликвидация на конце данных — рыночный выход с
комиссией тейкера и проскальзыванием, как любой рыночный выход; (б) конец периода не отрезает последние 4 свечи целиком —
сигнал пропускается (и считается) только если его подтверждение/вход не помещаются в данные."""
import math

from tests.research_gold.gold_fx import POST_CUT_DAY, block, combine, first_trade, normal_fixture, set_bar, sb

D = POST_CUT_DAY


def test_end_of_data_liquidation_pays_taker_fee_and_slippage():
    a = normal_fixture(D, minutes=90)                          # позиция открыта в 00:30, данные кончаются в 01:29
    t = first_trade(a, "PAXG")
    assert t["why"] == "конец данных"
    taker = sb.INST["PAXG"]["taker"]
    raw_end = float(a["close"][-1])
    exit_px = raw_end * (1 - sb.SLIP)
    fee = t["entry"] * t["qty"] * taker + exit_px * t["qty"] * taker
    expected = (exit_px - t["entry"]) * t["qty"] - fee
    assert math.isclose(t["pnl"], expected, abs_tol=1e-9), f"PnL {t['pnl']:.6f} без выходных затрат, нужно {expected:.6f}"


def _seven_bars():
    # свечи: 0 (день D), 1..6 (день D+1, минуты 0..89); сигнал — свеча 3, подтверждение 4, вход 5, последняя 6
    a = combine(block(D, 0, 15, 100), block(D + 1, 0, 90, 104))
    set_bar(a, D + 1, 30, o=100.5, h=101, l=99, c=100.5)
    set_bar(a, D + 1, 45, o=100.5, h=102, l=99.5, c=101.5)
    return a


def test_signal_with_available_confirmation_and_entry_near_end_is_traded():
    out = sb.simulate(sb.Market(_seven_bars(), "PAXG", False), "A", 3000.0, "net")
    assert len(out["trades"]) == 1, "сигнал за 4 свечи до конца отброшен целиком"
    t = out["trades"][0]
    assert t["entry_ts"] == (D + 1) * sb.DAY + 60 * sb.MIN


def test_signal_without_entry_bar_is_censored_and_counted():
    a = _seven_bars()
    keep = a["ts"] < (D + 1) * sb.DAY + 60 * sb.MIN              # данные кончаются на подтверждающей свече
    a = {k: v[keep] for k, v in a.items()}
    out = sb.simulate(sb.Market(a, "PAXG", False), "A", 3000.0, "net")
    assert out["trades"] == []
    assert out.get("censored") == 1, "сигнал, у которого вход не помещается в данные, не посчитан"
