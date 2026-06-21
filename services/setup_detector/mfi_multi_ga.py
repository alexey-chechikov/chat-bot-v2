"""GA-discovered multi-asset SHORT detector (Stage E1 multi, 2026-05-09).

Discovered by tools/_genetic_detector_search_multi.py with honest fitness
(intra-bar SL/TP, fees, BTC + ETH correlation gate + XRP lead confirmation).

Best STABLE genome:
  Signal:      MFI(14) < 71.3 on BTC 1h
  Trend gate:  disabled (relies on multi-asset confirmation instead)
  Volume:      z-score(20) >= 1.0 (above-average volume)
  ETH gate:    BTC↔ETH 30h Pearson >= 0.76 (assets in sync)
  XRP lead:    XRP MFI < 71.3 within last 4 bars (XRP confirms)
  Direction:   SHORT
  SL:          1.43%
  TP1:         RR=3.9  (+5.58% target)
  Hold:        1h max

Walk-forward results (BTC 1h 2y, 4 folds × ~6mo):
  N (total):     406 trades (≈ 200/year — high freq)
  WR:            59.2%
  PF:            2.78
  Per-fold PF:   5.62 / 1.90 / 2.84 / 0.75  (3/4 STABLE)

Why it's a real edge:
  Classic MFI top-fade pattern but heavily filtered: only fires when
  multi-asset alignment is high (BTC↔ETH corr) AND XRP showed the same
  weakness recently. This filters out many false tops where BTC drops
  alone and gets bought back. Multi-asset agreement = wide-base distribution
  rather than a single-asset hiccup.

  Note the 1h hold horizon — this is a *quick fade*, not a trend trade.
  TP target 5.58% in 1 hour means we want a sharp drop. If it doesn't
  come within the hour, we exit at close (mostly small win/loss).
"""
from __future__ import annotations

import logging

import pandas as pd

from services.setup_detector.models import Setup, SetupBasis, SetupType, make_setup

logger = logging.getLogger(__name__)

MFI_PERIOD = 14
MFI_THRESHOLD = 71.3
VOL_LOOKBACK = 20
VOL_Z_MIN = 1.0
ETH_CORR_LOOKBACK = 30
ETH_CORR_MIN = 0.76
XRP_LEAD_BARS = 4
SL_PCT = 1.43
TP1_RR = 3.9
TP2_RR = 5.5
HOLD_HOURS = 1


def _mfi(high: pd.Series, low: pd.Series, close: pd.Series,
         volume: pd.Series, period: int = MFI_PERIOD) -> pd.Series:
    typical = (high + low + close) / 3.0
    raw = typical * volume
    delta = typical.diff()
    pos = raw.where(delta > 0, 0.0)
    neg = raw.where(delta < 0, 0.0)
    pos_sum = pos.rolling(period, min_periods=1).sum()
    neg_sum = neg.rolling(period, min_periods=1).sum().replace(0, 1e-9)
    mr = pos_sum / neg_sum
    return 100 - (100 / (1 + mr))


def _load_companion(symbol: str, limit: int = 200) -> pd.DataFrame | None:
    try:
        from core.data_loader import load_klines
        return load_klines(symbol=symbol, timeframe="1h", limit=limit)
    except Exception:
        logger.exception("mfi_multi_ga.companion_load_failed symbol=%s", symbol)
        return None


def _pearson(a: pd.Series, b: pd.Series, n: int) -> float:
    n = min(len(a), len(b), n)
    if n < 10:
        return 0.0
    a_tail = a.iloc[-n:].astype(float).reset_index(drop=True)
    b_tail = b.iloc[-n:].astype(float).reset_index(drop=True)
    try:
        return float(a_tail.corr(b_tail))
    except Exception:
        return 0.0


def detect_short_mfi_multi_ga(ctx) -> Setup | None:
    """Fire SHORT_MFI_MULTI_GA when:
       1. BTC MFI(14) < 71.3 with vol_z >= 1.0
       2. BTC↔ETH 30h Pearson corr >= 0.76
       3. XRP MFI < 71.3 within last 4 bars
    """
    df = ctx.ohlcv_1h
    if df is None or len(df) < 60:
        return None
    if not all(col in df.columns for col in ("close", "high", "low", "volume")):
        return None
    if str(getattr(ctx, "pair", "")).upper() != "BTCUSDT":
        return None

    df = df.reset_index(drop=True)
    btc_mfi = _mfi(df["high"], df["low"], df["close"], df["volume"])
    last = -1
    btc_mfi_now = float(btc_mfi.iloc[last])

    if btc_mfi_now >= MFI_THRESHOLD:
        return None

    # Volume z-score
    v = df["volume"].astype(float)
    v_mean = v.rolling(VOL_LOOKBACK, min_periods=1).mean()
    v_std = v.rolling(VOL_LOOKBACK, min_periods=1).std().replace(0, 1.0)
    v_z = float(((v - v_mean) / v_std).iloc[last])
    if v_z < VOL_Z_MIN:
        return None

    # Anti-storm: previous bar should have had MFI >= threshold (fresh cross)
    if last >= 1:
        prev_mfi = float(btc_mfi.iloc[last - 1])
        if prev_mfi < MFI_THRESHOLD:
            # MFI was already below — already triggered, skip
            return None

    # ETH correlation gate
    eth_df = _load_companion("ETHUSDT", limit=200)
    if eth_df is None or len(eth_df) < ETH_CORR_LOOKBACK:
        return None
    eth_close = eth_df["close"].astype(float).iloc[-len(df):].reset_index(drop=True) \
        if len(eth_df) >= len(df) else eth_df["close"].astype(float)
    btc_close = df["close"].astype(float).iloc[-len(eth_close):].reset_index(drop=True)
    corr = _pearson(btc_close, eth_close, ETH_CORR_LOOKBACK)
    if corr < ETH_CORR_MIN:
        return None

    # XRP lead
    xrp_df = _load_companion("XRPUSDT", limit=200)
    if xrp_df is None or len(xrp_df) < MFI_PERIOD * 3:
        return None
    if not all(c in xrp_df.columns for c in ("high", "low", "close", "volume")):
        return None
    xrp = xrp_df.reset_index(drop=True)
    xrp_mfi = _mfi(xrp["high"].astype(float), xrp["low"].astype(float),
                   xrp["close"].astype(float), xrp["volume"].astype(float))
    if len(xrp_mfi) < XRP_LEAD_BARS:
        return None
    xrp_lead_window = xrp_mfi.iloc[-XRP_LEAD_BARS:]
    if not (xrp_lead_window < MFI_THRESHOLD).any():
        return None

    entry = float(df["close"].iloc[last])
    if entry <= 0:
        return None
    stop = entry * (1 + SL_PCT / 100.0)  # SHORT: stop ABOVE entry
    risk = stop - entry
    tp1 = entry - risk * TP1_RR
    tp2 = entry - risk * TP2_RR
    rr = (entry - tp1) / max(risk, 1e-9)

    basis = (
        SetupBasis("btc_mfi_now", round(btc_mfi_now, 1), 0.25),
        SetupBasis("vol_z_score", round(v_z, 2), 0.20),
        SetupBasis("btc_eth_corr_30h", round(corr, 3), 0.20),
        SetupBasis("xrp_lead_confirmed", "yes", 0.20),
        SetupBasis("hold_hours_max", HOLD_HOURS, 0.0),
        SetupBasis("backtest_pf_2y", 2.78, 0.0),
        SetupBasis("backtest_n_2y", 406, 0.0),
        SetupBasis("backtest_wr_pct", 59.2, 0.0),
    )

    return make_setup(
        setup_type=SetupType.SHORT_MFI_MULTI_GA,
        pair=ctx.pair,
        current_price=entry,
        regime_label=ctx.regime_label,
        session_label=ctx.session_label,
        entry_price=entry,
        stop_price=stop,
        tp1_price=tp1,
        tp2_price=tp2,
        risk_reward=round(rr, 2),
        strength=9,
        confidence_pct=78.0,
        basis=basis,
        cancel_conditions=(
            f"MFI 1h close > 75 — momentum reversed",
            f"BTC↔ETH 30h corr drops below 0.5 — assets de-sync",
            f"Hold expired ({HOLD_HOURS}h max)",
            f"Stop hit at +{SL_PCT}%",
        ),
        window_minutes=HOLD_HOURS * 60,
        portfolio_impact_note=(
            f"GA multi-asset SHORT. MFI={btc_mfi_now:.1f}<71.3 + vol z={v_z:.2f} + "
            f"BTC↔ETH corr={corr:.2f}>0.76 + XRP confirmed. "
            f"Backtest PF=2.78, WR=59.2%, walk-forward 3/4 STABLE."
        ),
        recommended_size_btc=0.05,
    )
