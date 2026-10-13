"""П.6 разбора GPT 13.10 (§5, отмена/вход 172/191–215 и timeout 220–224).
(а) Протокол отменяет сигнал только до подтверждения (основной прогон), ТЗ — до ВХОДА. Сделки, где open свечи входа уже
ниже low сигнальной, помечаются; чувствительность по ТЗ (`cancel_rule = "spec"`) отменяет их и считает отменённые.
(б) Выход по времени через разрыв данных позже 4 ч + 5 мин — помечается и считается."""
from tests.research_gold.gold_fx import POST_CUT_DAY, block, combine, first_trade, normal_fixture, set_bar, sb

D = POST_CUT_DAY


def _entry_below_signal_low():
    a = normal_fixture(D)
    set_bar(a, D + 1, 30, o=98.99, h=99.10, l=98.99, c=99.04)   # open свечи входа ниже low сигнальной (99)
    return a


def test_protocol_run_takes_but_flags_entry_below_signal_low():
    t = first_trade(_entry_below_signal_low(), "PAXG")
    assert t["entry_ts"] == (D + 1) * sb.DAY + 30 * sb.MIN
    assert t.get("entry_below_sig_low") is True, "сделка, которую ТЗ отменило бы, не помечена"


def test_spec_cancel_sensitivity_cancels_and_counts():
    m = sb.Market(_entry_below_signal_low(), "PAXG", False)
    m.cancel_rule = "spec"
    out = sb.simulate(m, "A", 3000.0, "net")
    assert out["trades"] == [], "по правилу ТЗ вход ниже low сигнальной отменяется"
    assert out.get("spec_cancelled") == 1


def test_time_exit_across_data_gap_is_flagged_late():
    a = combine(normal_fixture(D, minutes=120), block(D + 2, 0, 90, 104.0))
    t = first_trade(a, "PAXG")
    assert t["why"] == "время" and (t["exit_ts"] - t["entry_ts"]) / 3_600_000 == 23.5
    assert t.get("late_time_exit") is True, "выход через разрыв данных позже 4 ч не помечен"
    st = sb.stats([t], 3000.0, split_ts=0)
    assert st.get("late_time_exits") == 1


def test_regular_time_exit_is_not_late():
    t = first_trade(normal_fixture(D), "PAXG")
    assert t["why"] == "время" and t.get("late_time_exit") is False
