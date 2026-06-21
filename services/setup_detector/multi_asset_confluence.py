"""Cross-asset divergence confluence detector — TZ-3 of large batch.

Backtest 2026-05-08 (BTCUSDT vs ETHUSDT 1h 2y) showed:
  - Standalone BTC bull DIV conf>=2:    PF=1.78 hold_1h, N=147
  - BTC + ETH (within +/-4h):           PF=3.88 hold_1h, WR=68%, N=41

Confluence DOUBLES the PF on hold_1h while keeping 28% of signals. This
detector reproduces that filter live: when BTC has bull DIV with confluence
>=2 AND ETH has any bull DIV (conf>=2) within +/-4 hours -> fire setup.

LONG side only — short cross-asset confluence not tested.
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
    _agreeing_indicators_for_bearish,
    _agreeing_indicators_for_bullish,
    _build_indicators,
    _find_pivots,
    _is_double_trend_down,
)

logger = logging.getLogger(__name__)

CROSS_ASSET_WINDOW_HOURS = 4
CROSS_ASSET_SL_PCT = 1.0
CROSS_ASSET_TP1_RR = 2.0
CROSS_ASSET_TP2_RR = 4.0


def _detect_bullish_div_bars(df: pd.DataFrame) -> list[int]:
    """Return confirmation-bar indices of bullish divs (conf>=2) in df.

    Helper for companion-symbol scan. Returns only the bar where each div
    becomes confirmed (cur_pivot + PIVOT_LOOKBACK) — no SetupBasis.
    """
    if df is None or len(df) < 50:
        return []
    indicators = _build_indicators(df)
    pivots_by_indicator = {name: _find_pivots(ind) for name, ind in indicators.items()}
    price_pivots = _find_pivots(df["low"]).lows

    out: list[int] = []
    for i in range(1, len(price_pivots)):
        cur_idx = price_pivots[i]
        prev_idx = price_pivots[i - 1]
        if cur_idx - prev_idx > DIV_WINDOW_BARS:
            continue
        if df["low"].iloc[cur_idx] >= df["low"].iloc[prev_idx]:
            continue
        agreeing = _agreeing_indicators_for_bullish(
            indicators, pivots_by_indicator,
            prev_idx, cur_idx, INDICATOR_PIVOT_TOLERANCE,
        )
        if len(agreeing) < MIN_CONFLUENCE:
            continue
        conf_idx = cur_idx + PIVOT_LOOKBACK
        if conf_idx >= len(df):
            continue
        out.append(conf_idx)
    return out


def _load_companion_klines(symbol: str, limit: int = 200):
    """Best-effort companion-symbol fetch via core.data_loader."""
    try:
        from core.data_loader import load_klines
        return load_klines(symbol=symbol, timeframe="1h", limit=limit)
    except Exception:
        logger.exception("multi_asset_confluence.companion_load_failed symbol=%s", symbol)
        return None


def detect_long_multi_asset_confluence(ctx) -> Setup | None:
    """BTC bullish DIV + ETH companion bullish DIV within +/-4h."""
    df = ctx.ohlcv_1h
    if df is None or len(df) < 50:
        return None
    if not all(col in df.columns for col in ("high", "low", "close", "volume")):
        return None
    # Operate on BTC only — companion is ETH.
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

    # Find a BTC bullish divergence whose confirmation lands on last_bar
    # (fire only on fresh BoS; old confirmations skipped).
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
            return None  # any later pair would not be the latest, so stop
        agreeing = _agreeing_indicators_for_bullish(
            indicators, pivots_by_indicator,
            prev_idx, cur_idx, INDICATOR_PIVOT_TOLERANCE,
        )
        if len(agreeing) < MIN_CONFLUENCE:
            continue
        btc_match = {
            "prev_low": prev_low,
            "cur_low": cur_low,
            "agreeing": agreeing,
        }
        break

    if btc_match is None:
        return None

    # Get BTC signal timestamp.
    if "ts" in df.columns:
        btc_ts_ms = int(df["ts"].iloc[last_bar])
    elif "open_time" in df.columns:
        btc_ts_ms = int(df["open_time"].iloc[last_bar].timestamp() * 1000)
    else:
        return None

    # Companion: load ETH 1h klines and look for any bullish div within +/-4h.
    eth_df = _load_companion_klines("ETHUSDT", limit=200)
    if eth_df is None or len(eth_df) < 50:
        return None

    # Normalize: production load_klines returns 'open_time'; backtest CSV uses 'ts'.
    eth_klines = eth_df.copy().reset_index(drop=True)
    if "ts" not in eth_klines.columns and "open_time" in eth_klines.columns:
        eth_klines["ts"] = (eth_klines["open_time"].astype("int64") // 10**6).astype("int64")

    eth_div_bars = _detect_bullish_div_bars(eth_klines)
    if not eth_div_bars:
        return None

    has_companion = False
    for eth_bar in eth_div_bars:
        eth_ts_ms = int(eth_klines["ts"].iloc[eth_bar])
        delta_h = abs(eth_ts_ms - btc_ts_ms) / (60 * 60 * 1000)
        if delta_h <= CROSS_ASSET_WINDOW_HOURS:
            has_companion = True
            break
    if not has_companion:
        return None

    # Fire signal.
    entry = last_close
    stop = entry * (1 - CROSS_ASSET_SL_PCT / 100.0)
    risk = entry - stop
    tp1 = entry + risk * CROSS_ASSET_TP1_RR
    tp2 = entry + risk * CROSS_ASSET_TP2_RR
    rr = (tp1 - entry) / max(risk, 1e-9)

    btc_agreeing = btc_match["agreeing"]
    confidence_pct = 75.0 + (len(btc_agreeing) - MIN_CONFLUENCE) * 5.0
    confidence_pct = min(85.0, confidence_pct)
    strength = 8 + min(2, len(btc_agreeing) - MIN_CONFLUENCE + 1)

    basis_items = [
        SetupBasis("btc_LL_prev", round(btc_match["prev_low"], 1), 0.20),
        SetupBasis("btc_LL_cur", round(btc_match["cur_low"], 1), 0.20),
        SetupBasis("btc_confluence", len(btc_agreeing), 0.20),
        SetupBasis("eth_companion_div", "yes", 0.30),
        SetupBasis("agreeing_indicators_btc", "+".join(btc_agreeing), 0.10),
    ]

    return make_setup(
        setup_type=SetupType.LONG_MULTI_ASSET_CONFLUENCE,
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
        confidence_pct=confidence_pct,
        basis=tuple(basis_items),
        cancel_conditions=(
            f"close below {stop:.0f} invalidates BTC+ETH confluence",
            "regime turns trend_down on 1h",
        ),
        window_minutes=240,
        portfolio_impact_note=(
            f"BTC+ETH BULL DIV CONFLUENCE: BTC LL "
            f"{btc_match['prev_low']:.0f} -> {btc_match['cur_low']:.0f} "
            f"({len(btc_agreeing)}/7 inds), ETH companion within +/-4h. "
            f"Backtest PF=3.88 hold_1h, WR=68%, N=41 (vs BTC alone 1.78)."
        ),
    )
