"""Протокол §Исполнение и риск: одна позиция на ETH+XRP (первое по времени; во время позиции новых событий нет),
дневной лимит — после реализованного убытка дня ≥ лимита × equity на 00:00 UTC новых входов нет до конца суток.
Контроль C1 идёт через тот же replay()/simulate(). Плюс статистика: недели, статус."""
import math

import numpy as np

from tests.research_manual.mp_fx import H4, MIN, START, flat_minutes, ms, rp, set_min, sym_from_minutes

T1 = START + 6 * H4                                     # 2024-05-16 00:00 UTC, i4 = 5


def _syms(events: dict, dips=()):
    out = []
    for name in events:
        m = flat_minutes(4320)
        for t in dips:
            set_min(m, t, l=98.0)
        s = sym_from_minutes(m, name=name)
        for _, side, i4 in events[name]:
            s.b4["l"][i4], s.b4["h"][i4] = 99.0, 101.0
        out.append(s)
    return out


def _patch(monkeypatch, events):
    monkeypatch.setattr(rp, "detect_events", lambda s, need_adx, cfg=rp.CFG: list(events.get(s.name, [])))


def test_portfolio_single_position_first_in_time(monkeypatch):
    ev = {"ETHUSDT": [(T1, 1, 5)],
          "XRPUSDT": [(T1, 1, 5), (T1 + H4, 1, 6), (T1 + 2 * H4, 1, 7)]}
    _patch(monkeypatch, ev)
    r = rp.replay(_syms(ev), "C1", rp.BASE)
    assert [(x["sym"], x["entry_ts"], x["kind"]) for x in r["trades"]] == [
        ("ETHUSDT", T1, "TIME"), ("XRPUSDT", T1 + 2 * H4, "TIME")]
    assert r["counts"]["skip_busy"] == 1                 # XRP в ту же минуту — ETH раньше по порядку
    assert r["counts"]["ignored_in_position"] == 1       # событие XRP во время позиции ETH
    assert r["trades"][0]["exit_ts"] == T1 + 480 * MIN   # выход по времени освобождает слот ровно в T1 + 8 ч


def test_per_symbol_run_is_independent(monkeypatch):
    ev = {"XRPUSDT": [(T1, 1, 5), (T1 + H4, 1, 6), (T1 + 2 * H4, 1, 7)]}
    _patch(monkeypatch, ev)
    r = rp.replay(_syms(ev), "C1", rp.BASE)
    assert [x["entry_ts"] for x in r["trades"]] == [T1, T1 + 2 * H4]
    assert r["trades"][0]["q"] == int(r["trades"][0]["q"])          # XRP — шаг 1


def _daily(monkeypatch, cfg):
    t4 = START + 12 * H4                                 # следующие сутки 00:00
    ev = {"ETHUSDT": [(T1, 1, 5), (T1 + H4, 1, 6), (T1 + 2 * H4, 1, 7), (t4, 1, 11)]}
    _patch(monkeypatch, ev)
    dips = [T1 + 60 * MIN, T1 + H4 + 60 * MIN, T1 + 2 * H4 + 60 * MIN, t4 + 60 * MIN]
    return rp.replay(_syms(ev, dips), "C1", rp.BASE, cfg), t4


def test_daily_loss_limit_blocks_rest_of_day(monkeypatch):
    r, t4 = _daily(monkeypatch, rp.Cfg(daily=0.004))
    assert [(x["entry_ts"], x["kind"]) for x in r["trades"]] == [(T1, "SL"), (T1 + H4, "SL"), (t4, "SL")]
    assert r["counts"]["skip_daily_limit"] == 1
    lost = sum(x["pnl"] for x in r["trades"][:2])
    assert lost <= -0.004 * 3000 and all(math.isclose(x["R"], -1.0) for x in r["trades"])
    assert math.isclose(r["trades"][1]["B"], 0.0025 * (3000 + r["trades"][0]["pnl"]))     # сложный процент


def test_daily_limit_not_hit_with_protocol_value(monkeypatch):
    r, _ = _daily(monkeypatch, rp.CFG)                  # 0.75%: двух стопов по 0.25% мало
    assert len(r["trades"]) == 4 and "skip_daily_limit" not in r["counts"]


def test_strategy_end_to_end_entry_at_open_after_confirmation(monkeypatch):
    ev = {"ETHUSDT": [(T1, 1, 5)]}
    _patch(monkeypatch, ev)
    k1 = (T1 - START) // rp.M15
    t_entry = START + (k1 + 5) * rp.M15                 # open свечи №6 (подтверждение — №5)
    m = flat_minutes(4320)
    set_min(m, t_entry, o=101.57)
    s = sym_from_minutes(m)
    s.b4["l"][5], s.b4["h"][5] = 95.0, 101.0
    bars = [(101.0, 101.5, 100.5, 101.0), (101.0, 101.5, 100.5, 101.0), (101.0, 101.5, 99.9, 101.0),
            (101.0, 101.0, 99.8, 100.8), (100.8, 101.6, 100.5, 101.55)]
    for k, (o, h, l, c) in enumerate(bars):
        for key, v in (("o", o), ("h", h), ("l", l), ("c", c)):
            s.b15[key][k1 + k] = v
        s.ema15[k1 + k], s.atr15[k1 + k] = 100.0, 0.5
    r = rp.replay([s], "S", rp.BASE)
    assert len(r["trades"]) == 1 and r["counts"]["confirm"] == 1
    x = r["trades"][0]
    assert (x["entry_ts"], x["raw"], x["touch"], x["confirm"]) == (t_entry, 101.57, 4, 5)
    assert math.isclose(x["S"], 99.8 - 0.05) and math.isclose(x["E"], 101.57 * 1.0002)
    assert x["kind"] == "TIME" and x["exit_ts"] == t_entry + 480 * MIN


def test_weekly_ci_counts_empty_calendar_weeks_and_is_deterministic():
    start, end = START, START + 70 * rp.DAY
    ts = [START + d * rp.DAY for d in (1, 2, 15, 30, 31, 50)]
    R = [1.0, -1.0, 2.0, -1.0, -1.0, 0.5]
    a = ms.weekly_ci(ts, R, start, end, draws=500)
    b = ms.weekly_ci(ts, R, start, end, draws=500)
    assert a == b and a["weeks_all"] == 11 and a["weeks_nonempty"] == 4
    assert a["all"][0] <= np.mean(R) <= a["all"][1]


def _fake_summary(mean, hold, n=150, ci=(0.05, 0.3), c3=0.01, slip2=0.1, c1=-0.1, c2=0.0, weeks=40):
    run = lambda m, h=None: {"n": n, "mean_R": m, "holdout": {"mean_R": h},                 # noqa: E731
                             "weekly_ci": {"all": list(ci), "weeks_nonempty": weeks}}
    return {"runs": {"S_PORT_base": run(mean, hold), "S_PORT_slip2": run(slip2), "C1_PORT_base": run(c1),
                     "C2_PORT_base": run(c2)}, "c3": {"PORT": {"rank": c3}}}


def test_status_labels():
    assert ms.status(_fake_summary(0.2, 0.1), "PORT")["label"] == "Кандидат на бумажный forward"
    assert ms.status(_fake_summary(-0.01, 0.1), "PORT")["label"] == "Отвергнута"
    assert ms.status(_fake_summary(0.2, -0.05), "PORT")["label"] == "Отвергнута"
    assert ms.status(_fake_summary(0.2, 0.1, n=80), "PORT")["label"] == "Недостаточно данных"
    assert ms.status(_fake_summary(0.2, 0.1, ci=(-0.05, 0.4)), "PORT")["label"] == "Недостаточно данных"
    st = ms.status(_fake_summary(0.2, 0.1, c3=0.2), "PORT")
    assert st["label"] == "Не квалифицирована" and st["failed"] == ["ранг C3 ≤ 0.05"]
