"""Tests for services.grid_coordinator (movement exhaustion detector)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from services.grid_coordinator import loop as gc


def _make_uptrend_with_exhaustion_df() -> pd.DataFrame:
    """BTC 1h frame с восходящим движением до пика + истощение на верху."""
    n = 50
    # 40 баров роста, 10 баров consolidation на новом хае с малым объёмом
    closes = [70000 + i * 200 for i in range(40)]  # рост с 70000 до 77800
    closes += [77800, 77900, 78000, 78050, 78100, 78050, 78000, 77950, 77900, 77850]
    # Объём: на росте — высокий, на верхах — низкий
    volumes = [500.0] * 40 + [200.0, 180.0, 150.0, 130.0, 120.0, 110.0, 100.0, 95.0, 90.0, 85.0]
    return pd.DataFrame({
        "open": [c - 50 for c in closes],
        "high": [c + 50 for c in closes],
        "low": [c - 100 for c in closes],
        "close": closes,
        "volume": volumes,
    })


def _make_flat_df() -> pd.DataFrame:
    n = 50
    return pd.DataFrame({
        "open": [80000.0] * n,
        "high": [80050.0] * n,
        "low": [79950.0] * n,
        "close": [80000.0] * n,
        "volume": [300.0] * n,
    })


def test_evaluate_no_signals_in_flat_market():
    btc = _make_flat_df()
    eth = _make_flat_df()
    deriv = {"BTCUSDT": {"oi_change_1h_pct": 0.1, "funding_rate_8h": 0.00001}}
    ev = gc.evaluate_exhaustion(btc, eth, deriv)
    # Во флете не должно быть истощения (после калибровки 2026-05 noise floor ~2)
    assert ev["upside_score"] <= 2
    assert ev["downside_score"] <= 2


def test_evaluate_thin_data():
    btc = pd.DataFrame({"open": [1] * 10, "high": [1] * 10, "low": [1] * 10,
                        "close": [1] * 10, "volume": [1] * 10})
    ev = gc.evaluate_exhaustion(btc, None, {})
    assert ev["upside_score"] == 0
    assert ev["downside_score"] == 0


def test_evaluate_uptrend_with_exhaustion():
    btc = _make_uptrend_with_exhaustion_df()
    eth = _make_uptrend_with_exhaustion_df()
    deriv = {"BTCUSDT": {"oi_change_1h_pct": 1.5, "funding_rate_8h": 0.0006}}
    ev = gc.evaluate_exhaustion(btc, eth, deriv)
    # Должен быть upside_score >=1 (минимум RSI или MFI overbought)
    assert ev["upside_score"] >= 1
    details = ev["details"]
    # RSI должен быть высоким после роста
    assert details["rsi_btc_now"] > 50


def test_format_card_upside():
    details = {
        "btc_close": 80500, "rsi_btc_now": 78.0, "mfi_btc_now": 76.0,
        "vol_z_now": -0.5, "oi_change_1h_pct": 1.2,
        "funding_rate_8h": 0.0005, "eth_rsi_now": 72.0,
        "btc_eth_corr_30h": 0.85,
        "up_signals": {"rsi_high_falling": True, "mfi_high": True, "eth_sync_high": True,
                       "volume_no_confirm_at_high": False, "oi_rising_funding_high": False},
    }
    card = gc._format_card("up", 3, details)
    # 2026-06-15 (ревью Вина): up-импульс честно переформулирован — слабый перевес,
    # НЕ вероятность, явная пометка перекупленности; фейковый «≈100% (n=3)» убран.
    assert "ИМПУЛЬС ВВЕРХ" in card
    assert "3/6" in card
    assert "ПЕРЕКУПЛЕННОСТЬ" in card
    assert "НЕ статистика" in card
    assert "≈100%" not in card and "P(выше" not in card  # фейковая вероятность убрана
    assert "LONG-вход" in card  # совет: вход только с реклеймом структуры
    assert "rsi_high_falling" in card
    assert "78.0" in card


def test_format_card_downside():
    details = {
        "btc_close": 70000, "rsi_btc_now": 22.0, "mfi_btc_now": 23.0,
        "vol_z_now": -0.3, "oi_change_1h_pct": 1.5,
        "funding_rate_8h": -0.0005, "eth_rsi_now": 28.0,
        "btc_eth_corr_30h": 0.75,
        "down_signals": {"rsi_low_rising": True, "mfi_low": True, "eth_sync_low": True,
                         "volume_no_confirm_at_low": True, "oi_rising_funding_low": False},
    }
    card = gc._format_card("down", 4, details)
    # 2026-05-29: down re-framed as downside-continuation (not reversal/fade).
    assert "ИМПУЛЬС ВНИЗ" in card
    assert "4/6" in card
    assert "LONG" in card  # advice still references protecting LONG grids
    assert "ПРОДОЛЖАЕТСЯ" in card


def test_check_cooldown_blocks_within_window():
    now = datetime.now(timezone.utc)
    dedup = {"up": (now - timedelta(seconds=gc.COOLDOWN_SEC // 2)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    assert gc._check_cooldown("up", dedup, now) is False


def test_check_cooldown_allows_after_window():
    now = datetime.now(timezone.utc)
    dedup = {"up": (now - timedelta(seconds=gc.COOLDOWN_SEC + 60)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    assert gc._check_cooldown("up", dedup, now) is True


def test_check_cooldown_no_prior_record():
    now = datetime.now(timezone.utc)
    assert gc._check_cooldown("up", {}, now) is True


def test_rsi_helper_basic():
    # Восходящий ряд → RSI должен быть высоким
    series = pd.Series(range(50, 100))
    rsi = gc._rsi(series, 14)
    assert rsi.iloc[-1] > 70


def test_rsi_helper_falling():
    series = pd.Series(range(100, 50, -1))
    rsi = gc._rsi(series, 14)
    assert rsi.iloc[-1] < 30


def test_mfi_helper_basic():
    n = 30
    high = pd.Series([100.0 + i for i in range(n)])
    low = high - 1
    close = high - 0.5
    volume = pd.Series([100.0] * n)
    mfi = gc._mfi(high, low, close, volume)
    # На равномерном росте MFI близок к 100
    assert mfi.iloc[-1] > 80


def test_vol_z_helper():
    volume = pd.Series([100.0] * 20 + [500.0])
    vz = gc._vol_z(volume, period=20)
    assert vz.iloc[-1] > 2  # spike


def test_journal_append(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "JOURNAL_PATH", tmp_path / "j.jsonl")
    gc._journal({"ts": "2026-05-09T18:00:00Z", "direction": "up", "score": 4})
    lines = (tmp_path / "j.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["direction"] == "up"
    assert rec["score"] == 4
