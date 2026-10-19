"""Прогноз размаха на сутки dr-2 — синтетика, без сети. Регрессии разбора GPT 19.10: зона «из будущего», окно
08:00→08:00 при переводе часов, потерянные проверки."""
import json
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

from services.coinglass_web import day_range as dr

MIN, HOUR = 60_000, 3_600_000
UTC = timezone.utc


def synth_base(first: date, last: date, seed=0, spikes=(), tail_min=0):
    """Минутки от 08:00−16ч первого дня до 08:00 после последнего (+ хвост); блуждание + точечные выбросы."""
    t0 = dr.anchor_ms(first) - 16 * HOUR
    t1 = dr.anchor_ms(last + timedelta(days=1)) + tail_min * MIN
    ts = np.arange(t0, t1, MIN, dtype=np.int64)
    rng = np.random.default_rng(seed)
    cl = 100 + np.cumsum(rng.normal(0, 0.05, len(ts)))
    op = np.r_[cl[0], cl[:-1]]
    hi, lo = np.maximum(op, cl) + 0.02, np.minimum(op, cl) - 0.02
    for t, h in spikes:
        i = int((t - t0) // MIN)
        hi[i] = h
    days = []
    d = first
    while d <= last:
        days.append(d.isoformat())
        d += timedelta(days=1)
    return {"ts": ts, "open": op, "high": hi, "low": lo, "close": cl, "days": days}


@pytest.fixture
def tmp_dr(tmp_path, monkeypatch):
    monkeypatch.setattr(dr, "DIR", tmp_path)
    monkeypatch.setattr(dr, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(dr, "MANIFEST", tmp_path / "manifest.json")
    v = {"joint_inside": 0.76, "test": ["2025-10-14", "2026-10-13"],
         "touch_bins": [{"promised": 0.1, "realized": 0.1, "queries": 5, "days": 5}]}
    (tmp_path / "manifest.json").write_text(json.dumps({"algo": dr.ALGO, "symbols": {
        s: {"npz_sha256": "x", "validation": v} for s in dr.SYMS}}))
    B = synth_base(date(2026, 9, 1), date(2026, 10, 10))
    monkeypatch.setattr(dr, "_B", {s: B for s in dr.SYMS})
    return tmp_path


def fake_klines(calls, p=100.0, hi_at_ms=(), fail=False):
    """Как Binance: 1h с closeTime = open+1ч−1; 1m — полные минуты, выбросы high в заданные минуты."""
    def k(sym, interval, start, end):
        calls.append((interval, start, end))
        if fail:
            raise OSError("сеть")
        if interval == "1h":
            return [[t, "100", "101", "99", "100", "1", t + HOUR - 1] for t in range(start, end, HOUR)]
        return [[t, str(p), str(110.0 if t in hi_at_ms else p + 0.5), str(p - 0.5), str(p)]
                for t in range(start, end, MIN)]
    return k


# ---------------------------------------------------------------- окно до местного 08:00 (DST)
def test_history_window_ends_at_next_local_0800_across_dst():
    an = dr.anchor_ms(date(2026, 10, 24))                           # 24.10 08:00 CEST → 25.10 08:00 CET = 1500 мин
    assert dr.anchor_ms(date(2026, 10, 25)) - an == 1500 * MIN
    B = synth_base(date(2026, 10, 24), date(2026, 10, 24), spikes=[(an + 1450 * MIN, 150.0)])
    up, _ = dr._hist(B, 1, 0)
    assert up[0] > 20                                               # всплеск на 1450-й минуте внутри окна
    am = dr.anchor_ms(date(2026, 3, 28))                            # 28.03 CET → 29.03 CEST: 1380 мин
    assert dr.anchor_ms(date(2026, 3, 29)) - am == 1380 * MIN
    B2 = synth_base(date(2026, 3, 28), date(2026, 3, 28), spikes=[(am + 1400 * MIN, 150.0)], tail_min=200)
    up2, _ = dr._hist(B2, 1, 0)
    assert up2[0] < 20                                              # 1400-я минута — уже за 08:00, не входит


def test_history_atr_and_pref_are_causal():
    an = dr.anchor_ms(date(2026, 10, 5))
    plain = dr._hist(synth_base(date(2026, 10, 5), date(2026, 10, 5)), 1, 0)[0][0]
    after = dr._hist(synth_base(date(2026, 10, 5), date(2026, 10, 5), spikes=[(an + 30 * MIN, 150.0)]), 1, 0)[0][0]
    before = dr._hist(synth_base(date(2026, 10, 5), date(2026, 10, 5), spikes=[(an - MIN, 150.0)]), 1, 0)[0][0]
    assert after > 10 * plain                                       # всплеск после A — в исходе
    assert before <= plain                                          # всплеск 07:59 — до A: в исход не входит (ATR растёт)


# ---------------------------------------------------------------- P1: зона и касания только после выдачи
def test_zone_after_issue_ignored_and_touch_before_A_not_counted(tmp_dr, monkeypatch):
    issued = datetime(2026, 10, 19, 6, 9, 30, tzinfo=UTC)          # 08:09:30 Варшавы
    snaps = [{"run_id": "r1", "levels_captured": "2026-10-19T06:09:00+00:00",
              "levels": {"zones_short": [{"lo": 105.0, "hi": 106.0}], "zones_long": []}},
             {"run_id": "r2", "levels_captured": "2026-10-19T06:12:00+00:00",          # после выдачи — не берём
              "levels": {"zones_short": [{"lo": 999.0, "hi": 1000.0}], "zones_long": []}}]
    (tmp_dr / "snapshots.jsonl").write_text("\n".join(json.dumps(s) for s in snaps) + "\n")
    z = dr.zones_known(issued)
    assert z["levels"] == [("зоны шортов сверху", 105.0)] and z["run_id"] == "r1" and len(z["snapshot_record_sha256"]) == 64
    calls = []
    touch_0805 = int(datetime(2026, 10, 19, 6, 5, tzinfo=UTC).timestamp() * 1000)
    monkeypatch.setattr(dr, "klines", fake_klines(calls, hi_at_ms={touch_0805}))
    f = dr.forecast("BTCUSDT", issued, z)
    assert f["A_ms"] == int(datetime(2026, 10, 19, 6, 10, tzinfo=UTC).timestamp() * 1000)
    assert f["P_ref_minute_ms"] == f["A_ms"] - 2 * MIN and f["zones_source"]["run_id"] == "r1"
    assert f["late"] is False and f["window_min"] == 1430
    c = dr._check_one(f)
    assert c["levels"][0]["touched"] is False                       # касание 08:05 было до выдачи — не засчитано
    assert calls[-1][1] == f["A_ms"]


def test_forecast_atr_hours_closed_before_issue_hour(tmp_dr, monkeypatch):
    calls = []
    monkeypatch.setattr(dr, "klines", fake_klines(calls))
    issued = datetime(2026, 10, 19, 7, 30, 10, tzinfo=UTC)         # 09:30 Варшавы → часы до 09:00
    f = dr.forecast("BTCUSDT", issued, None)
    H = int(datetime(2026, 10, 19, 7, 0, tzinfo=UTC).timestamp() * 1000)
    assert f["atr_hours_open_ms"][-1] == H - HOUR and f["phase"] == {"k_min": 91, "h_off": 1}
    assert f["late"] is True and f["atr"] == pytest.approx(2.0)


# ---------------------------------------------------------------- P2: все созревшие проверки, pending, зрелость
def _fc(day: date, sym="BTCUSDT"):
    a = dr.anchor_ms(day) + MIN
    return {"algo": dr.ALGO, "kind": "forecast", "date": day.isoformat(), "sym": sym, "A_ms": a,
            "end_ms": dr.anchor_ms(day + timedelta(days=1)), "corridor": [90.0, 110.0], "late": False,
            "levels": [{"name": "верх", "price": 105.0, "side": "up", "chance": 0.4}]}


def test_backlog_resolved_and_failures_stay_pending(tmp_dr, monkeypatch):
    for d in (date(2026, 10, 17), date(2026, 10, 18)):
        dr._append(_fc(d))
    dr._append({"kind": "forecast", "date": "2026-10-16", "sym": "BTCUSDT"})   # старая версия — не трогаем
    clock = lambda: datetime(2026, 10, 20, 6, 5, tzinfo=UTC)       # noqa: E731
    monkeypatch.setattr(dr, "klines", fake_klines([], fail=True))
    assert dr.resolve_all(clock) == 0
    s = dr.stats("BTCUSDT", clock)
    assert (s["issued"], s["resolved"], s["pending"]) == (2, 0, 2)
    assert s["missing_days"] == 1                                   # 19.10 без прогноза (20.10 ещё не выдан)
    assert len([r for r in dr._read() if r.get("kind") == "pending"]) == 2
    monkeypatch.setattr(dr, "klines", fake_klines([]))
    assert dr.resolve_all(clock) == 2                               # оба дня догружены, а не только «вчера»
    s = dr.stats("BTCUSDT", clock)
    assert (s["resolved"], s["pending"], s["inside"]) == (2, 0, 2)


def test_maturity_uses_real_clock_not_issue_time(tmp_dr, monkeypatch):
    dr._append(_fc(date(2026, 10, 18)))
    monkeypatch.setattr(dr, "klines", fake_klines([]))
    end = dr.anchor_ms(date(2026, 10, 19))
    assert dr.resolve_all(lambda: datetime.fromtimestamp((end + 30_000) / 1000, UTC)) == 0   # ещё не созрел
    assert dr.resolve_all(lambda: datetime.fromtimestamp((end + 61_000) / 1000, UTC)) == 1


def test_dst_check_requires_full_1500_minutes(tmp_dr, monkeypatch):
    f = _fc(date(2026, 10, 24))
    assert (f["end_ms"] - f["A_ms"]) // MIN == 1499
    dr._append(f)
    calls = []
    monkeypatch.setattr(dr, "klines", fake_klines(calls))
    assert dr.resolve_all(lambda: datetime(2026, 10, 25, 7, 5, tzinfo=UTC)) == 1
    c = [r for r in dr._read() if r.get("kind") == "check"][0]
    assert c["minutes"] == 1499 and calls[-1][2] == f["end_ms"]


# ---------------------------------------------------------------- проверка вне выборки и карточка
def test_validate_reports_marginal_joint_and_brier():
    B = synth_base(date(2026, 6, 1), date(2026, 9, 30), seed=3)
    v = dr._validate(B)
    assert v["joint_inside"] <= min(v["marginal_up_inside"], v["marginal_down_inside"])
    assert v["brier_model"] < v["brier_baseline_const"] and v["n_test_days"] + v["n_train_days"] == len(B["days"])
    assert all(b["days"] <= v["n_test_days"] for b in v["touch_bins"])


def test_lines_survive_network_failure(tmp_dr, monkeypatch):
    monkeypatch.setattr(dr, "klines", fake_klines([], fail=True))
    out = dr.lines(datetime(2026, 10, 19, 6, 5, tzinfo=UTC), zones={},
                   clock=lambda: datetime(2026, 10, 19, 6, 5, tzinfo=UTC))
    assert out[0].startswith("📏") and any("не посчитано" in x for x in out)
