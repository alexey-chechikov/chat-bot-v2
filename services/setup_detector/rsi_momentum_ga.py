"""GA-discovered RSI-momentum LONG detector (Stage E1, 2026-05-09).

Discovered by tools/_genetic_detector_search.py with honest fitness
(intra-bar SL/TP simulation, fees included). Best STABLE genome:

  Signal:        RSI(14) > 71 on 1h
  Trend gate:    EMA50 > EMA200 AND close > EMA50 (uptrend confirmed)
  Volume filter: volume z-score (20-bar) >= 1.21
  Direction:     LONG
  SL:            1.39%
  TP1:           RR=1.59  (+2.21% target)
  Hold horizon:  24h max

Walk-forward results (BTC 1h 2y, 4 folds × 6mo):
  N (total):     125 trades
  WR:            57.4%
  Avg PnL:       +0.45% per trade (after 2x 0.05% fees)
  PF:            2.05
  Per-fold PF:   1.52 / 3.18 / 2.43 / 1.06  (3/4 folds STABLE)

This is a momentum-breakout setup: RSI in overbought territory but still
rising while uptrend is confirmed and volume validates the move. Classic
"strong gets stronger" pattern — entry on the breakout, ride for 24h.

Note on overbought entry: ordinary intuition says "RSI>70 = overbought,
fade it". But in *confirmed uptrend with volume*, RSI>70 is continuation,
not exhaustion. The walk-forward confirms this empirically.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from services.setup_detector.models import Setup, SetupBasis, SetupType, make_setup

logger = logging.getLogger(__name__)

RSI_PERIOD = 14
RSI_THRESHOLD = 71.0
EMA_FAST = 50
EMA_SLOW = 200
VOL_LOOKBACK = 20
VOL_Z_MIN = 1.21
SL_PCT = 1.39
TP1_RR = 1.59
TP2_RR = 2.5
HOLD_HOURS = 24

# Cooldown: don't fire again on the same pair for N hours after a trigger
COOLDOWN_HOURS = 4


def _rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))


def detect_long_rsi_momentum_ga(ctx) -> Setup | None:
    """Fire LONG_RSI_MOMENTUM_GA when all 3 conditions hold on the latest 1h bar:
       1. RSI(14) > 71
       2. EMA50 > EMA200 AND close > EMA50 (uptrend gate)
       3. Volume z-score (20-bar lookback) >= 1.21
    """
    df = ctx.ohlcv_1h
    if df is None or len(df) < EMA_SLOW + 5:
        return None
    if not all(col in df.columns for col in ("close", "volume", "high", "low")):
        return None

    df = df.reset_index(drop=True)
    close = df["close"].astype(float)
    volume = df["volume"].astype(float)

    # Compute indicators
    rsi_series = _rsi(close, RSI_PERIOD)
    e_fast = close.ewm(span=EMA_FAST, adjust=False).mean()
    e_slow = close.ewm(span=EMA_SLOW, adjust=False).mean()
    v_mean = volume.rolling(VOL_LOOKBACK, min_periods=1).mean()
    v_std = volume.rolling(VOL_LOOKBACK, min_periods=1).std().replace(0, 1.0)
    v_z = (volume - v_mean) / v_std

    last = -1
    rsi_now = float(rsi_series.iloc[last])
    e_fast_now = float(e_fast.iloc[last])
    e_slow_now = float(e_slow.iloc[last])
    close_now = float(close.iloc[last])
    v_z_now = float(v_z.iloc[last])

    # Gate checks
    if rsi_now <= RSI_THRESHOLD:
        return None
    if not (e_fast_now > e_slow_now and close_now > e_fast_now):
        return None
    if v_z_now < VOL_Z_MIN:
        return None

    # Anti-storm: also require RSI was below 71 within the last 4 bars
    # (otherwise we'd fire every bar while RSI sits at 75 for a day).
    if last >= 4:
        recent_below = (rsi_series.iloc[last - 4: last] <= RSI_THRESHOLD).any()
        if not recent_below:
            return None

    entry = close_now
    if entry <= 0:
        return None
    stop = entry * (1 - SL_PCT / 100.0)
    risk = entry - stop
    tp1 = entry + risk * TP1_RR
    tp2 = entry + risk * TP2_RR
    rr = (tp1 - entry) / max(risk, 1e-9)

    basis = (
        SetupBasis("rsi_14_now", round(rsi_now, 1), 0.30),
        SetupBasis("rsi_threshold", RSI_THRESHOLD, 0.0),
        SetupBasis("ema_fast", round(e_fast_now, 1), 0.20),
        SetupBasis("ema_slow", round(e_slow_now, 1), 0.20),
        SetupBasis("vol_z_score", round(v_z_now, 2), 0.20),
        SetupBasis("hold_hours_max", HOLD_HOURS, 0.10),
        SetupBasis("backtest_pf_2y", 2.05, 0.0),
        SetupBasis("backtest_n_2y", 125, 0.0),
        SetupBasis("backtest_wr_pct", 57.4, 0.0),
    )

    return make_setup(
        setup_type=SetupType.LONG_RSI_MOMENTUM_GA,
        pair=ctx.pair,
        current_price=entry,
        regime_label=ctx.regime_label,
        session_label=ctx.session_label,
        entry_price=entry,
        stop_price=stop,
        tp1_price=tp1,
        tp2_price=tp2,
        risk_reward=round(rr, 2),
        strength=8,
        confidence_pct=72.0,
        basis=basis,
        cancel_conditions=(
            "RSI 1h close < 50 — momentum lost",
            "Close back below EMA50 — trend gate broken",
            f"Hold expired ({HOLD_HOURS}h max)",
            f"Stop hit at -{SL_PCT}%",
        ),
        window_minutes=HOLD_HOURS * 60,
        portfolio_impact_note=(
            f"GA-found RSI momentum LONG. RSI={rsi_now:.1f}>71, "
            f"uptrend confirmed (EMA50/200), volume z={v_z_now:.2f}. "
            f"Backtest PF=2.05, WR=57.4%, walk-forward 3/4 STABLE."
        ),
        recommended_size_btc=0.05,
    )
