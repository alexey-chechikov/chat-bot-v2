"""Прогноз размаха на сутки — синтетика, без сети."""
import json
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

from services.coinglass_web import day_range as dr

MIN, HOUR = 60_000, 3_600_000
DAY = date(2026, 10, 19)
A = dr.anchor_ms(DAY)                                               # 08:00 Варшавы = 06:00 UTC


@pytest.fixture
def tmp_dr(tmp_path, monkeypatch):
    monkeypatch.setattr(dr, "DIR", tmp_path)
    monkeypatch.setattr(dr, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(dr, "_TAB", {"BTCUSDT": {"up": [float(x) for x in range(1, 11)],
                                                 "dn": [float(x) for x in range(1, 11)], "days": ["a", "b"],
                                                 "validation": {"promised_realized_n": [[0.1, 0.1, 5]]}},
                                     "ETHUSDT": {"up": [1.0] * 10, "dn": [1.0] * 10, "days": ["a", "b"],
                                                 "validation": {"promised_realized_n": [[0.1, 0.1, 5]]}}})
    return tmp_path


def fake_klines(calls, p0=100.0, hi_at=None, lo_at=None, n1m=1440):
    def k(sym, interval, start, end):
        calls.append((interval, start, end))
        if interval == "1h":
            return [[t, "100", "101", "99", "100", "1", t + HOUR - 1] for t in range(start, end, HOUR)]
        if end - start == MIN:
            return [[start, str(p0), str(p0), str(p0), str(p0)]]
        rows = []
        for i in range(n1m):
            h = 110.0 if i == hi_at else 100.5
            lo = 90.0 if i == lo_at else 99.5
            rows.append([start + i * MIN, "100", str(h), str(lo), "100"])
        return rows
    return k


def test_anchor_is_0800_warsaw():
    assert datetime.fromtimestamp(A / 1000, timezone.utc) == datetime(2026, 10, 19, 6, 0, tzinfo=timezone.utc)


def test_moves_atr_uses_only_hours_before_anchor():
    t0 = A - 15 * HOUR
    n = 15 * 60 + 1440
    ts = t0 + np.arange(n, dtype=np.int64) * MIN
    op, hi, lo, cl = np.full(n, 100.0), np.full(n, 100.5), np.full(n, 99.5), np.full(n, 100.0)
    hi[900 + 30] = 103.0                                            # после 08:00 — в ATR не входит, в up входит
    up, dn, atr, p0 = dr._moves(ts, op, hi, lo, cl, A)
    assert atr == pytest.approx(1.0) and up == pytest.approx(3.0) and dn == pytest.approx(0.5)
    assert dr._moves(ts[:-1], op[:-1], hi[:-1], lo[:-1], cl[:-1], A) is None   # неполное окно


def test_forecast_corridor_chances_and_logged_once(tmp_dr, monkeypatch):
    calls = []
    monkeypatch.setattr(dr, "klines", fake_klines(calls))
    f = dr.forecast("BTCUSDT", DAY, [("верх", 104.0), ("низ", 97.0)])
    assert f["P0"] == 100.0 and f["atr"] == pytest.approx(2.0)
    q = float(np.quantile(range(1, 11), dr.Q))
    assert f["corridor"] == pytest.approx([100 - q * 2, 100 + q * 2])
    assert [x["chance"] for x in f["levels"]] == [0.9, 0.9]          # 2 ATR вверх и 1.5 ATR вниз: по 9 из 10 (≥2…10)
    n = len(calls)
    assert dr.forecast("BTCUSDT", DAY) == f and len(calls) == n       # второй раз — из журнала, без сети


def test_check_waits_for_full_window_then_scores(tmp_dr, monkeypatch):
    calls = []
    monkeypatch.setattr(dr, "klines", fake_klines(calls))
    dr.forecast("BTCUSDT", DAY, [("верх", 104.0), ("низ", 97.0)])
    early = datetime.fromtimestamp((A + 1440 * MIN) / 1000, timezone.utc)
    assert dr.check("BTCUSDT", DAY, early) is None
    monkeypatch.setattr(dr, "klines", fake_klines(calls, n1m=1439))
    assert dr.check("BTCUSDT", DAY, early + timedelta(minutes=5)) is None   # неполные минуты — не оцениваем
    monkeypatch.setattr(dr, "klines", fake_klines(calls, hi_at=100))
    c = dr.check("BTCUSDT", DAY, early + timedelta(minutes=5))
    assert c["broke_up"] is False and c["inside"] is True
    assert [x["touched"] for x in c["levels"]] == [True, False]
    s = dr.stats("BTCUSDT")
    assert s["days"] == 1 and s["inside"] == 1 and s["realized"] == 0.5 and s["promised"] == pytest.approx(0.9)


def test_zones_only_from_0800_snapshot(tmp_dr):
    def snap(cap, lo):
        return json.dumps({"levels_captured": cap, "levels": {"zones_short": [{"lo": lo, "hi": lo + 1}],
                                                              "zones_long": [{"lo": 1.0, "hi": 2.0}]}})
    (tmp_dr / "snapshots.jsonl").write_text("\n".join([
        snap("2026-10-19T06:00:15+00:00", 83000.0),                 # 08:00 Варшавы — берём
        snap("2026-10-19T09:35:00+00:00", 99999.0)]) + "\n")        # позже — нет
    assert dr.zones_at(DAY) == [("зоны шортов сверху", 83000.0), ("зоны лонгов снизу", 2.0)]
    assert dr.zones_at(DAY + timedelta(days=1)) == []


def test_lines_survive_network_failure(tmp_dr, monkeypatch):
    def boom(*a):
        raise OSError("нет сети")
    monkeypatch.setattr(dr, "klines", boom)
    out = dr.lines(datetime(2026, 10, 19, 6, 5, tzinfo=timezone.utc), zones=[])
    assert out[0].startswith("📏") and any("не посчитано" in x for x in out)
