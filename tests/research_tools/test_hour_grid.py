"""Ревью GPT 15.10 (docs/WEEX_GPT_REVIEW_AND_MANUAL_STRATEGIES_2026-10-15.md §1, P2): производитель часов
scripts/ohlcv_ingest.py (fill_1h_from_1m, каждый прогон gapfill) проверял только возраст часа — час из ОДНОЙ минуты,
из 59 минут, из 60 строк с дублем и пропуском, с меткой вне сетки или с битым OHLC записывался как OHLC.

Час пишется только из ровно 60 разных минут hour + k·60000, k = 0..59, каждая — валидный OHLCV. Валидатор один на
производителя и на починку research/weex/repair_frozen_1m.py (scripts/ohlc_grid.py).
"""
from __future__ import annotations

import math

import pytest

from tests.research_tools._util import load

MIN = 60_000
HOUR = 3_600_000
T0 = 1_760_000_000_000 // HOUR * HOUR                     # начало часа UTC
SYM = "FAKEUSDT"
HEADER = b"ts,open,high,low,close,volume\r\n"
PREV = (50.0, 51.0, 49.0, 50.5, 1.0)                     # последний час, уже лежащий в 1h-файле


def _row(ts: int, v) -> bytes:                            # как csv.writer ingest: repr(float), CRLF
    return (",".join([str(ts)] + ["" if x is None else repr(float(x)) for x in v])).encode() + b"\r\n"


def _good(ts: int) -> tuple:
    k = (ts - T0) // MIN
    p = 100.0 + k
    return (p, p + 1.0, p - 1.0, p + 0.5, 1.0 + k)


def _hour_rows(h: int) -> list[tuple[int, tuple]]:
    return [(h + m * MIN, _good(h + m * MIN)) for m in range(60)]


def _bad_hour(kind: str, h: int) -> list[tuple[int, tuple]]:
    rows = _hour_rows(h)
    t17 = h + 17 * MIN
    o, hi, lo, c, v = _good(t17)
    if kind == "one_minute":                             # пример GPT: час из одной минуты
        return rows[:1]
    if kind == "59_minutes":
        return [r for r in rows if r[0] != t17]
    if kind == "dup_and_missing":                        # 60 строк: дубль минуты 0, нет минуты 17
        out = [r for r in rows if r[0] != t17]
        return out[:1] + [(h, _good(h))] + out[1:]
    if kind == "off_grid":                               # минута 17 записана на hour + 17 мин + 30 с
        return [(t + 30_000, x) if t == t17 else (t, x) for t, x in rows]
    bad = {"high_below_close": (o, c - 0.1, lo, c, v),
           "low_above_open": (o, hi, o + 0.1, c, v),
           "zero_low": (o, hi, 0.0, c, v),
           "negative_volume": (o, hi, lo, c, -1.0),
           "nan_close": (o, hi, lo, None, v)}[kind]
    return [(t, bad if t == t17 else x) for t, x in rows]


BAD_KINDS = ["one_minute", "59_minutes", "dup_and_missing", "off_grid", "high_below_close", "low_above_open",
             "zero_low", "negative_volume", "nan_close"]


def _want(h: int) -> tuple:
    bars = [_good(h + m * MIN) for m in range(60)]
    return (bars[0][0], max(b[1] for b in bars), min(b[2] for b in bars), bars[-1][3],
            round(sum(b[4] for b in bars), 8))


def _write_minutes(tmp_path, rows: list[tuple[int, tuple]]):
    path = tmp_path / f"{SYM}_1m_2y.csv"
    path.write_bytes(HEADER + b"".join(_row(t, v) for t, v in rows))
    return path


def _hours_file(tmp_path):
    path = tmp_path / f"{SYM}_1h_2y.csv"
    path.write_bytes(HEADER + _row(T0 - HOUR, PREV))
    return path


def _ts_list(path) -> list[int]:
    return [int(x.split(b",", 1)[0]) for x in path.read_bytes().splitlines()[1:] if x.strip()]


# ---------- производитель: scripts/ohlcv_ingest.py fill_1h_from_1m ----------

@pytest.mark.parametrize("kind", BAD_KINDS)
def test_producer_writes_no_hour_without_exactly_60_valid_grid_minutes(tmp_path, kind):
    oi = load("scripts/ohlcv_ingest.py")
    # час 0 полный, час 1 испорчен, час 2 полный, час 3 — одна минута (часы 0–2 уже закрыты по возрасту)
    rows = _hour_rows(T0) + _bad_hour(kind, T0 + HOUR) + _hour_rows(T0 + 2 * HOUR) + [(T0 + 3 * HOUR, _good(T0))]
    _write_minutes(tmp_path, rows)
    hours = _hours_file(tmp_path)
    res = oi.fill_1h_from_1m(SYM, tmp_path)
    assert T0 + HOUR not in _ts_list(hours), f"{kind}: неполный/битый час записан как OHLC"
    assert hours.read_bytes() == (HEADER + _row(T0 - HOUR, PREV) + _row(T0, _want(T0))
                                  + _row(T0 + 2 * HOUR, _want(T0 + 2 * HOUR)))
    assert res["hours_added"] == 2 and res["hours_rejected"] == 1


def test_producer_new_hours_file_takes_only_full_hours(tmp_path):
    oi = load("scripts/ohlcv_ingest.py")
    rows = (_bad_hour("one_minute", T0 - HOUR) + _hour_rows(T0) + _bad_hour("dup_and_missing", T0 + HOUR)
            + [(T0 + 2 * HOUR, _good(T0))])
    _write_minutes(tmp_path, rows)
    res = oi.fill_1h_from_1m(SYM, tmp_path)
    hours = tmp_path / f"{SYM}_1h_2y.csv"
    assert _ts_list(hours) == [T0]
    assert hours.read_bytes().splitlines()[1] == _row(T0, _want(T0)).rstrip(b"\r\n")
    assert res["hours_added"] == 1 and res["hours_rejected"] == 2


def test_producer_dry_run_counts_only_full_hours(tmp_path):
    oi = load("scripts/ohlcv_ingest.py")
    rows = _hour_rows(T0) + _bad_hour("59_minutes", T0 + HOUR) + [(T0 + 2 * HOUR, _good(T0))]
    _write_minutes(tmp_path, rows)
    hours = _hours_file(tmp_path)
    before = hours.read_bytes()
    res = oi.fill_1h_from_1m(SYM, tmp_path, dry_run=True)
    assert res["hours_to_add"] == 1 and res["hours_rejected"] == 1
    assert hours.read_bytes() == before


def test_producer_still_waits_for_the_hour_to_close(tmp_path):
    oi = load("scripts/ohlcv_ingest.py")
    _write_minutes(tmp_path, _hour_rows(T0) + _hour_rows(T0 + HOUR)[:59])   # час 1 ещё идёт — не отказ, а ожидание
    hours = _hours_file(tmp_path)
    res = oi.fill_1h_from_1m(SYM, tmp_path)
    assert _ts_list(hours) == [T0 - HOUR, T0]
    assert res["hours_rejected"] == 0


# ---------- общий валидатор ----------

def test_producer_and_repair_use_one_shared_validator():
    oi, rf = load("scripts/ohlcv_ingest.py"), load("research/weex/repair_frozen_1m.py")
    grid = load("scripts/ohlc_grid.py")
    assert oi.full_hours is rf.full_hours and oi.hour_bar is rf.hour_bar
    assert oi.full_hours.__code__.co_filename == grid.full_hours.__code__.co_filename


@pytest.mark.parametrize("kind", BAD_KINDS)
def test_shared_validator_rejects_bad_hour(kind):
    grid = load("scripts/ohlc_grid.py")
    rows = [(t, tuple(math.nan if x is None else x for x in v)) for t, v in _bad_hour(kind, T0)]
    full, rejected = grid.full_hours(rows + _hour_rows(T0 + HOUR))
    assert list(full) == [T0 + HOUR] and rejected == [T0]


def test_shared_validator_full_hour_in_time_order_and_from_ms_cut():
    grid = load("scripts/ohlc_grid.py")
    rows = _hour_rows(T0)
    full, rejected = grid.full_hours(rows[30:] + rows[:30])
    assert rejected == [] and full[T0] == [v for _, v in rows]
    assert grid.hour_bar(full[T0]) == _want(T0)
    full, rejected = grid.full_hours(rows, from_ms=T0 + MIN)           # минута 0 до from_ms — час неполный
    assert full == {} and rejected == [T0]


def test_repair_fix_hours_rejects_one_minute_and_invalid_hours(tmp_path, monkeypatch):
    rf = load("research/weex/repair_frozen_1m.py")
    monkeypatch.setattr(rf, "FROZEN", tmp_path)
    path = tmp_path / f"{SYM}_1h_2y.csv"
    orig = HEADER + _row(T0, PREV) + _row(T0 + HOUR, PREV)
    path.write_bytes(orig)
    body = [_row(t, v) for t, v in _bad_hour("one_minute", T0) + _bad_hour("zero_low", T0 + HOUR)]
    rf.fix_hours(SYM, body, T0, True)
    assert path.read_bytes() == orig
