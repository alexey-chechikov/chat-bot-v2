"""Аддендум GPT 13.10, B2: месяцы research/weex/fast_grid.run — по UTC-метке КАЖДОЙ минуты; на смене месяца
капитал прошлого месяца — по закрытию предыдущей минуты, до обработки бара нового месяца."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from tests.research_tools._util import load


@pytest.fixture(scope="module")
def fg():
    return load("research/weex/fast_grid.py")


def _utc(*a) -> int:
    return int(datetime(*a, tzinfo=timezone.utc).timestamp())


def test_three_minutes_across_month_boundary(fg):
    ts = np.array([_utc(2026, 1, 31, 23, 59) + i * 60 for i in range(3)], dtype=np.int64)
    o, h = np.array([100.0, 100, 100]), np.array([100.0, 100, 100])
    l, c = np.array([99.0, 100, 100]), np.array([99.0, 100, 100])
    r = fg.run((ts, o, h, l, c), sides=("LONG",), step=1, target=1, order_qty=1, cap_usd=10_000)
    jan = -99 * 0.00016                                       # лот куплен по 99, январь закрылся по 99
    assert r["по месяцам"] == [("2026-01", round(jan, 2)), ("2026-02", round(r["итог"] - jan, 2))]


def _walk(stamps: np.ndarray, seed: int = 7):
    rng = np.random.default_rng(seed)
    c = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.003, len(stamps))))
    o = np.r_[100.0, c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.001, len(stamps))))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.001, len(stamps))))
    return o, h, l, c


def test_months_offset_start_gaps_several_months(fg):
    rng = np.random.default_rng(3)
    a = np.arange(_utc(2026, 1, 31, 21, 17), _utc(2026, 2, 1, 3, 0), 60)        # старт не в полночь
    b = np.arange(_utc(2026, 2, 28, 22, 40), _utc(2026, 3, 1, 2, 0), 60)        # прыжок через февраль в март
    ts = np.r_[a, b].astype(np.int64)
    ts = ts[rng.random(len(ts)) > 0.15]                                           # пропуски минут
    o, h, l, c = _walk(ts)
    kw = dict(sides=("LONG", "SHORT"), step=0.2, target=0.3, order_qty=1.0, cap_usd=1e7)
    r = fg.run((ts, o, h, l, c), **kw)
    cum = []
    for bound in (_utc(2026, 2, 1), _utc(2026, 3, 1)):                           # эталон: прогон, обрезанный у границы
        m = ts < bound
        cum.append(fg.run((ts[m], o[m], h[m], l[m], c[m]), **kw)["итог"])
    cum.append(r["итог"])
    want = [("2026-01", cum[0]), ("2026-02", cum[1] - cum[0]), ("2026-03", cum[2] - cum[1])]
    got = r["по месяцам"]
    assert [m for m, _ in got] == [m for m, _ in want]
    for (_, g), (_, w) in zip(got, want):
        assert g == pytest.approx(w, abs=0.0051)
    assert sum(v for _, v in got) == pytest.approx(r["итог"], abs=0.005 * len(got))
