"""research/weex/regime_grid.py: аддендум GPT 13.10 B1 (капитал первой половины — по закрытию последней минуты
до среза, до ВСЕХ операций минуты среза, включая закрытие по смене режима) и ревью §6 (прогрев — 100 ПОЛНЫХ дней:
1440 разных минут каждый, 24/7)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.research_tools._util import load

T, F = True, False
DAY = 86_400_000


@pytest.fixture(scope="module")
def rg():
    return load("research/weex/regime_grid.py")


def _bars(o_cut: float):
    ts = np.array([0, 60, 120, 180], dtype=np.int64)
    o = np.array([100.0, 100.0, o_cut, o_cut])
    h = np.array([101.0, 100.0, o_cut, o_cut])
    l = np.array([99.0, 100.0, o_cut, o_cut])
    c = np.array([100.0, 100.0, o_cut, o_cut])
    return ts, o, h, l, c


def _run(rg, data, mode):
    rg.init(data)
    return rg.run(("t", mode, 0, 1, 100, 1, 10_000.0))   # шаг 1%, цель 100%, 1 монета, потолок $10k


@pytest.mark.parametrize("o_cut", [120.0, 90.0])          # гэп вверх / вниз на open минуты среза
@pytest.mark.parametrize("mode,reg", [("longflat", [T, T, F, F]), ("regime", [T, T, F, F]),
                                      ("regime", [F, F, T, T]), ("longflat", [T, T, T, T]),
                                      ("longflat", [F, F, T, T])])   # пустая позиция на срезе
def test_first_half_independent_of_cut_minute(rg, mode, reg, o_cut):
    ts, o, h, l, c = _bars(o_cut)
    reg = np.array(reg)
    full = _run(rg, (ts, o, h, l, c, reg), mode)
    eq, eq_mid = full[5], full[6]
    mid = len(ts) // 2
    first = _run(rg, (ts[:mid], o[:mid], h[:mid], l[:mid], c[:mid], reg[:mid]), mode)[5]
    assert eq_mid == pytest.approx(first, abs=1e-9), "в первую половину попали операции минуты среза"
    assert eq_mid + (eq - eq_mid) == pytest.approx(eq) and eq - first == pytest.approx(eq - eq_mid, abs=1e-9)


def _csv(path, days: int, per_day, drop=(), dup=()):
    t0 = int(pd.Timestamp("2024-01-01", tz="UTC").value // 10**6)
    if per_day == 1:
        ms = np.array([t0 + d * DAY for d in range(days)], dtype=np.int64)
    else:
        ms = t0 + np.arange(days * 1440, dtype=np.int64) * 60_000
        if drop:
            ms = ms[~np.isin(ms, np.array(drop, dtype=np.int64))]
        if dup:
            ms = np.sort(np.r_[ms, np.array(dup, dtype=np.int64)])
    day = (ms - t0) // DAY
    close = 100.0 + day * 0.1
    pd.DataFrame({"ts": ms, "open": close, "high": close + 0.5, "low": close - 0.5, "close": close,
                  "volume": 1.0}).to_csv(path, index=False)
    return t0


def test_one_minute_per_day_refused(rg, tmp_path, monkeypatch):
    p = tmp_path / "BTCUSDT_sparse_1m.csv"
    _csv(p, 101, 1)
    monkeypatch.setattr(rg, "SRC", p)
    with pytest.raises(SystemExit):
        rg.load()                                             # 101 «день» по одной минуте — не 100 полных дней


def test_hundred_complete_days_accepted(rg, tmp_path, monkeypatch):
    p = tmp_path / "BTCUSDT_full_1m.csv"
    t0 = _csv(p, 101, 1440)
    monkeypatch.setattr(rg, "SRC", p)
    ts, o, h, l, c, reg = rg.load()
    assert len(ts) == 1440 and int(ts[0]) * 1000 == t0 + 100 * DAY  # режим — со 101-го дня
    assert reg.all()                                          # закрытие дня 99 выше SMA100 растущего ряда


def test_incomplete_day_inside_warmup_refused(rg, tmp_path, monkeypatch):
    p = tmp_path / "BTCUSDT_hole_1m.csv"
    t0 = int(pd.Timestamp("2024-01-01", tz="UTC").value // 10**6)
    _csv(p, 101, 1440, drop=(t0 + 50 * DAY + 17 * 60_000,))  # в дне 50 нет одной минуты
    monkeypatch.setattr(rg, "SRC", p)
    with pytest.raises(SystemExit):
        rg.load()


def test_duplicate_minute_refused(rg, tmp_path, monkeypatch):
    p = tmp_path / "BTCUSDT_dup_1m.csv"
    t0 = int(pd.Timestamp("2024-01-01", tz="UTC").value // 10**6)
    _csv(p, 101, 1440, dup=(t0 + 100 * DAY + 5 * 60_000,))
    monkeypatch.setattr(rg, "SRC", p)
    with pytest.raises(SystemExit):
        rg.load()
