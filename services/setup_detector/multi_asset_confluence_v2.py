"""Stage B2 — 3-asset confluence v2 with correlation gate.

Extends multi_asset_confluence.detect_long_multi_asset_confluence:
  v1: BTC bull DIV (conf>=2) + ETH bull DIV within ±4h → LONG signal (PF=3.88)
  v2: BTC + ETH + XRP bull DIV all within ±4h
      AND BTC↔ETH 30-bar 1h close correlation > 0.7

Hypothesis (handoff 2026-05-09 Stage B2):
  Adding XRP as 3rd confirm and a correlation gate should raise PF further at
  the cost of fewer signals. If sample size remains tractable (N>=15) and
  PF >= 4.5, this becomes the preferred fire path; v1 falls back to "second
  tier" (still produces signals, but downgraded confidence).

NOT a replacement for v1 — fires alongside as a separate setup type so we
can A/B compare in walk-forward without modifying v1 fire conditions.
"""
from __future__ import annotations

import logging

import pandas as pd

from services.setup_detector.models import Setup, SetupBasis, SetupType, make_setup
from services.setup_detector.multi_divergence import (
    DIV_WINDOW_BARS,
    INDICATOR_PIVOT_TOLERANCE,
    MIN_CONFLUENCE,
    PIVOT_LOOKBACK,
    _agreeing_indicators_for_bullish,
    _build_indicators,
    _find_pivots,
    _is_double_trend_down,
)
from services.setup_detector.multi_asset_confluence import (
    CROSS_ASSET_WINDOW_HOURS,
    _detect_bullish_div_bars,
    _load_companion_klines,
)

logger = logging.getLogger(__name__)

CORRELATION_LOOKBACK_BARS = 30   # 30h on 1h frame
CORRELATION_THRESHOLD = 0.70     # Pearson on close
V2_SL_PCT = 1.0
V2_TP1_RR = 2.5
V2_TP2_RR = 5.0


def _pearson_30bar(a: pd.Series, b: pd.Series) -> float:
    """Compute Pearson correlation of last `CORRELATION_LOOKBACK_BARS` of two
    close series. Aligns by tail length. Returns 0.0 on insufficient data."""
    if a is None or b is None:
        return 0.0
    n = min(len(a), len(b), CORRELATION_LOOKBACK_BARS)
    if n < 10:
        return 0.0
    a_tail = a.iloc[-n:].astype(float).reset_index(drop=True)
    b_tail = b.iloc[-n:].astype(float).reset_index(drop=True)
    try:
        return float(a_tail.corr(b_tail))
    except Exception:
        return 0.0


def detect_long_multi_asset_confluence_v2(ctx) -> Setup | None:
    """BTC bull DIV + ETH bull DIV + XRP bull DIV (all within ±4h) AND
    BTC↔ETH close-corr (last 30h) > 0.7 → fire v2 LONG."""
    df = ctx.ohlcv_1h
    if df is None or len(df) < 50:
        return None
    if not all(col in df.columns for col in ("high", "low", "close", "volume")):
        return None
    if str(getattr(ctx, "pair", "")).upper() != "BTCUSDT":
        return None
    if _is_double_trend_down(ctx):
        return None

    df = df.reset_index(drop=True)
    indicators = _build_indicators(df)
    pivots_by_indicator = {name: _find_pivots(ind) for name, ind in indicators.items()}
    price_pivots = _find_pivots(df["low"]).lows
    if len(price_pivots) < 2:
        return None

    n = len(df)
    last_bar = n - 1
    last_close = float(df["close"].iloc[last_bar])

    # Find a fresh BTC bull div confirmed on last_bar.
    btc_match = None
    for j in range(len(price_pivots) - 1, 0, -1):
        cur_idx = price_pivots[j]
        prev_idx = price_pivots[j - 1]
        if cur_idx - prev_idx > DIV_WINDOW_BARS:
            continue
        cur_low = float(df["low"].iloc[cur_idx])
        prev_low = float(df["low"].iloc[prev_idx])
        if cur_low >= prev_low:
            continue
        conf_idx = cur_idx + PIVOT_LOOKBACK
        if conf_idx != last_bar:
            return None  # latest pair would not be the fresh one
        agreeing = _agreeing_indicators_for_bullish(
            indicators, pivots_by_indicator,
            prev_idx, cur_idx, INDICATOR_PIVOT_TOLERANCE,
        )
        if len(agreeing) < MIN_CONFLUENCE:
            continue
        btc_match = {"prev_low": prev_low, "cur_low": cur_low, "agreeing": agreeing}
        break

    if btc_match is None:
        return None

    if "ts" in df.columns:
        btc_ts_ms = int(df["ts"].iloc[last_bar])
    elif "open_time" in df.columns:
        btc_ts_ms = int(df["open_time"].iloc[last_bar].timestamp() * 1000)
    else:
        return None

    # Companions: ETH and XRP.
    eth_df = _load_companion_klines("ETHUSDT", limit=200)
    xrp_df = _load_companion_klines("XRPUSDT", limit=200)
    if eth_df is None or len(eth_df) < 50:
        return None
    if xrp_df is None or len(xrp_df) < 50:
        return None

    def _normalize_ts(d: pd.DataFrame) -> pd.DataFrame:
        d = d.copy().reset_index(drop=True)
        if "ts" not in d.columns and "open_time" in d.columns:
            d["ts"] = (d["open_time"].astype("int64") // 10**6).astype("int64")
        return d

    eth_klines = _normalize_ts(eth_df)
    xrp_klines = _normalize_ts(xrp_df)

    def _has_companion_div(klines: pd.DataFrame) -> bool:
        bars = _detect_bullish_div_bars(klines)
        if not bars:
            return False
        for bar in bars:
            ts_ms = int(klines["ts"].iloc[bar])
            delta_h = abs(ts_ms - btc_ts_ms) / (60 * 60 * 1000)
            if delta_h <= CROSS_ASSET_WINDOW_HOURS:
                return True
        return False

    if not _has_companion_div(eth_klines):
        return None
    if not _has_companion_div(xrp_klines):
        return None

    # Correlation gate: BTC ↔ ETH close 30-bar Pearson.
    corr = _pearson_30bar(df["close"], eth_klines["close"])
    if corr < CORRELATION_THRESHOLD:
        return None

    # Fire v2 signal — wider TP because 3-asset agreement should run further.
    entry = last_close
    stop = entry * (1 - V2_SL_PCT / 100.0)
    risk = entry - stop
    tp1 = entry + risk * V2_TP1_RR
    tp2 = entry + risk * V2_TP2_RR
    rr = (tp1 - entry) / max(risk, 1e-9)

    btc_agreeing = btc_match["agreeing"]
    # Higher confidence than v1: 3-asset + corr gate.
    confidence_pct = 80.0 + (len(btc_agreeing) - MIN_CONFLUENCE) * 4.0
    confidence_pct = min(92.0, confidence_pct)
    strength = 9 + min(1, len(btc_agreeing) - MIN_CONFLUENCE)

    basis_items = (
        SetupBasis("btc_LL_prev", round(btc_match["prev_low"], 1), 0.15),
        SetupBasis("btc_LL_cur", round(btc_match["cur_low"], 1), 0.15),
        SetupBasis("btc_confluence", len(btc_agreeing), 0.15),
        SetupBasis("eth_companion_div", "yes", 0.20),
        SetupBasis("xrp_companion_div", "yes", 0.20),
        SetupBasis("btc_eth_corr_30h", round(corr, 3), 0.15),
        SetupBasis("agreeing_indicators_btc", "+".join(btc_agreeing), 0.0),
    )

    return make_setup(
        setup_type=SetupType.LONG_MULTI_ASSET_CONFLUENCE_V2,
        pair=ctx.pair,
        current_price=last_close,
        regime_label=ctx.regime_label,
        session_label=ctx.session_label,
        entry_price=entry,
        stop_price=stop,
        tp1_price=tp1,
        tp2_price=tp2,
        risk_reward=round(rr, 2),
        strength=strength,
        confidence_pct=round(confidence_pct, 1),
        basis=basis_items,
        cancel_conditions=(
            "BTC closes below LL_cur — wave invalidated",
            "BTC↔ETH correlation drops below 0.5 — regime de-sync",
            "Any of (ETH, XRP) prints fresh LL with no bull DIV — companion fails",
        ),
        window_minutes=240,
        portfolio_impact_note=(
            f"3-asset bull DIV confluence (BTC+ETH+XRP) "
            f"with BTC↔ETH corr={corr:.2f}. Higher conviction than v1; "
            f"fires alongside v1 — A/B in walk-forward."
        ),
        recommended_size_btc=0.05,
    )
