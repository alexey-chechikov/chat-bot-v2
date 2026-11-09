"""research/chart_walk_20261105/features_ext.py: внешние ряды берутся только известные к часу и не старше max_age;
ценовые дивергенции не заглядывают вперёд."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "research" / "chart_walk_20261105"))
import features_ext as fe  # noqa: E402

from tests.services.btc_signals.test_features import cut, rich  # noqa: E402


def test_asof_only_known_and_fresh():
    tk = np.array([100, 200, 300])
    v = np.array([1.0, 2.0, 3.0])
    t = np.array([50, 100, 150, 299, 300, 900])
    got = fe.asof(tk, v, t, max_age=200)
    assert np.isnan(got[0]) and got[1] == 1.0 and got[2] == 1.0 and got[3] == 2.0 and got[4] == 3.0
    assert np.isnan(got[5])


def test_asof_unsorted_input():
    got = fe.asof(np.array([300, 100]), np.array([3.0, 1.0]), np.array([150, 310]), 1000)
    assert list(got) == [1.0, 3.0]


def test_div_block_no_lookahead():
    a, _ = rich()
    full = fe.div_block(a)
    for i in (24 * 100 + 7, 24 * 200 + 1, len(a["t"]) - 5):
        part = fe.div_block(cut(a, i + 1))
        for k, v in full.items():
            x, y = v[i], part[k][i]
            assert (np.isnan(x) and np.isnan(y)) or x == pytest.approx(y, abs=1e-12), (k, i)


def test_rank_and_pos_helpers():
    x = np.array([1.0, 2, 3, 4, 5, 0])
    p = fe.pos_in(x, 3)
    assert np.isnan(p[1]) and p[2] == 1.0 and p[5] == 0.0
    r = fe.rank_in(np.array([5.0, 1, 2, 3, 4, 10]), 4)
    assert r[5] == 1.0 and r[4] == pytest.approx(0.75)
