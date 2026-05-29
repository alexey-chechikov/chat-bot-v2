"""Tests for the alt decorrelation-divergence detector."""
from __future__ import annotations

import numpy as np
import pandas as pd

from services.alt_decorr import loop as ad


def _frame(closes):
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame({
        "open": closes, "high": closes * 1.001, "low": closes * 0.999,
        "close": closes, "volume": np.full(len(closes), 100.0),
    })


def test_corr_perfectly_correlated_is_one():
    base = np.cumsum(np.random.RandomState(0).randn(40)) + 100
    alt = _frame(base * 2.0)   # same shape, scaled → corr of returns ~1
    btc = _frame(base)
    assert ad._corr_alt_btc(alt, btc) > 0.95


def test_corr_anticorrelated_is_negative():
    base = np.cumsum(np.random.RandomState(1).randn(40)) + 100
    alt = _frame(200 - base)   # mirrored → returns anti-correlated
    btc = _frame(base)
    assert ad._corr_alt_btc(alt, btc) < -0.5


def test_thin_data_no_fire():
    ev = ad.evaluate_alt_decorr(_frame([100] * 10), _frame([100] * 10))
    assert ev["fire"] is False


def test_no_fire_when_correlated_even_if_div():
    # flat/identical series: no divergence AND corr high → must not fire
    base = list(np.linspace(100, 110, 60))
    ev = ad.evaluate_alt_decorr(_frame(base), _frame(base))
    assert ev["fire"] is False
    assert ev["side"] is None


def test_bearish_detector_returns_list():
    base = list(np.linspace(100, 130, 80))
    out = ad._detect_bearish_div_bars(_frame(base))
    assert isinstance(out, list)


def test_corr_gate_constant_sane():
    assert 0.0 < ad.CORR_GATE < 1.0
    assert ad.SL_PCT > 0 and ad.TP_PCT > ad.SL_PCT  # positive RR
