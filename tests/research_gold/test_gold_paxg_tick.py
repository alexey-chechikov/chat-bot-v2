"""П.5 разбора GPT 13.10 (§5, константный tick; G2 отчёта): у PAXGUSDT шаг цены 1.00 до 2025-05-16 05:06 UTC и 0.01
после. Стоп = low сигнальной − 2 тика ДЕЙСТВУЮЩЕГО шага; цель округляется ВВЕРХ до шага; лимитная цель исполняется,
только если 1m high ≥ цель + 1 тик того же шага."""
import math

from tests.research_gold.gold_fx import POST_CUT_DAY, PRE_CUT_DAY, block, combine, first_trade, set_bar, set_minute


def _fixture(day0: int, frac: float = 0.0):
    a = combine(block(day0, 0, 15, 2000 + frac), block(day0 + 1, 0, 360, 2010 + frac))
    set_bar(a, day0 + 1, 0, o=2001 + frac, h=2003 + frac, l=1998 + frac, c=2001 + frac)
    set_bar(a, day0 + 1, 15, o=2001 + frac, h=2006 + frac, l=1999 + frac, c=2005 + frac)
    return a


def test_pre_cut_stop_is_two_one_dollar_ticks_and_target_rounds_up_to_dollar():
    t = first_trade(_fixture(PRE_CUT_DAY), "PAXG")
    assert t["stop"] == 1996.0, f"стоп {t['stop']} — шаг 0.01 вместо действовавшего 1.00"
    raw_target = t["entry"] + 2 * (t["entry"] - t["stop"])
    assert t["target"] == math.ceil(raw_target), f"цель {t['target']} не округлена вверх до шага 1.00"


def test_post_cut_stop_uses_cent_tick_and_target_rounds_up_to_cent():
    t = first_trade(_fixture(POST_CUT_DAY, frac=0.37), "PAXG")
    assert math.isclose(t["stop"], 1998.37 - 0.02, abs_tol=1e-9)
    raw_target = t["entry"] + 2 * (t["entry"] - t["stop"])
    cents = t["target"] * 100
    assert abs(cents - round(cents)) < 1e-6 and raw_target <= t["target"] < raw_target + 0.01 + 1e-9


def test_pre_cut_target_fill_needs_one_dollar_through_the_rounded_target():
    a = _fixture(PRE_CUT_DAY)
    probe = first_trade(a, "PAXG")
    tgt = math.ceil(probe["entry"] + 2 * (probe["entry"] - 1996.0))
    set_minute(a, PRE_CUT_DAY + 1, 100, high=float(tgt))         # касание цели — не исполнение
    set_minute(a, PRE_CUT_DAY + 1, 120, high=float(tgt + 1))     # +1 тик — исполнение
    t = first_trade(a, "PAXG")
    assert t["why"] == "цель" and t["exit"] == float(tgt)
    assert t["exit_ts"] == (PRE_CUT_DAY + 1) * 86_400_000 + 120 * 60_000
