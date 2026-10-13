"""Ревью GPT 13.10, вопрос 4: гонка repair_frozen_1m ↔ gapfill (scripts/ohlcv_ingest.py) и неполные часы fix_hours.

Протокол: общий межпроцессный lock backtests/frozen/.ingest.lock (fcntl.flock LOCK_EX). Gapfill держит его на каждой
дозаписи 1m и пересчёте 1h и открывает путь заново под ним; repair — на чтение → проверку → замену.
"""
from __future__ import annotations

import fcntl
import threading

from tests.research_tools._util import load

MIN = 60_000
HOUR = 3_600_000
T0 = 1_760_000_000_000 // HOUR * HOUR                     # начало часа UTC
SYM = "FAKEUSDT"
HEADER = b"ts,open,high,low,close,volume\r\n"
BAD = (1.0, 1.0, 1.0, 1.0, 1.0)


def _row(ts: int, v: tuple) -> bytes:                    # как csv.writer ingest: repr(float), CRLF
    return (",".join([str(ts)] + [repr(float(x)) for x in v])).encode() + b"\r\n"


def _good(ts: int) -> tuple:
    k = (ts - T0) // MIN
    p = 100.0 + k
    return (p, p + 1.0, p - 1.0, p + 0.5, 1.0 + k)


def _kline(ts: int) -> list:
    o, h, l, c, v = _good(ts)
    return [ts, str(o), str(h), str(l), str(c), str(v), ts + MIN - 1]


def _ts_list(path) -> list[int]:
    return [int(x.split(b",", 1)[0]) for x in path.read_bytes().splitlines()[1:] if x.strip()]


def _hold_lock(folder):
    f = open(folder / ".ingest.lock", "a+b")             # noqa: SIM115
    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
    return f


def _thread(errors: list, fn, *args) -> threading.Thread:
    def body():
        try:
            fn(*args)
        except BaseException as exc:                        # noqa: BLE001
            errors.append(exc)
    return threading.Thread(target=body, daemon=True)


def _minutes_file(tmp_path, n: int, bad_ts: int | None = None):
    path = tmp_path / f"{SYM}_1m_2y.csv"
    rows = [HEADER] + [_row(t, BAD if t == bad_ts else _good(t)) for t in (T0 + i * MIN for i in range(n))]
    path.write_bytes(b"".join(rows))
    return path


def _fake_klines(new_ts: int):
    def fetch(symbol, start_ms, *args, **kwargs):
        return [_kline(new_ts)] if start_ms <= new_ts else []
    return fetch


def test_gapfill_append_between_check_and_replace_is_kept(tmp_path, monkeypatch):
    rf, oi = load("research/weex/repair_frozen_1m.py"), load("scripts/ohlcv_ingest.py")
    monkeypatch.setattr(rf, "FROZEN", tmp_path)
    bad = T0 + 2 * MIN
    path = _minutes_file(tmp_path, 5, bad_ts=bad)
    ref = {T0 + i * MIN: _good(T0 + i * MIN) for i in range(5)}
    monkeypatch.setattr(rf, "fetch", lambda sym, a, b: dict(ref))
    new_ts = T0 + 5 * MIN
    monkeypatch.setattr(oi, "_fetch_klines", _fake_klines(new_ts))
    errors: list = []
    writer = _thread(errors, oi.fill_gap, SYM, "1m", new_ts + 30_000, tmp_path)
    check = rf._changed

    def check_then_gapfill(p, st):
        res = check(p, st)
        writer.start()                     # gapfill дописывает минуту ровно между проверкой и заменой
        writer.join(timeout=1.0)           # без общего lock он успевает здесь; с lock — ждёт конца замены
        return res

    monkeypatch.setattr(rf, "_changed", check_then_gapfill)
    rf.repair(SYM, T0, apply=True)
    writer.join(timeout=15)
    assert not writer.is_alive() and not errors, errors
    got = _ts_list(path)
    assert got.count(new_ts) == 1, "дозапись gapfill между проверкой и заменой потеряна"
    assert got == sorted(set(got))
    line = next(x for x in path.read_bytes().splitlines(keepends=True) if x.startswith(str(bad).encode()))
    assert line in (_row(bad, _good(bad)), _row(bad, BAD))    # починено под lock ИЛИ замена отменена
    assert line == _row(bad, _good(bad))


def test_repair_tmp_name_unique_foreign_tmp_untouched(tmp_path, monkeypatch):
    rf = load("research/weex/repair_frozen_1m.py")
    monkeypatch.setattr(rf, "FROZEN", tmp_path)
    bad = T0 + MIN
    path = _minutes_file(tmp_path, 3, bad_ts=bad)
    monkeypatch.setattr(rf, "fetch", lambda sym, a, b: {T0 + i * MIN: _good(T0 + i * MIN) for i in range(3)})
    foreign = tmp_path / f"{SYM}_1m_2y.csv.tmp"            # временный файл другого процесса со старым именем
    foreign.write_bytes(b"foreign")
    mode0 = path.stat().st_mode & 0o777
    rf.repair(SYM, T0, apply=True)
    assert foreign.exists() and foreign.read_bytes() == b"foreign", "чужой .csv.tmp перезаписан"
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp") and p != foreign] == []
    assert _row(bad, _good(bad)) in path.read_bytes()
    assert path.stat().st_mode & 0o777 == mode0              # права файла не сменились на 0600 временного


def test_gapfill_append_waits_for_lock_and_rereads_tail(tmp_path, monkeypatch):
    oi = load("scripts/ohlcv_ingest.py")
    path = _minutes_file(tmp_path, 3)
    new_ts = T0 + 3 * MIN
    monkeypatch.setattr(oi, "_fetch_klines", _fake_klines(new_ts))
    holder = _hold_lock(tmp_path)
    errors: list = []
    th = _thread(errors, oi.fill_gap, SYM, "1m", new_ts + 30_000, tmp_path)
    try:
        th.start()
        th.join(timeout=0.7)
        blocked = th.is_alive()
        with open(path, "ab") as f:                          # другой писатель под тем же lock успел дописать минуту
            f.write(_row(new_ts, _good(new_ts)))
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()
    th.join(timeout=15)
    assert not errors, errors
    assert blocked, "gapfill дописывает 1m, не дожидаясь общего lock"
    assert _ts_list(path).count(new_ts) == 1, "под lock хвост не перечитан — дубль минуты"


def test_gapfill_1h_resample_waits_for_lock(tmp_path):
    oi = load("scripts/ohlcv_ingest.py")
    _minutes_file(tmp_path, 121)
    hour = tmp_path / f"{SYM}_1h_2y.csv"
    hour.write_bytes(HEADER + _row(T0 - HOUR, _good(T0)))
    holder = _hold_lock(tmp_path)
    errors: list = []
    th = _thread(errors, oi.fill_1h_from_1m, SYM, tmp_path)
    try:
        th.start()
        th.join(timeout=0.7)
        blocked = th.is_alive()
        snapshot = hour.read_bytes()
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()
    th.join(timeout=15)
    assert not errors, errors
    assert blocked and snapshot == HEADER + _row(T0 - HOUR, _good(T0)), "пересчёт 1h идёт без общего lock"
    assert _ts_list(hour) == [T0 - HOUR, T0, T0 + HOUR]


def _hour_file(tmp_path):
    path = tmp_path / f"{SYM}_1h_2y.csv"
    orig = HEADER + _row(T0, BAD)
    path.write_bytes(orig)
    return path, orig


def test_fix_hours_rejects_duplicate_minute_with_gap(tmp_path, monkeypatch):
    rf = load("research/weex/repair_frozen_1m.py")
    monkeypatch.setattr(rf, "FROZEN", tmp_path)
    path, orig = _hour_file(tmp_path)
    rows = [_row(T0 + m * MIN, _good(T0 + m * MIN)) for m in range(60) if m != 17]
    rows.insert(1, _row(T0, _good(T0)))                     # дубль минуты 0, нет минуты 17 — всё равно 60 строк
    assert len(rows) == 60
    rf.fix_hours(SYM, rows, T0, True)
    assert path.read_bytes() == orig, "час из 59 разных минут (60 строк) принят за полный"


def test_fix_hours_rejects_off_grid_stamp(tmp_path, monkeypatch):
    rf = load("research/weex/repair_frozen_1m.py")
    monkeypatch.setattr(rf, "FROZEN", tmp_path)
    path, orig = _hour_file(tmp_path)
    rows = [_row(T0 + m * MIN + (30_000 if m == 17 else 0), _good(T0 + m * MIN)) for m in range(60)]
    rf.fix_hours(SYM, rows, T0, True)
    assert path.read_bytes() == orig, "минута не на сетке hour+k*60000 принята"


def test_fix_hours_full_hour_recomputed_in_time_order(tmp_path, monkeypatch):
    rf = load("research/weex/repair_frozen_1m.py")
    monkeypatch.setattr(rf, "FROZEN", tmp_path)
    path, _ = _hour_file(tmp_path)
    stamps = [T0 + m * MIN for m in range(60)]
    rows = [_row(t, _good(t)) for t in stamps[30:] + stamps[:30]]   # порядок строк не по времени
    rf.fix_hours(SYM, rows, T0, True)
    bars = [_good(t) for t in stamps]
    want = (bars[0][0], max(b[1] for b in bars), min(b[2] for b in bars), bars[-1][3], round(sum(b[4] for b in bars), 8))
    assert path.read_bytes() == HEADER + _row(T0, want)
