"""adapt() сканера после Win-правок 2026-06-11: охват от волатильности + score к пиле."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import _alt_grid_scan as sc


def test_span_scales_with_volatility():
    # vr=1 → 12%, vr=2 → ~17%, vr=4 → 24 (кап), vr<1 → пол 12 (vr клампится к 1)... пол 8
    a1 = sc.adapt(price=1.0, atrp=2.0, btc_atrp=2.0, btc_notional=300)
    assert a1["span"] == 12.0
    a2 = sc.adapt(price=1.0, atrp=4.0, btc_atrp=2.0, btc_notional=300)
    assert 16.5 <= a2["span"] <= 17.5
    a4 = sc.adapt(price=1.0, atrp=8.0, btc_atrp=2.0, btc_notional=300)
    assert a4["span"] == 24.0  # кап


def test_size_shrinks_when_span_widens():
    """Волатильнее → шире охват → меньше поза при том же $-риске."""
    calm = sc.adapt(price=1.0, atrp=2.0, btc_atrp=2.0, btc_notional=300)
    wild = sc.adapt(price=1.0, atrp=8.0, btc_atrp=2.0, btc_notional=300)
    assert wild["maxsz"] < calm["maxsz"]


def test_score_prefers_saw_over_pump():
    m_saw = dict(price=1.0, atrp=2.0, rng24=4.0, t7=5.0, t1=1.0, er=0.1)
    m_pump = dict(price=1.0, atrp=2.0, rng24=20.0, t7=40.0, t1=15.0, er=0.3)
    s_saw = sc.score_row(m_saw, 1e9, pump=False, danger=False, thin=False)
    s_pump = sc.score_row(m_pump, 1e9, pump=True, danger=False, thin=False)
    assert s_pump == 0.0
    assert s_saw > 0
    # размах >4% штрафуется, не награждается
    m_wide = dict(m_saw, rng24=12.0)
    assert sc.score_row(m_wide, 1e9, pump=False, danger=False, thin=False) < s_saw
