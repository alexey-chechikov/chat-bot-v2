"""Сигналы BTC: правила системы на искусственных часах и отправка без повторов."""
from __future__ import annotations

import json

import numpy as np
import pytest

from services.btc_signals import engine as en
from services.btc_signals import run as rn

T0 = 1_700_000_000 // 14400 * 14400


def mk(n=24, F=100.0, B=90.0, price=100.0):
    a = {
        "t": T0 + 3600 * (np.arange(n) + 1),
        "c": np.full(n, price), "h": np.full(n, price), "l": np.full(n, price), "o": np.full(n, price),
        "j": np.arange(n) // 4,
        "f_close": np.full(n, F), "f_B": np.full(n, B), "atr4": np.full(n, 1.0), "B4p": np.full(n, 95.0),
        "f_G": np.full(n, 99.0), "f_Y": np.full(n, 98.0), "f_R": np.full(n, 97.0),
        "f_run_G": np.zeros(n), "f_run_Y": np.zeros(n), "f_run_R": np.zeros(n), "f_run_B": np.zeros(n),
        "i0": 0,
    }
    lay = (np.zeros(n), np.full(n, en.DIV))
    return a, lay


def long_case():
    a, lay = mk()
    a["f_run_G"][4] = 2
    a["h"][10], a["o"][10] = 103.0, 101.0
    a["f_run_R"][16] = -2
    a["c"][16] = 105.0
    return a, lay


def test_long_entry_add_exit():
    a, lay = long_case()
    ev, pos = en.simulate(a, lay)
    assert [e["kind"] for e in ev] == ["вход", "добор", "выход"]
    assert ev[0]["i"] == 4 and ev[0]["px"] == 100.0 and ev[0]["pos"]["add_lv"] == 102.0
    assert ev[1]["i"] == 10 and ev[1]["px"] == 102.0
    ex = ev[2]
    assert ex["i"] == 16 and ex["px"] == 105.0 and ex["why"] == "2 закрытия 4ч под красной"
    want = en.leg_net(1, 100.0, 105.0) * 0.5 + en.leg_net(1, 102.0, 105.0) * 0.5
    assert ex["res"] == pytest.approx(want)
    assert pos is None


def test_add_not_taken_on_exit_bar():
    a, lay = long_case()
    a["h"][10] = 100.0
    a["h"][16] = 110.0
    ev, _ = en.simulate(a, lay)
    assert [e["kind"] for e in ev] == ["вход", "выход"]
    assert ev[1]["res"] == pytest.approx(en.leg_net(1, 100.0, 105.0) * 0.5)


def test_cs_target_inside_4h():
    a, lay = mk()
    a["f_run_Y"][4] = -2
    a["l"][6], a["o"][6] = 95.0, 96.0
    ev, pos = en.simulate(a, lay)
    assert [(e["kind"], e["tag"]) for e in ev] == [("вход", "под жёлтой"), ("выход", "под жёлтой")]
    lv = 95.0 * 1.005
    assert ev[1]["i"] == 6 and ev[1]["px"] == pytest.approx(lv)
    assert ev[1]["res"] == pytest.approx(en.leg_net(-1, 100.0, lv))
    assert pos is None


def test_short_under_blue_rank_gate():
    a, lay = mk(F=80.0, price=80.0)
    a["f_run_G"][4] = -2
    rk = np.zeros(24)
    rk[4] = 0.7
    ev, pos = en.simulate(a, (rk, lay[1]))
    assert ev == [] and pos is None
    rk[4] = 0.6
    ev, pos = en.simulate(a, (rk, lay[1]))
    assert [e["kind"] for e in ev] == ["вход"] and pos["tag"] == "под синей" and pos["add_lv"] == 78.0


def test_last_closed_hour_skips_partial_line(tmp_path):
    p = tmp_path / "m.csv"
    p.write_text("ts,open,high,low,close,volume\n1794085140000,1,1,1,1,1\n1794085200000,1,1,1,1,1\n17940852")
    assert rn.last_closed_hour(p) == 1794085260 // 3600 * 3600


def slice_a(a, m):
    return {k: (v[:m] if isinstance(v, np.ndarray) else v) for k, v in a.items()}


def wire(monkeypatch, tmp_path, a, lay, box, send, weekly=False):
    def compute():
        b = slice_a(a, box["m"])
        ly = (lay[0][:box["m"]], lay[1][:box["m"]])
        ev, pos = en.simulate(b, ly)
        ev432, pos432, lv432 = en.simulate432(b)
        ev_v2, pos_v2 = en.simulate(b, ly, lx_blue=True)
        return {"a": b, "lay": ly, "h4f": None, "ev": ev, "pos": pos, "ev432": ev432, "pos432": pos432, "lv432": lv432, "ev_v2": ev_v2, "pos_v2": pos_v2}

    hour = lambda path=None: int(a["t"][box["m"] - 1])  # noqa: E731
    monkeypatch.setattr(rn, "STATE", tmp_path / "st.json")
    monkeypatch.setattr(rn, "JOURNAL", tmp_path / "j.jsonl")
    monkeypatch.setattr(rn, "SHADOW", tmp_path / "shadow.jsonl")
    monkeypatch.setattr(rn, "FEATURES", tmp_path / "features.jsonl")
    monkeypatch.setattr(rn, "compute", compute)
    monkeypatch.setattr(rn, "sender", lambda dry: send)
    monkeypatch.setattr(rn, "last_closed_hour", hour)
    monkeypatch.setattr(rn, "_now", lambda: hour() + 600 + box.get("late", 0))
    if not weekly:
        monkeypatch.setattr(rn, "weekly_due", lambda now, st: None)
    monkeypatch.setattr("sys.argv", ["run.py"])


def test_main_sends_each_event_once(tmp_path, monkeypatch):
    a, lay = long_case()
    box = {"m": 3, "ok": True}
    sent = []

    def send(text):
        if box["ok"]:
            sent.append(text)
        return box["ok"]

    wire(monkeypatch, tmp_path, a, lay, box, send)
    assert rn.main() == 0
    assert len(sent) == 1 and sent[0].startswith("📊")
    assert rn.main() == 0 and len(sent) == 1

    box["m"] = 5
    assert rn.main() == 0
    assert len(sent) == 2 and "ЛОНГ над синей — вход" in sent[1]

    box["m"], box["ok"] = 11, False
    assert rn.main() == 1
    st = json.loads((tmp_path / "st.json").read_text())
    assert st["last_hour"] == int(a["t"][4])
    box["ok"] = True
    assert rn.main() == 0
    assert len(sent) == 3 and "добор" in sent[2]

    box["m"] = 17
    assert rn.main() == 0
    assert len(sent) == 4 and "закрыт —" in sent[3]
    rows = [json.loads(x) for x in (tmp_path / "j.jsonl").read_text().splitlines()]
    assert [(r["kind"], r["sent"]) for r in rows] == [("вход", True), ("добор", False), ("добор", True), ("выход", True)]


def test_partial_failure_no_duplicates(tmp_path, monkeypatch):
    """Выход и новый вход на одном часе: выход ушёл, вход нет — при повторе выход не дублируется."""
    a, lay = long_case()
    a["f_run_Y"][16] = -2
    box = {"m": 3}
    sent, fails = [], {"n": 1}

    def send(text):
        if "— вход" in text and len(sent) >= 3 and fails["n"] > 0:
            fails["n"] -= 1
            return False
        sent.append(text)
        return True

    wire(monkeypatch, tmp_path, a, lay, box, send)
    assert rn.main() == 0
    box["m"] = 11
    assert rn.main() == 0
    assert len(sent) == 3
    box["m"] = 17
    assert rn.main() == 1
    assert len(sent) == 4 and "закрыт —" in sent[3]
    assert rn.main() == 0
    assert len(sent) == 5 and "ШОРТ под жёлтой — вход" in sent[4]
    assert sum("закрыт —" in s for s in sent) == 1


def test_shadow_v2_exits_long_under_blue_only_in_shadow():
    a, lay = long_case()
    a["f_run_B"][12] = -2
    ev, _ = en.simulate(a, lay)
    assert ev[-1]["i"] == 16 and ev[-1]["why"] == "2 закрытия 4ч под красной"
    ev2, _ = en.simulate(a, lay, lx_blue=True)
    assert [e["kind"] for e in ev2] == ["вход", "добор", "выход"]
    assert ev2[-1]["i"] == 12 and ev2[-1]["why"] == "2 закрытия 4ч под синей"


def bars_case(closes, start_flat=330):
    """Часы, где все 4 часа свечи 4ч одинаковые: open — прошлое закрытие, high/low — края."""
    nb = len(closes)
    O = np.r_[closes[0], closes[:-1]]
    H = np.maximum(O, closes) + np.where(np.arange(nb) < start_flat, 0.05, 0.0)
    L = np.minimum(O, closes) - np.where(np.arange(nb) < start_flat, 0.05, 0.0)
    rep = lambda x: np.repeat(np.asarray(x, float), 4)  # noqa: E731
    n = nb * 4
    a, lay = mk(n=n)
    a.update({"t": T0 + 3600 * (np.arange(n) + 1), "o": rep(O), "h": rep(H), "l": rep(L), "c": rep(closes), "j": np.arange(n) // 4})
    return a, lay


def ramp(n_ramp, tail=()):
    flat = 100 + 0.3 * np.sin(np.arange(330) * 0.7)
    up = flat[-1] * 1.02 ** np.arange(1, n_ramp + 1)
    return np.r_[flat, up, np.asarray(tail, float)]


def test_bars4_groups_hours_by_close_time():
    a, _ = bars_case(ramp(2))
    b = en.bars4(a)
    assert len(b["c"]) == 332 and b["done"].all()
    assert b["c"][331] == pytest.approx(ramp(2)[-1]) and b["last_i"][331] == 331 * 4 + 3
    a2 = slice_a(a, 331 * 4 + 2)
    b2 = en.bars4(a2)
    assert len(b2["c"]) == 332 and not b2["done"][-1]


def test_432_breakout_then_time_exit():
    a, _ = bars_case(ramp(45))
    ev, _, lv = en.simulate432(a)
    assert [e["kind"] for e in ev[:2]] == ["вход", "выход"]
    k_in, k_out = ev[0]["i"] // 4, ev[1]["i"] // 4
    assert k_in >= 330 and k_out - k_in == 20 and "20 свечей" in ev[1]["why"]
    assert ev[0]["px"] == pytest.approx(a["c"][ev[0]["i"]]) and ev[0]["pos"]["adx"] >= 22
    assert ev[1]["res"] == pytest.approx(en.leg_net(1, ev[0]["px"], ev[1]["px"]))
    assert ev[0]["pos"]["exit_by_t"] == int(a["t"][ev[1]["i"]])


def test_432_channel_exit():
    a, _ = bars_case(ramp(10, tail=[90.0]))
    ev, pos, _ = en.simulate432(a)
    assert [e["kind"] for e in ev] == ["вход", "выход"]
    assert ev[1]["i"] // 4 == 340 and "минимума 30" in ev[1]["why"] and ev[1]["px"] == 90.0
    assert pos is None


def test_432_no_entry_without_trend_strength():
    a, _ = bars_case(ramp(0))
    ev, pos, _ = en.simulate432(a)
    assert ev == [] and pos is None


def test_main_sends_432_once_and_keeps_system(tmp_path, monkeypatch):
    a, lay = bars_case(ramp(45))
    ev = en.simulate432(a)[0]
    k_in, k_out = ev[0]["i"] // 4, ev[1]["i"] // 4
    box = {"m": 330 * 4}
    sent = []
    wire(monkeypatch, tmp_path, a, lay, box, lambda text: sent.append(text) or True)
    assert rn.main() == 0 and len(sent) == 1 and "432: позиции нет" in sent[0]
    box["m"] = (k_in + 1) * 4
    assert rn.main() == 0 and len(sent) == 2 and "432 ЛОНГ — вход" in sent[1]
    st = json.loads((tmp_path / "st.json").read_text())
    assert st["pos432"]["tag"] == "432" and st["pos"] is None
    assert rn.main() == 0 and len(sent) == 2
    box["m"] = (k_out + 1) * 4
    assert rn.main() == 0 and len(sent) == 3 and "лонг 432 закрыт — прошло 20 свечей" in sent[2]
    rows = [json.loads(x) for x in (tmp_path / "j.jsonl").read_text().splitlines()]
    assert [(r["kind"], r["tag"]) for r in rows] == [("вход", "432"), ("выход", "432")]


def test_status_does_not_skip_hours(tmp_path, monkeypatch):
    a, lay = long_case()
    box = {"m": 3}
    sent = []
    wire(monkeypatch, tmp_path, a, lay, box, lambda text: sent.append(text) or True)
    assert rn.main() == 0
    box["m"] = 5
    monkeypatch.setattr("sys.argv", ["run.py", "--status"])
    assert rn.main() == 0 and sent[-1].startswith("📊")
    monkeypatch.setattr("sys.argv", ["run.py"])
    assert rn.main() == 0 and "ЛОНГ над синей — вход" in sent[-1]


def test_weekly_due_monday_after_7_once_per_week():
    mon6, mon8 = 1794204000, 1794211200  # понедельник 09.11.2026 06:00 и 08:00 UTC
    tue = mon8 + 86400
    assert rn.weekly_due(mon6, {}) is None
    lab = rn.weekly_due(mon8, {})
    assert lab == "2026-W46"
    assert rn.weekly_due(tue, {"weekly_for": lab}) is None
    assert rn.weekly_due(tue, {}) == lab


def test_weekly_sent_once_with_reconciliation(tmp_path, monkeypatch):
    a, lay = long_case()
    box = {"m": 3}
    sent = []
    wire(monkeypatch, tmp_path, a, lay, box, lambda text: sent.append(text) or True, weekly=True)
    monkeypatch.setattr(rn, "weekly_due", lambda now, st: None if st.get("weekly_for") == "W" else "W")
    assert rn.main() == 0 and len(sent) == 1
    box["m"] = 17
    assert rn.main() == 0
    weekly = [s for s in sent if s.startswith("📅")]
    assert len(weekly) == 1 and "все 3 событий совпали" in weekly[0] and "Тень" in weekly[0]
    box["m"] = 18
    assert rn.main() == 0
    assert sum(s.startswith("📅") for s in sent) == 1
    shadow = [json.loads(x) for x in (tmp_path / "shadow.jsonl").read_text().splitlines()]
    assert [r["kind"] for r in shadow] == ["вход", "добор", "выход"] and not any(r["sent"] for r in shadow)


def test_stale_data_warns_once(tmp_path, monkeypatch):
    a, lay = long_case()
    box = {"m": 5}
    sent = []
    wire(monkeypatch, tmp_path, a, lay, box, lambda text: sent.append(text) or True)
    assert rn.main() == 0 and len(sent) == 1
    box["late"] = 4 * 3600
    assert rn.main() == 0
    assert rn.main() == 0
    assert len(sent) == 2 and sent[1].startswith("⚠️")
