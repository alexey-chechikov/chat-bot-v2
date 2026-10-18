"""Протокол §2–§3 (docs/TREND_4H_RECHECK_PROTOCOL_2026-10-15.md): вход по open следующей минуты, пропуск за
Chandelier, храповик только в пользу ≥ 0.2%, аварийный стоп внутри свечи раньше проверки закрытия, гэп через стоп по
open, выход по закрытию по ТЕКУЩЕМУ Chandelier, нет входа на свече выхода, размер, фандинг, неполная свеча, конец
данных. Один цикл исполнения research/trend_recheck/replay.py."""
import math
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from tests.research_trend.tr_fx import H4, MIN, START, flat, mi, rp, series, setm, drop, st

BASE = rp.BASE
SIG = 120                                     # свеча сигнала (первая после прогрева)
T_IN = START + (SIG + 1) * H4                 # первая минута после закрытия свечи сигнала


def long_signal(m, close=101.5, entry_open=101.2):
    setm(m, mi(SIG, 239), c=close)            # close 101.5 > HH 101, high 101.5 → пик
    setm(m, mi(SIG + 1, 0), o=entry_open)
    return m


def test_entry_at_next_minute_open_and_size():
    m = long_signal(flat())
    s = series(m)
    out = rp.run(s, BASE)
    t = out["trades"][0]
    assert t["entry_ts"] == T_IN and t["E"] == 101.2 and t["side"] == "LONG"
    assert t["ch0"] == pytest.approx(98.5)                         # пик 101.5 − 3·ATR 1
    assert t["trig0"] == 97.02                                      # 98.5·0.985 = 97.0225 → вниз к тику
    q = min(50 / (101.2 - 97.02 + 2 * 0.0005 * 101.2), 3000 / 101.2)
    assert t["qty"] == pytest.approx(math.floor(q / 0.001 + 1e-9) * 0.001) and t["qty"] == 11.678   # 11.6789 → вниз
    assert t["entry_fill"] == pytest.approx(101.2 * 1.0002)
    assert t["censored"] and t["kind"] == rp.CENS                   # цена дальше не дошла ни до стопа, ни до выхода
    assert out["funnel"]["signals"] == 1 and out["funnel"]["entered"] == 1


def test_no_entry_inside_warmup():
    m = flat()
    setm(m, mi(SIG - 1, 239), c=101.5)
    s = series(m)
    assert rp.run(s, BASE)["funnel"]["signals"] == 0


@pytest.mark.parametrize("open_px", [98.5, 98.4])
def test_skip_when_open_already_beyond_initial_chandelier(open_px):
    m = long_signal(flat(), entry_open=open_px)                    # Chandelier₀ = 98.5; open ≤ 98.5 → пропуск
    s = series(m)
    out = rp.run(s, BASE)
    assert out["trades"] == []
    assert out["funnel"]["skip_beyond_chandelier"] == 1


def test_short_skip_mirror():
    m = flat()
    setm(m, mi(SIG, 239), c=98.5)                                  # close < LL 99, low 98.5 → пик SHORT
    setm(m, mi(SIG + 1, 0), o=101.5)                                # Chandelier₀ = 98.5 + 3 = 101.5 → open ≥ → пропуск
    out = rp.run(series(m), BASE)
    assert out["trades"] == [] and out["funnel"]["skip_beyond_chandelier"] == 1


def _open_long(m, **kw):
    s = series(m, **kw)
    p = rp.open_trade(s, SIG, 1, BASE)
    assert isinstance(p, rp.Pos)
    return s, p


def test_ratchet_only_in_favour_and_at_least_0_2pct():
    m = long_signal(flat())
    setm(m, mi(SIG + 1, 50), h=101.6)          # Ch 98.6: +0.10% — не переставлять
    setm(m, mi(SIG + 2, 50), h=101.8)          # Ch 98.8: +0.30% от учтённого 98.5 — переставить
    s, p = _open_long(m)
    s.atr[SIG + 3] = 1.2                       # Ch 101.8 − 3.6 = 98.2 — против позиции, не переставлять
    assert rp.step_bar(s, p, SIG + 1, BASE) is None
    assert (p.last_ch, p.trig, p.n_ratchet) == (98.5, 97.02, 0)
    assert rp.step_bar(s, p, SIG + 2, BASE) is None
    assert p.last_ch == pytest.approx(98.8) and p.trig == 97.31 and p.n_ratchet == 1   # 98.8·0.985 = 97.318 → 97.31
    assert rp.step_bar(s, p, SIG + 3, BASE) is None
    assert p.ch == pytest.approx(98.2) and p.last_ch == pytest.approx(98.8) and p.trig == 97.31


def test_new_trigger_acts_from_minute_after_close():
    m = long_signal(flat())
    setm(m, mi(SIG + 2, 50), h=101.8)          # храповик на закрытии свечи SIG+2 → триггер 97.31
    setm(m, mi(SIG + 2, 60), l=97.25)          # в свече SIG+2 действует старый 97.02 — нет срабатывания
    setm(m, mi(SIG + 3, 7), l=97.30)           # в следующей свече — новый 97.31 → срабатывание
    t = rp.run(series(m), BASE)["trades"][0]
    assert t["kind"] == rp.STOP and t["exit_raw"] == 97.31
    assert t["exit_ts"] == START + (SIG + 3) * H4 + 7 * MIN


def test_emergency_stop_inside_bar_before_close_check():
    m = long_signal(flat())
    setm(m, mi(SIG + 1, 100), l=96.9)          # триггер 97.02, open 100 → по триггеру
    for k in range(101, 240):
        setm(m, mi(SIG + 1, k), o=97.0, h=97.0, l=97.0, c=97.0)    # закрытие 97 < Ch 98.5 — тоже был бы выход
    t = rp.run(series(m), BASE)["trades"][0]
    assert t["kind"] == rp.STOP and t["exit_raw"] == 97.02
    assert t["exit_ts"] == START + (SIG + 1) * H4 + 100 * MIN
    assert t["exit_fill"] == pytest.approx(97.02 * (1 - 0.0002))


def test_gap_through_stop_fills_at_open():
    m = long_signal(flat())
    setm(m, mi(SIG + 1, 100), o=96.5, l=96.4, c=96.6)
    t = rp.run(series(m), BASE)["trades"][0]
    assert t["kind"] == rp.GAP and t["exit_raw"] == 96.5


def test_short_gap_through_stop_fills_at_open():
    m = flat()
    setm(m, mi(SIG, 239), c=98.5)                                  # пик SHORT 98.5, Ch₀ 101.5, триггер 103.0225 → 103.03
    setm(m, mi(SIG + 1, 0), o=98.8)
    setm(m, mi(SIG + 1, 30), o=103.5, h=103.6, c=103.4)
    t = rp.run(series(m), BASE)["trades"][0]
    assert t["side"] == "SHORT" and t["trig0"] == 103.03
    assert t["kind"] == rp.GAP and t["exit_raw"] == 103.5
    assert t["exit_fill"] == pytest.approx(103.5 * 1.0002) and t["R"] < 0


def test_no_stop_check_in_entry_minute():
    m = long_signal(flat())
    setm(m, mi(SIG + 1, 0), l=96.0)            # минута входа ниже триггера — проверка только со следующей минуты
    t = rp.run(series(m), BASE)["trades"][0]
    assert t["censored"]


def test_close_exit_at_next_minute_open():
    m = long_signal(flat())
    setm(m, mi(SIG + 1, 239), c=98.4, l=98.4)  # закрытие 98.4 < Ch 98.5, минимум выше триггера 97.02
    setm(m, mi(SIG + 2, 0), o=98.3)
    t = rp.run(series(m), BASE)["trades"][0]
    assert t["kind"] == rp.CLOSE and t["exit_raw"] == 98.3 and t["exit_ts"] == START + (SIG + 2) * H4


def test_close_exit_uses_current_chandelier_even_if_it_moved_against():
    m = long_signal(flat())
    setm(m, mi(SIG + 1, 50), h=102.5)          # Ch 99.5 → храповик (учтён 99.5, триггер 98.00)
    setm(m, mi(SIG + 2, 239), c=98.5, l=98.5)  # закрытие 98.5 < учтённого 99.5, но > текущего 96.5
    s, p = _open_long(m)
    s.atr[SIG + 2] = 2.0                       # текущий Ch = 102.5 − 6 = 96.5
    assert rp.step_bar(s, p, SIG + 1, BASE) is None and p.trig == 98.0
    assert rp.step_bar(s, p, SIG + 2, BASE) is None                 # выхода нет
    assert p.ch == pytest.approx(96.5) and p.last_ch == pytest.approx(99.5) and p.trig == 98.0


def test_no_reentry_on_exit_bar():
    m = long_signal(flat())
    setm(m, mi(SIG + 1, 100), l=96.9)          # аварийный стоп LONG в свече SIG+1
    for k in range(mi(SIG + 1, 101), len(m["ts"])):
        m["o"][k] = m["h"][k] = m["l"][k] = m["c"][k] = 98.0       # закрытия 98 < LL 99 — условие SHORT
    trades = rp.run(series(m), BASE)["trades"]
    assert trades[0]["kind"] == rp.STOP and trades[0]["exit_bar"] == SIG + 1
    assert trades[1]["side"] == "SHORT" and trades[1]["signal_bar_idx"] == SIG + 2      # не SIG+1
    assert trades[1]["entry_ts"] == START + (SIG + 3) * H4


def test_qty_rounding_and_cap():
    cfg = BASE
    assert rp.size_qty(2000.0, 1900.0, 0.001, cfg) == 0.49           # 50/102 = 0.4902 → 0.490
    assert rp.size_qty(2000.0, 1999.0, 0.001, cfg) == 1.5            # 50/3 = 16.7 → потолок 3000/2000
    assert rp.size_qty(0.5, 0.45, 10.0, cfg) == 990.0                # XRP: 50/0.0505 = 990.1 → 990
    assert rp.size_qty(0.5, 0.4999, 10.0, cfg) == 6000.0             # потолок 3000/0.5
    assert rp.size_qty(100.0, 50.0, 10.0, cfg) == 0.0                # 0.998 при шаге 10 → 0


def test_qty_zero_skips():
    m = long_signal(flat())
    s = series(m, step=10.0, atr=10.0)          # q = 50/(101.2 − 70.42 + 0.1) ≈ 1.6 → при шаге 10 → 0
    out = rp.run(s, BASE)
    assert out["trades"] == [] and out["funnel"]["skip_qty0"] == 1


def test_trigger_rounding_away_from_price():
    assert rp.round_away(97.0225, 0.01, 1) == 97.02
    assert rp.round_away(103.0225, 0.01, -1) == 103.03
    assert rp.round_away(97.02, 0.01, 1) == 97.02 and rp.round_away(103.03, 0.01, -1) == 103.03
    assert rp.round_away(0.512349, 0.0001, 1) == 0.5123 and rp.round_away(0.512341, 0.0001, -1) == 0.5124


def _funding_series(rate=0.0001, mark=100.0, jitter=47):
    m = flat()
    times = START + np.arange(1, 130 * 6) * 8 * 3_600_000 // 2      # каждые 4 ч (для простоты)
    f = pd.DataFrame({"fundingTime": times + jitter, "fundingRate": rate, "markPrice": mark})
    return m, f


def test_funding_sign_and_window():
    m, f = _funding_series()
    s = series(m, funding=f)
    t1 = START + 4 * H4                          # метка начисления (после округления вниз до минуты)
    assert s.funding(1, 2.0, t1 - MIN, t1) == (pytest.approx(-0.02), 1)    # LONG платит при rate > 0
    assert s.funding(-1, 2.0, t1 - MIN, t1) == (pytest.approx(0.02), 1)    # SHORT получает
    assert s.funding(1, 2.0, t1, t1 + MIN) == (0.0, 0)                     # вход в минуту начисления — не платит
    m2, f2 = _funding_series(rate=-0.0002)
    s2 = series(m2, funding=f2)
    assert s2.funding(1, 1.0, t1 - MIN, t1)[0] == pytest.approx(0.02)      # rate < 0 — LONG получает


def test_funding_without_mark_uses_close_of_settlement_minute():
    m, f = _funding_series(mark=np.nan)
    t1 = START + 4 * H4
    setm(m, (t1 - START) // MIN, c=120.0)
    s = series(m, funding=f)
    assert s.funding(1, 1.0, t1 - MIN, t1)[0] == pytest.approx(-0.0001 * 120.0)


def test_trade_accounting_R_definition():
    m = long_signal(flat())
    setm(m, mi(SIG + 1, 239), c=98.4, l=98.4)
    setm(m, mi(SIG + 2, 0), o=98.3)
    t = rp.run(series(m), BASE)["trades"][0]
    q, E = t["qty"], 101.2
    ef, xf = E * 1.0002, 98.3 * 0.9998
    net = q * (xf - ef) - (ef + xf) * q * 0.00048
    assert t["net"] == pytest.approx(net)
    assert t["R"] == pytest.approx(net / (q * (E - 97.02 + 2 * 0.0005 * E)))


def test_incomplete_bar_suppresses_signal():
    m = drop(long_signal(flat()), mi(SIG, 5))     # свеча сигнала без одной минуты — неполная
    out = rp.run(series(m), BASE)
    assert out["trades"] == [] and out["funnel"]["signal_on_incomplete_bar"] == 1


def test_incomplete_bar_defers_close_exit_to_next_complete_bar():
    m = long_signal(flat())
    for b in (SIG + 1, SIG + 2):
        setm(m, mi(b, 239), c=98.4, l=98.4)
    setm(m, mi(SIG + 3, 0), o=98.2)
    m = drop(m, mi(SIG + 1, 5))                   # свеча SIG+1 неполная: выход по закрытию не исполняется
    t = rp.run(series(m), BASE)["trades"][0]
    assert t["kind"] == rp.CLOSE and t["exit_raw"] == 98.2 and t["exit_ts"] == START + (SIG + 3) * H4
    assert t["deferred_exits"] == 1


def test_incomplete_bar_keeps_emergency_stop():
    m = long_signal(flat())
    setm(m, mi(SIG + 1, 100), l=96.9)
    m = drop(m, mi(SIG + 1, 5))
    t = rp.run(series(m), BASE)["trades"][0]
    assert t["kind"] == rp.STOP and t["exit_raw"] == 97.02


def test_censored_at_end_not_in_n():
    m = long_signal(flat())
    out = rp.run(series(m), BASE)
    b = st.block(out["trades"])
    assert b["n"] == 0 and b["censored"] == 1 and b["mean_R"] is None
    t = out["trades"][0]
    assert t["exit_raw"] == 100.0 and t["fee_out"] == 0.0


def test_close_exit_on_last_bar_is_censored():
    m = long_signal(flat())
    setm(m, mi(129, 239), c=98.4, l=98.4)         # последняя свеча: выход по закрытию, следующей минуты нет
    t = rp.run(series(m), BASE)["trades"][0]
    assert t["censored"] and t["exit_signal_at_end"]


def test_entry_delay_5_minutes():
    m = long_signal(flat())
    setm(m, mi(SIG + 1, 5), o=101.3)
    t = rp.run(series(m), replace(BASE, delay_min=5))["trades"][0]
    assert t["entry_ts"] == T_IN + 5 * MIN and t["E"] == 101.3


def test_no_emergency_variant_keeps_planned_risk():
    m = long_signal(flat())
    setm(m, mi(SIG + 1, 100), l=96.9)
    setm(m, mi(SIG + 1, 239), c=98.4, l=98.4)
    setm(m, mi(SIG + 2, 0), o=98.3)
    t = rp.run(series(m), replace(BASE, emergency=False))["trades"][0]
    assert t["kind"] == rp.CLOSE and t["trig0"] == 97.02 and t["exit_raw"] == 98.3


def test_live_episode_machine_ignores_emergency_stop():
    m = long_signal(flat())
    setm(m, mi(SIG + 1, 100), l=96.9)             # аварийный стоп у бэктеста; закрытие 100 > Ch — живой эпизод идёт
    s = series(m)
    eps = rp.live_episodes(s, BASE)
    assert eps == [(SIG, 1, -1)]
