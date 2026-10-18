"""C1 (протокол cg-c1-20261018) — синтетика, без сети: клайны и база подменяются."""
import json
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

from services.coinglass_web import c1

MIN, HOUR = 60_000, 3_600_000
UTC = timezone.utc


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


@pytest.fixture
def tmp_c1(tmp_path, monkeypatch):
    monkeypatch.setattr(c1, "C1", tmp_path)
    monkeypatch.setattr(c1, "_BASE", None)
    (tmp_path / "base_manifest.json").write_text(json.dumps({"npz_sha256": "n" * 64, "dates_sha256": "d" * 64}))
    return tmp_path


def levels(price=100.0, short=None, long=None):
    return {"price": price,
            "zones_short": short if short is not None else [{"lo": 104.0, "hi": 105.0, "strength": 500},
                                                            {"lo": 103.0, "hi": 104.0, "strength": 500}],
            "zones_long": long if long is not None else [{"lo": 96.0, "hi": 97.0, "strength": 300}]}


def clock(*times):
    """now_fn: первый вызов — время фиксации, дальше — последнее значение."""
    seq = list(times)

    def f():
        return seq.pop(0) if len(seq) > 1 else seq[0]
    return f


def fake_klines(tmp, p0=100.0, calls=None):
    def k(interval, start, end):
        assert (tmp / "fixes.jsonl").exists(), "цена A запрошена до записи фиксации"
        if calls is not None:
            calls.append(interval)
        if interval == "1m":
            return [[start, str(p0), str(p0), str(p0), str(p0), "1", start + MIN - 1]]
        out = []
        t = (start // HOUR + 1) * HOUR if start % HOUR else start
        while t < end:
            big = t == (end // HOUR) * HOUR                          # текущий незакрытый час — огромный размах
            out.append([t, "100", "200" if big else "101", "99", "100", "1", t + HOUR - 1])
            t += HOUR
        return out
    return k


RUN = datetime(2026, 10, 19, 5, 0, 5, tzinfo=UTC)                   # 07:00:05 Варшавы (CEST)
CAP = datetime(2026, 10, 19, 5, 0, 40, tzinfo=UTC)
FIX = datetime(2026, 10, 19, 5, 1, 30, tzinfo=UTC)


# ---------------------------------------------------------------- выбор зон и общие расчёты
def test_select_zones_tie_breaks_and_equal_strength():
    s = c1.select_zones(levels())
    assert s["U"] == 103.0 and s["L"] == 97.0 and s["stronger"] == "upper"   # равные силы → меньший разрыв
    s = c1.select_zones(levels(short=[{"lo": 103.0, "hi": 104.0, "strength": 300}]))
    assert s["stronger"] is None                                    # силы сторон равны → воздержаться
    s = c1.select_zones(levels(long=[]))
    assert s["L"] is None


def test_atr14_is_simple_mean_not_wilder():
    h, lo, c = [101.0] * 15, [99.0] * 15, [100.0] * 15
    h[14], lo[14] = 110.0, 90.0                                     # последний TR = 20, остальные 13 по 2
    assert c1.atr14(h, lo, c) == pytest.approx((13 * 2 + 20) / 14)


def test_bucket_and_minute_outcomes():
    hi, lo = [100.0] * 1440, [100.0] * 1440
    hi[10], lo[20] = 103.0, 97.0                                    # обе стороны в первой корзине
    assert c1.bucket_outcome(hi, lo, 103.0, 97.0) == "both"
    assert c1.minute_outcome(hi, lo, 103.0, 97.0) == "upper"
    hi2, lo2 = [100.0] * 1440, [100.0] * 1440
    lo2[70] = 97.0
    assert c1.bucket_outcome(hi2, lo2, 103.0, 97.0) == "lower"
    assert c1.bucket_outcome([100.0] * 1440, [100.0] * 1440, 103.0, 97.0) == "none"


# ---------------------------------------------------------------- прогноз
def test_not_scheduled_run_is_ignored(tmp_c1):
    assert c1.make_forecast("r", RUN + timedelta(hours=1), levels(), CAP, {}) is None
    assert c1.make_forecast("r", datetime(2026, 10, 18, 5, 0, tzinfo=UTC), levels(), CAP, {}) is None   # до старта
    assert not (tmp_c1 / "registry.jsonl").exists()


def test_admitted_forecast_fixes_before_price_and_uses_closed_hours(tmp_c1, monkeypatch):
    calls, seen_q = [], {}
    monkeypatch.setattr(c1, "klines", fake_klines(tmp_c1, calls=calls))
    monkeypatch.setattr(c1, "q_vector", lambda a, b, hhmm, side: seen_q.update(a=a, b=b, hhmm=hhmm, side=side) or
                        {"q_low": 0.4, "q_high": 0.45, "complete": 730})
    a_ms = ms(datetime(2026, 10, 19, 5, 2, tzinfo=UTC))
    rec = c1.make_forecast("run-1", RUN, levels(), CAP, {"x": 1},
                           now_fn=clock(FIX, datetime(2026, 10, 19, 5, 2, 3, tzinfo=UTC)), sleep=lambda s: None)
    assert rec["status"] == "admitted" and rec["run_id"] == "run-1"
    assert rec["A_utc"] == "2026-10-19T05:02:00+00:00" and rec["phase_local"] == "07:02"
    assert rec["P0"] == 100.0 and rec["atr_1h"] == pytest.approx(2.0)          # незакрытый час 05:00 не вошёл
    assert len(rec["atr_hours_open_utc"]) == 15
    assert rec["atr_hours_open_utc"][-1] == ms(datetime(2026, 10, 19, 4, 0, tzinfo=UTC))
    assert max(rec["atr_hours_close_utc"]) < ms(FIX)
    assert seen_q == {"a": 1.5, "b": 1.5, "hhmm": (7, 2), "side": "upper"}
    fixes = [json.loads(x) for x in (tmp_c1 / "fixes.jsonl").read_text().splitlines()]
    assert len(fixes) == 1 and "P0" not in fixes[0] and rec["fix_sha256"] == fixes[0]["fix_sha256"]
    body = {k: v for k, v in rec.items() if k != "record_sha256"}
    assert rec["record_sha256"] == c1.sha_bytes(c1.canon(body))
    assert a_ms == ms(datetime.fromisoformat(rec["A_utc"]))
    # повторный запуск того же слота не заменяет выбранную запись
    assert c1.make_forecast("run-2", RUN + timedelta(minutes=5), levels(), CAP + timedelta(minutes=5), {}) is None
    assert len((tmp_c1 / "registry.jsonl").read_text().splitlines()) == 1


def test_abstain_at_anchor(tmp_c1, monkeypatch):
    monkeypatch.setattr(c1, "klines", fake_klines(tmp_c1, p0=103.5))
    rec = c1.make_forecast("r", RUN, levels(), CAP, {}, now_fn=clock(FIX, FIX + timedelta(minutes=1)),
                           sleep=lambda s: None)
    assert rec["status"] == "abstain_at_anchor" and "q" not in rec


def test_missing_late_capture_and_late_forecast(tmp_c1, monkeypatch):
    assert c1.make_forecast("r", RUN, None, None, {}) is None
    reg = [json.loads(x) for x in (tmp_c1 / "registry.jsonl").read_text().splitlines()]
    assert reg[-1]["status"] == "missing_snapshot"
    day2 = RUN + timedelta(days=1)
    assert c1.make_forecast("r", day2, levels(), day2 + timedelta(minutes=10), {}) is None
    reg = [json.loads(x) for x in (tmp_c1 / "registry.jsonl").read_text().splitlines()]
    assert reg[-1]["status"] == "late_capture"
    day3 = RUN + timedelta(days=2)
    monkeypatch.setattr(c1, "klines", lambda *a: pytest.fail("при опоздании цена не нужна"))
    rec = c1.make_forecast("r", day3, levels(), day3 + timedelta(minutes=9, seconds=50), {},
                           now_fn=clock(day3 + timedelta(minutes=10, seconds=1)))
    assert rec["status"] == "late_forecast"


def test_close_missing_fills_only_empty_past_slots(tmp_c1):
    (tmp_c1 / "registry.jsonl").write_text(json.dumps({"slot": "2026-10-19", "status": "admitted"}) + "\n")
    (tmp_c1 / "fixes.jsonl").write_text(json.dumps({"slot": "2026-10-20"}) + "\n")
    now = datetime(2026, 10, 21, 6, 0, tzinfo=UTC)                   # 08:00 Варшавы 21.10
    assert c1.close_missing(now) == 1
    reg = [json.loads(x) for x in (tmp_c1 / "registry.jsonl").read_text().splitlines()]
    assert reg[-1]["slot"] == "2026-10-21" and reg[-1]["status"] == "missing_snapshot"
    assert c1.close_missing(now) == 0


# ---------------------------------------------------------------- исход
def _forecast_file(tmp, a_dt):
    f = {"forecast_id": "c1-2026-10-19", "slot": "2026-10-19", "status": "admitted", "A_utc": a_dt.isoformat(),
         "U": 103.0, "L": 97.0, "stronger": "upper", "q": {"q_low": 0.4, "q_high": 0.45}}
    (tmp / "forecasts.jsonl").write_text(json.dumps(f) + "\n")
    (tmp / "registry.jsonl").write_text(json.dumps({"slot": "2026-10-19", "status": "admitted"}) + "\n")


def _minutes(a_ms, n, hi_at=None, lo_at=None):
    rows = []
    for i in range(n):
        h = 103.5 if i == hi_at else 100.0
        lo = 96.5 if i == lo_at else 100.0
        rows.append([a_ms + i * MIN, "100", str(h), str(lo), "100"])
    return rows


def test_evaluate_incomplete_then_revision_and_freeze(tmp_c1, monkeypatch):
    a_dt = datetime(2026, 10, 19, 5, 2, tzinfo=UTC)
    _forecast_file(tmp_c1, a_dt)
    a_ms = ms(a_dt)
    after = a_dt + timedelta(days=1, minutes=3)
    monkeypatch.setattr(c1, "klines", lambda i, s, e: _minutes(a_ms, 1439, hi_at=70))
    assert c1.evaluate(after) == 1
    assert c1.evaluate(after) == 0                                  # неполное повторно не пишется
    monkeypatch.setattr(c1, "klines", lambda i, s, e: _minutes(a_ms, 1440, hi_at=70))
    assert c1.evaluate(after + timedelta(hours=1)) == 1
    outs = [json.loads(x) for x in (tmp_c1 / "outcomes.jsonl").read_text().splitlines()]
    assert (outs[0]["outcome"], outs[0]["Y_low"], outs[0]["Y_high"]) == ("unknown", 0.0, 1.0)
    assert (outs[1]["outcome"], outs[1]["Y_low"], outs[1]["Y_high"]) == ("upper", 1.0, 1.0)
    s = c1.summary()
    assert s["resolved"] == 1 and s["D_low_desc"] == pytest.approx(1 - 0.45) and s["outcomes"] == {"upper": 1}
    assert c1.evaluate(datetime(2027, 10, 23, tzinfo=UTC)) == 0


def test_evaluate_both_is_conservative(tmp_c1, monkeypatch):
    a_dt = datetime(2026, 10, 19, 5, 2, tzinfo=UTC)
    _forecast_file(tmp_c1, a_dt)
    monkeypatch.setattr(c1, "klines", lambda i, s, e: _minutes(ms(a_dt), 1440, hi_at=10, lo_at=20))
    c1.evaluate(a_dt + timedelta(days=1, minutes=3))
    o = json.loads((tmp_c1 / "outcomes.jsonl").read_text().splitlines()[-1])
    assert (o["outcome"], o["outcome_1m"], o["Y_low"], o["Y_high"]) == ("both", "upper", 0.0, 1.0)


# ---------------------------------------------------------------- база: фаза, каузальный ATR, SHA
def _synthetic_base(a_j_ms):
    t0 = ms(datetime(2026, 9, 30, tzinfo=UTC))
    n = 4 * 1440
    ts = t0 + np.arange(n, dtype=np.int64) * MIN
    op = np.full(n, 100.2)
    hi, lo, cl = np.full(n, 100.5), np.full(n, 99.5), np.full(n, 100.0)
    i = int((a_j_ms - t0) // MIN)
    op[i] = 100.0
    hi[i - 1] = 150.0                                               # минута до A_j в том же часе: в ATR не попадает
    hi[i + 200] = 102.0                                             # корзина 3 → верх первым
    return {"ts": ts, "open": op, "high": hi, "low": lo, "close": cl, "pos": {int(t): k for k, t in enumerate(ts)}}


def test_history_point_phase_and_q_vector(monkeypatch):
    a_j = datetime(2026, 10, 1, 7, 2, tzinfo=c1.WARSAW)
    monkeypatch.setattr(c1, "_BASE", _synthetic_base(ms(a_j)))
    p, atr, hi, lo = c1.history_point(ms(a_j))
    assert p == 100.0 and atr == pytest.approx(1.0) and len(hi) == 1440
    monkeypatch.setattr(c1, "BASE_DATES", [date(2026, 10, 1), date(2026, 10, 9)])   # вторая дата вне базы → unknown
    q = c1.q_vector(1.5, 1.5, (7, 2), "upper")
    assert (q["side_first"], q["unknown"], q["n"]) == (1, 1, 2)
    assert q["q_low"] == 0.5 and q["q_high"] == 1.0 and q["per_date"] == "SU"


# ---------------------------------------------------------------- финальный разбор (бутстрап)
def test_block_indices_circular_blocks():
    idx = c1._block_indices(np.random.Generator(np.random.PCG64(1)), 10)
    assert len(idx) == 10 and idx.min() >= 0 and idx.max() < 10
    assert all((idx[i + 1] - idx[i]) % 10 == 1 for i in range(6))     # внутри первого блока — подряд по кругу


def _per(q_high: float) -> str:
    k = round(q_high * 730)
    return "S" * k + "O" * (730 - k)


def test_bootstrap_deterministic_and_detects_large_effect():
    rng = np.random.default_rng(5)
    per = [_per(0.4)] * 300
    y = (rng.random(300) < 0.75).astype(float).tolist()                # +35 п.п. к базе
    a = c1.bootstrap(per, y, list(range(300)), reps=300)
    b = c1.bootstrap(per, y, list(range(300)), reps=300)
    assert np.array_equal(a["D_b"], b["D_b"]) and a["L"] == b["L"]
    assert a["defined"] and a["L"] > c1.MARGIN


def test_bootstrap_no_effect_not_confirmed_and_empty_undefined():
    rng = np.random.default_rng(6)
    per = [_per(0.4)] * 300
    y = (rng.random(300) < 0.4).astype(float).tolist()
    assert c1.bootstrap(per, y, list(range(300)), reps=300)["L"] < c1.MARGIN
    e = c1.bootstrap([], [], [], reps=10)
    assert e["defined"] is False and e["L"] is None


def test_final_test_locked_until_freeze_and_quality_gate(tmp_c1):
    assert "error" in c1.final_test(datetime(2027, 10, 20, tzinfo=UTC))
    f = {"forecast_id": "c1-2026-10-19", "slot": "2026-10-19", "status": "admitted",
         "q": {"per_date": _per(0.4), "q_low": 0.4, "q_high": 0.4}}
    (tmp_c1 / "forecasts.jsonl").write_text(json.dumps(f) + "\n")
    (tmp_c1 / "outcomes.jsonl").write_text(json.dumps({"forecast_id": "c1-2026-10-19", "complete": True,
                                                        "Y_low": 1.0, "Y_high": 1.0}) + "\n")
    r = c1.final_test(datetime(2027, 10, 23, 10, 0, tzinfo=UTC))
    assert r["N_admitted"] == 1 and r["quality_ok"] is False and r["confirmed"] is False
    assert (tmp_c1 / "bootstrap_D_b.npy").exists()


def test_base_sha_mismatch_refuses(tmp_c1):
    np.savez(tmp_c1 / "base.npz", ts=np.array([1]))
    with pytest.raises(RuntimeError):
        c1.base()
