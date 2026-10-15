"""Tests for range_hunter.signal — pure detection logic."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from services.range_hunter.signal import (
    DEFAULT_PARAMS,
    RangeHunterParams,
    compute_signal,
    format_tg_card,
)


def _make_window(prices: list[float], start: datetime | None = None) -> pd.DataFrame:
    """Helper: build 1m OHLCV from close prices."""
    if start is None:
        start = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    rows = []
    for i, p in enumerate(prices):
        rows.append({
            "high": p * 1.0001,
            "low": p * 0.9999,
            "close": p,
            "volume": 1.0,
        })
    df = pd.DataFrame(rows)
    df.index = pd.date_range(start, periods=len(prices), freq="1min", tz="UTC")
    return df


def test_signal_fires_on_quiet_range() -> None:
    # 240 баров, цена 80000 ± 30 (range 0.075%) — qualifies for ренж
    np.random.seed(42)
    prices = 80000 + np.random.uniform(-30, 30, 240)
    df = _make_window(prices.tolist())
    sig = compute_signal(df, DEFAULT_PARAMS)
    assert sig is not None
    assert sig.range_4h_pct < DEFAULT_PARAMS.range_max_pct
    assert sig.atr_pct < DEFAULT_PARAMS.atr_pct_max
    assert abs(sig.trend_pct_per_h) < DEFAULT_PARAMS.trend_max_pct_per_h


def test_signal_blocked_by_wide_range() -> None:
    # Range > 1% — слишком широко
    prices = [80000.0] * 100 + [81000.0] * 140
    df = _make_window(prices)
    sig = compute_signal(df, DEFAULT_PARAMS)
    assert sig is None


def test_signal_blocked_by_trend() -> None:
    # Линейный uptrend ~0.2%/час — выходит за trend_max (0.10%/час)
    # slope per minute = 80000 * 0.002 / 60 ≈ 2.67 USD/min
    prices = [80000.0 + i * 3.0 for i in range(240)]  # ~0.27%/час
    df = _make_window(prices)
    sig = compute_signal(df, DEFAULT_PARAMS)
    assert sig is None


def test_signal_blocked_by_high_atr() -> None:
    # Большие свечи (high-low большие) — high ATR
    rows = []
    for i in range(240):
        rows.append({"high": 80100, "low": 79900, "close": 80000, "volume": 1})
    df = pd.DataFrame(rows)
    df.index = pd.date_range("2026-05-14", periods=240, freq="1min", tz="UTC")
    sig = compute_signal(df, DEFAULT_PARAMS)
    assert sig is None  # ATR ≈ 0.25%, выше 0.10% порога


def test_signal_insufficient_data() -> None:
    df = _make_window([80000.0] * 100)  # < 240 нужных
    sig = compute_signal(df, DEFAULT_PARAMS)
    assert sig is None


def test_signal_buy_sell_levels_correct(monkeypatch) -> None:
    # изоляция от живого state: свежие VAL/VAH рядом с ценой теста подменяют симметричные уровни
    monkeypatch.setattr("services.manual_levels.get_levels", lambda *a, **k: None)
    np.random.seed(7)
    prices = 81500 + np.random.uniform(-20, 20, 240)
    df = _make_window(prices.tolist())
    sig = compute_signal(df, DEFAULT_PARAMS)
    assert sig is not None
    expected_buy = sig.mid * (1 - DEFAULT_PARAMS.width_pct / 100)
    expected_sell = sig.mid * (1 + DEFAULT_PARAMS.width_pct / 100)
    assert abs(sig.buy_level - expected_buy) < 0.5
    assert abs(sig.sell_level - expected_sell) < 0.5
    assert sig.size_btc > 0


def test_format_tg_card_contains_essentials() -> None:
    np.random.seed(3)
    prices = 80000 + np.random.uniform(-25, 25, 240)
    df = _make_window(prices.tolist())
    sig = compute_signal(df, DEFAULT_PARAMS)
    assert sig is not None
    text = format_tg_card(sig)
    assert "RANGE HUNTER" in text
    assert "BUY" in text
    assert "SELL" in text
    assert "EV" in text
    assert f"${sig.buy_level:,.2f}" in text or f"{sig.buy_level:,.2f}" in text
