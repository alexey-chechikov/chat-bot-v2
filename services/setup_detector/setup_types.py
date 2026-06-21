from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from .constants import (
    GRID_BOUNDARY_PREMIUM, GRID_BOUNDARY_TRIGGER,
    LONG_ENTRY_NEAR_LEVEL, LONG_ENTRY_PREMIUM,
    LONG_RECLAIM_MIN, LONG_REJECTION_TOLERANCE,
    LONG_STOP_BUFFER_BELOW, LONG_STOP_BUFFER_DEEP, LONG_STOP_FROM_LIQ,
    RSI_MOMENTUM_HIGH, RSI_NEUTRAL_HIGH, RSI_NEUTRAL_LOW,
    RSI_OVERBOUGHT, RSI_OVERBOUGHT_STRICT,
    RSI_OVERSOLD, RSI_OVERSOLD_STRICT,
    SHORT_ENTRY_NEAR_LEVEL, SHORT_ENTRY_PREMIUM,
    SHORT_REJECT_MIN, SHORT_REJECTION_TOLERANCE,
    SHORT_STOP_BUFFER_ABOVE, SHORT_STOP_BUFFER_DEEP, SHORT_STOP_FROM_LIQ,
    SLOPE_6H_MIN_FOR_SHORT, SWING_HIGH_BUFFER, SWING_LOW_BUFFER,
)
from .indicators import (
    compute_rsi,
    compute_volume_ratio,
    count_touches_at_level,
    detect_swing_highs,
    detect_swing_lows,
    find_pdh_pdl,
    reversal_wick_count,
)
from .models import Setup, SetupBasis, SetupType, make_setup
from .scorer import compute_confidence, compute_strength


@dataclass
class PortfolioSnapshot:
    free_margin_pct: float = 100.0
    net_btc: float = 0.0
    available_usd: float = 1000.0
    liq_above_price: float | None = None
    liq_below_price: float | None = None


@dataclass
class DetectionContext:
    pair: str
    current_price: float
    regime_label: str
    session_label: str
    ohlcv_1m: pd.DataFrame
    ohlcv_1h: pd.DataFrame
    portfolio: PortfolioSnapshot = field(default_factory=PortfolioSnapshot)
    # ICT level features at this bar (from ict_levels parquet). Empty if unavailable.
    ict_context: dict = field(default_factory=dict)
    # 15m frame for fast-reaction detectors (e.g. LONG_DIV_BOS_15M).
    # Empty DataFrame when the loop hasn't loaded it yet — detectors must guard.
    ohlcv_15m: pd.DataFrame = field(default_factory=pd.DataFrame)


DetectorFn = Callable[[DetectionContext], Setup | None]

_RANGE_OR_DOWN = {"range_tight", "range_wide", "consolidation", "trend_down", "impulse_down"}
_RANGE_OR_UP = {"range_tight", "range_wide", "consolidation", "trend_up", "impulse_up"}
_RANGE_ONLY = {"range_tight", "range_wide", "consolidation"}


def _long_trade(
    ctx: DetectionContext,
    *,
    setup_type: SetupType,
    basis: tuple[SetupBasis, ...],
    entry: float,
    stop: float,
    window_minutes: int,
    note: str,
) -> Setup | None:
    strength = compute_strength(basis)
    if strength < 6:
        return None
    confidence = compute_confidence(setup_type, basis, ctx.regime_label, ctx.session_label)
    risk = max(entry - stop, entry * 0.001)
    tp1 = entry + risk * 1.5
    tp2 = entry + risk * 2.5
    rr = (tp1 - entry) / max(entry - stop, 1e-9)
    return make_setup(
        setup_type=setup_type,
        pair=ctx.pair,
        current_price=ctx.current_price,
        regime_label=ctx.regime_label,
        session_label=ctx.session_label,
        entry_price=entry,
        stop_price=stop,
        tp1_price=tp1,
        tp2_price=tp2,
        risk_reward=round(rr, 2),
        strength=strength,
        confidence_pct=round(confidence, 1),
        basis=basis,
        cancel_conditions=(
            "Сигнал инвалидации на 1ч закрытии против входа",
            "Импульс восстановления погас",
            "Новый локальный минимум ниже стопа",
        ),
        window_minutes=window_minutes,
        portfolio_impact_note=note,
        recommended_size_btc=0.05,
    )


def _short_trade(
    ctx: DetectionContext,
    *,
    setup_type: SetupType,
    basis: tuple[SetupBasis, ...],
    entry: float,
    stop: float,
    window_minutes: int,
    note: str,
) -> Setup | None:
    strength = compute_strength(basis)
    if strength < 6:
        return None
    confidence = compute_confidence(setup_type, basis, ctx.regime_label, ctx.session_label)
    risk = max(stop - entry, entry * 0.001)
    tp1 = entry - risk * 1.5
    tp2 = entry - risk * 2.5
    rr = (entry - tp1) / max(stop - entry, 1e-9)
    return make_setup(
        setup_type=setup_type,
        pair=ctx.pair,
        current_price=ctx.current_price,
        regime_label=ctx.regime_label,
        session_label=ctx.session_label,
        entry_price=entry,
        stop_price=stop,
        tp1_price=tp1,
        tp2_price=tp2,
        risk_reward=round(rr, 2),
        strength=strength,
        confidence_pct=round(confidence, 1),
        basis=basis,
        cancel_conditions=(
            "Сигнал инвалидации на 1ч закрытии против входа",
            "Momentum loss снялся",
            "Новый локальный максимум выше стопа",
        ),
        window_minutes=window_minutes,
        portfolio_impact_note=note,
        recommended_size_btc=0.05,
    )


def _grid_setup(
    ctx: DetectionContext,
    *,
    setup_type: SetupType,
    basis: tuple[SetupBasis, ...],
    action: str,
    target_bots: tuple[str, ...],
    param_change: dict[str, object] | None,
    window_minutes: int,
    note: str,
    entry_price: float | None = None,
    stop_price: float | None = None,
    tp1_price: float | None = None,
    tp2_price: float | None = None,
    risk_reward: float | None = None,
) -> Setup | None:
    strength = compute_strength(basis)
    if strength < 6:
        return None
    confidence = compute_confidence(setup_type, basis, ctx.regime_label, ctx.session_label)
    return make_setup(
        setup_type=setup_type,
        pair=ctx.pair,
        current_price=ctx.current_price,
        regime_label=ctx.regime_label,
        session_label=ctx.session_label,
        entry_price=entry_price,
        stop_price=stop_price,
        tp1_price=tp1_price,
        tp2_price=tp2_price,
        risk_reward=risk_reward,
        grid_action=action,
        grid_target_bots=target_bots,
        grid_param_change=param_change,
        strength=strength,
        confidence_pct=round(confidence, 1),
        basis=basis,
        cancel_conditions=(
            "Рынок вернулся в range",
            "Снялось давление по шортам",
        ),
        window_minutes=window_minutes,
        portfolio_impact_note=note,
        recommended_size_btc=0.0,
    )


def _price_change_pct(current: float, previous: float) -> float:
    return (current - previous) / max(previous, 1.0) * 100.0


def _last_volume_ratio(df1m: pd.DataFrame, lookback: int = 30) -> float:
    return compute_volume_ratio(df1m["volume"], lookback=lookback)


def _range_tightening(df1m: pd.DataFrame) -> bool:
    if len(df1m) < 60:
        return False
    last = (df1m["high"].iloc[-30:] - df1m["low"].iloc[-30:]).mean()
    prev = (df1m["high"].iloc[-60:-30] - df1m["low"].iloc[-60:-30]).mean()
    return float(last) < float(prev) * 0.85


def _volume_increasing(df1m: pd.DataFrame, bars: int = 3) -> bool:
    if len(df1m) < bars:
        return False
    volumes = df1m["volume"].iloc[-bars:]
    return bool(volumes.is_monotonic_increasing and float(volumes.iloc[-1]) > float(volumes.iloc[0]))


def _higher_close_reclaim(df1m: pd.DataFrame) -> bool:
    if len(df1m) < 4:
        return False
    last3 = df1m.iloc[-3:]
    prev = df1m.iloc[-4:-1]
    return (
        float(last3["close"].iloc[-1]) > float(last3["high"].iloc[-2])
        and bool(last3["close"].is_monotonic_increasing)
        and float(last3["close"].iloc[-1]) > float(prev["high"].max())
    )


def _lower_close_fade(df1m: pd.DataFrame) -> bool:
    if len(df1m) < 3:
        return False
    closes = df1m["close"].iloc[-3:]
    return bool(closes.is_monotonic_decreasing)


def _recent_swing_low(df1m: pd.DataFrame) -> float:
    swings = detect_swing_lows(df1m["low"], window=3, max_count=1)
    return swings[-1][1] if swings else float(df1m["low"].iloc[-20:].min())


def _recent_swing_high(df1m: pd.DataFrame) -> float:
    swings = detect_swing_highs(df1m["high"], window=3, max_count=1)
    return swings[-1][1] if swings else float(df1m["high"].iloc[-20:].max())


def _hold_above_level(df1m: pd.DataFrame, level: float, bars: int) -> bool:
    if len(df1m) < bars or level <= 0.0:
        return False
    return bool((df1m["close"].iloc[-bars:] > level).all())


def _continuous_trend_up(df1h: pd.DataFrame, bars: int = 4) -> bool:
    if len(df1h) < bars:
        return False
    closes = df1h["close"].iloc[-bars:]
    return bool(closes.is_monotonic_increasing)


def _continuous_trend_down(df1h: pd.DataFrame, bars: int = 4) -> bool:
    if len(df1h) < bars:
        return False
    closes = df1h["close"].iloc[-bars:]
    return bool(closes.is_monotonic_decreasing)


def detect_long_dump_reversal(ctx: DetectionContext) -> Setup | None:
    # 2026-05-11 note: pipeline_analyzer shows 1180 fires / 2 emits (0.2% yield)
    # over 24h. ~99% of fires die at combo_filter strength<9 gate.
    # Tightening the cond count threshold here (3→4) would reduce noise but
    # also risks the documented edge (PF 0.70 on full backtest). Leave as
    # is — fires are cheap (compute_strength + combo check, ~ms each).
    df1h = ctx.ohlcv_1h
    df1m = ctx.ohlcv_1m
    if len(df1h) < 6 or len(df1m) < 30:
        return None

    price_4h_ago = float(df1h["close"].iloc[-5])
    price_change_4h = _price_change_pct(ctx.current_price, price_4h_ago)
    cond_dump = price_change_4h <= -2.0
    rsi_1h = compute_rsi(df1h["close"], period=14)
    cond_rsi = rsi_1h < RSI_OVERSOLD
    wick_cnt = reversal_wick_count(
        df1m["open"].iloc[-10:],
        df1m["high"].iloc[-10:],
        df1m["low"].iloc[-10:],
        df1m["close"].iloc[-10:],
        direction="long",
    )
    cond_wicks = wick_cnt >= 3
    vol_ratio = _last_volume_ratio(df1m, lookback=30)
    cond_volume = vol_ratio >= 1.3
    lookback_h = min(24, len(df1h))
    _, pdl = find_pdh_pdl(df1h.iloc[-lookback_h:])
    near_pdl = pdl > 0.0 and abs(ctx.current_price - pdl) / pdl * 100.0 <= 0.6
    pdl_tests = count_touches_at_level(df1m["low"], pdl, tolerance_pct=0.15) if pdl > 0.0 else 0
    cond_pdl = near_pdl
    if sum([cond_dump, cond_rsi, cond_wicks, cond_volume, cond_pdl]) < 3:
        return None

    basis_items: list[SetupBasis] = []
    if cond_dump:
        basis_items.append(SetupBasis(f"Дамп {price_change_4h:.1f}% за 4ч", price_change_4h, 1.0))
    if cond_rsi:
        basis_items.append(SetupBasis(f"RSI 1h = {rsi_1h:.0f}", rsi_1h, 1.0))
    if cond_wicks:
        basis_items.append(SetupBasis(f"Разворотные свечи {wick_cnt}/10", wick_cnt, 0.8))
    if cond_volume:
        basis_items.append(SetupBasis(f"Объём x{vol_ratio:.1f}", vol_ratio, 0.9))
    if cond_pdl and pdl > 0.0:
        basis_items.append(SetupBasis(f"PDL ${pdl:,.0f} ({pdl_tests} тест)", pdl, 0.9))

    entry = ctx.current_price * LONG_ENTRY_PREMIUM
    stop = min(_recent_swing_low(df1m) * LONG_STOP_BUFFER_BELOW,
               entry * LONG_STOP_BUFFER_DEEP)
    return _long_trade(
        ctx,
        setup_type=SetupType.LONG_DUMP_REVERSAL,
        basis=tuple(basis_items),
        entry=entry,
        stop=stop,
        window_minutes=120,
        note="P-7: добавляет к лонгам после dump reversal",
    )


def detect_long_pdl_bounce(ctx: DetectionContext) -> Setup | None:
    df1h = ctx.ohlcv_1h
    df1m = ctx.ohlcv_1m
    if len(df1h) < 16 or len(df1m) < 30:
        return None
    if ctx.regime_label not in _RANGE_OR_DOWN:
        return None

    _, pdl = find_pdh_pdl(df1h.iloc[-24:])
    if pdl <= 0.0:
        return None
    last_bar = df1m.iloc[-1]
    touch_count = count_touches_at_level(df1m["low"].iloc[-30:], pdl, tolerance_pct=0.3)
    cond_touch = touch_count >= 1
    cond_reject = (float(last_bar["low"]) <= pdl * LONG_REJECTION_TOLERANCE
                    and float(last_bar["close"]) > pdl)
    rsi_1h = compute_rsi(df1h["close"])
    cond_rsi = rsi_1h < RSI_NEUTRAL_LOW
    vol_ratio = _last_volume_ratio(df1m, lookback=20)
    cond_volume = vol_ratio >= 1.3
    if not all([cond_touch, cond_reject, cond_rsi, cond_volume]):
        return None

    basis = (
        SetupBasis(f"PDL ${pdl:,.0f} ({touch_count} тест)", pdl, 1.0),
        SetupBasis("Отбой закрытием выше PDL", float(last_bar["close"]), 1.0),
        SetupBasis(f"RSI 1h = {rsi_1h:.0f}", rsi_1h, 0.9),
        SetupBasis(f"Объём x{vol_ratio:.1f}", vol_ratio, 0.8),
    )
    entry = ctx.current_price * LONG_ENTRY_NEAR_LEVEL
    stop = pdl * LONG_STOP_BUFFER_BELOW
    return _long_trade(
        ctx,
        setup_type=SetupType.LONG_PDL_BOUNCE,
        basis=basis,
        entry=entry,
        stop=stop,
        window_minutes=240,
        note="P-7 stack-long на PDL bounce",
    )


def detect_long_oversold_reclaim(ctx: DetectionContext) -> Setup | None:
    df1h = ctx.ohlcv_1h
    df1m = ctx.ohlcv_1m
    if len(df1h) < 16 or len(df1m) < 10:
        return None
    rsi_1h = compute_rsi(df1h["close"])
    cond_rsi = rsi_1h < RSI_OVERSOLD_STRICT
    cond_reclaim = _higher_close_reclaim(df1m)
    cond_volume = _volume_increasing(df1m, bars=3)
    if not all([cond_rsi, cond_reclaim, cond_volume]):
        return None

    recent_low = _recent_swing_low(df1m)
    basis = (
        SetupBasis(f"RSI 1h = {rsi_1h:.0f}", rsi_1h, 1.0),
        SetupBasis("3 бара reclaim выше high", ctx.current_price, 1.0),
        SetupBasis("Объём растёт в reclaim", float(df1m["volume"].iloc[-1]), 0.8),
    )
    return _long_trade(
        ctx,
        setup_type=SetupType.LONG_OVERSOLD_RECLAIM,
        basis=basis,
        entry=ctx.current_price,
        stop=recent_low * SWING_LOW_BUFFER,
        window_minutes=180,
        note="Long reclaim после extreme oversold",
    )


def detect_long_liq_magnet(ctx: DetectionContext) -> Setup | None:
    df1m = ctx.ohlcv_1m
    liq = ctx.portfolio.liq_below_price
    if len(df1m) < 30 or liq is None or liq <= 0.0:
        return None
    if ctx.regime_label in {"trend_down", "impulse_down"}:
        return None
    recent_low = float(df1m["low"].iloc[-30:].min())
    cond_cluster = abs(recent_low - liq) / liq * 100.0 <= 0.5
    cond_reclaim = ctx.current_price > liq * LONG_RECLAIM_MIN
    vol_ratio = _last_volume_ratio(df1m, lookback=20)
    cond_volume = vol_ratio >= 1.5
    if not all([cond_cluster, cond_reclaim, cond_volume]):
        return None

    basis = (
        SetupBasis(f"Liq cluster ${liq:,.0f}", liq, 1.0),
        SetupBasis("Цена отошла выше кластера >0.3%", ctx.current_price, 0.9),
        SetupBasis(f"Объём x{vol_ratio:.1f}", vol_ratio, 0.8),
    )
    return _long_trade(
        ctx,
        setup_type=SetupType.LONG_LIQ_MAGNET,
        basis=basis,
        entry=ctx.current_price * LONG_ENTRY_NEAR_LEVEL,
        stop=liq * LONG_STOP_FROM_LIQ,
        window_minutes=180,
        note="Long после похода в нижний liq cluster",
    )


def detect_short_rally_fade(ctx: DetectionContext) -> Setup | None:
    df1h = ctx.ohlcv_1h
    df1m = ctx.ohlcv_1m
    if len(df1h) < 6 or len(df1m) < 30:
        return None

    # 2026-05-10 SETUP_FILTER_RESEARCH (commit 1434a44): на 365д baseline PF был
    # 0.54 (-114% PnL). После добавления фильтра RSI_15m>=75.6 + trend_slope_6h>=1.6%
    # PF стал 1.39. Без этого hard-gate детектор выпускает ~3x ложных сигналов.
    df15m = ctx.ohlcv_15m
    if df15m is None or len(df15m) < 20:
        return None
    rsi_15m = compute_rsi(df15m["close"], period=14)
    if rsi_15m < 75.0:
        return None  # rally not extreme enough — skip
    if len(df1h) >= 7:
        slope_6h = _price_change_pct(ctx.current_price, float(df1h["close"].iloc[-7]))
        if slope_6h < 1.5:
            return None  # uptrend not strong enough — skip

    price_4h_ago = float(df1h["close"].iloc[-5])
    price_change_4h = _price_change_pct(ctx.current_price, price_4h_ago)
    cond_rally = price_change_4h >= 2.0
    rsi_1h = compute_rsi(df1h["close"], period=14)
    cond_rsi = rsi_1h > RSI_MOMENTUM_HIGH
    wick_cnt = reversal_wick_count(
        df1m["open"].iloc[-10:],
        df1m["high"].iloc[-10:],
        df1m["low"].iloc[-10:],
        df1m["close"].iloc[-10:],
        direction="short",
    )
    cond_wicks = wick_cnt >= 3
    vol_ratio = _last_volume_ratio(df1m, lookback=30)
    cond_volume = vol_ratio >= 1.3
    lookback_h = min(24, len(df1h))
    pdh, _ = find_pdh_pdl(df1h.iloc[-lookback_h:])
    near_pdh = pdh > 0.0 and abs(ctx.current_price - pdh) / pdh * 100.0 <= 0.6
    pdh_tests = count_touches_at_level(df1m["high"], pdh, tolerance_pct=0.15) if pdh > 0.0 else 0
    cond_pdh = near_pdh
    if sum([cond_rally, cond_rsi, cond_wicks, cond_volume, cond_pdh]) < 3:
        return None

    basis_items: list[SetupBasis] = []
    if cond_rally:
        basis_items.append(SetupBasis(f"Ралли +{price_change_4h:.1f}% за 4ч", price_change_4h, 1.0))
    if cond_rsi:
        basis_items.append(SetupBasis(f"RSI 1h = {rsi_1h:.0f}", rsi_1h, 1.0))
    if cond_wicks:
        basis_items.append(SetupBasis(f"Отбойные свечи {wick_cnt}/10", wick_cnt, 0.8))
    if cond_volume:
        basis_items.append(SetupBasis(f"Объём x{vol_ratio:.1f}", vol_ratio, 0.9))
    if cond_pdh and pdh > 0.0:
        basis_items.append(SetupBasis(f"PDH ${pdh:,.0f} ({pdh_tests} тест)", pdh, 0.9))

    entry = ctx.current_price * SHORT_ENTRY_PREMIUM
    stop = max(_recent_swing_high(df1m) * SHORT_STOP_BUFFER_ABOVE,
               entry * SHORT_STOP_BUFFER_DEEP)
    return _short_trade(
        ctx,
        setup_type=SetupType.SHORT_RALLY_FADE,
        basis=tuple(basis_items),
        entry=entry,
        stop=stop,
        window_minutes=120,
        note="P-2/P-6 fade после rally",
    )


def detect_short_pdh_rejection(ctx: DetectionContext) -> Setup | None:
    df1h = ctx.ohlcv_1h
    df1m = ctx.ohlcv_1m
    if len(df1h) < 16 or len(df1m) < 30:
        return None
    if ctx.regime_label not in _RANGE_OR_UP:
        return None

    # 2026-05-10 SETUP_FILTER_RESEARCH: 2y honest baseline PF 0.58 (-45% PnL).
    # Filter+Conf (RSI_1h>=72, MFI_1h>=72, trend_slope_6h>=1.0%) → PF 1.35,
    # WF 3/4 folds positive. Hard-gate the strict overbought condition.
    rsi_1h = compute_rsi(df1h["close"])
    if rsi_1h < RSI_OVERBOUGHT_STRICT:
        return None
    if len(df1h) >= 7:
        slope_6h = _price_change_pct(ctx.current_price, float(df1h["close"].iloc[-7]))
        if slope_6h < SLOPE_6H_MIN_FOR_SHORT:
            return None

    pdh, _ = find_pdh_pdl(df1h.iloc[-24:])
    if pdh <= 0.0:
        return None
    last_bar = df1m.iloc[-1]
    touch_count = count_touches_at_level(df1m["high"].iloc[-30:], pdh, tolerance_pct=0.3)
    cond_touch = touch_count >= 1
    cond_reject = (float(last_bar["high"]) >= pdh * SHORT_REJECTION_TOLERANCE
                    and float(last_bar["close"]) < pdh)
    cond_rsi = rsi_1h > RSI_NEUTRAL_HIGH  # already gated >72 above, kept for basis logic
    vol_ratio = _last_volume_ratio(df1m, lookback=20)
    cond_volume = vol_ratio >= 1.3
    if not all([cond_touch, cond_reject, cond_rsi, cond_volume]):
        return None

    basis = (
        SetupBasis(f"PDH ${pdh:,.0f} ({touch_count} тест)", pdh, 1.0),
        SetupBasis("Отбой закрытием ниже PDH", float(last_bar["close"]), 1.0),
        SetupBasis(f"RSI 1h = {rsi_1h:.0f}", rsi_1h, 0.9),
        SetupBasis(f"Объём x{vol_ratio:.1f}", vol_ratio, 0.8),
    )
    entry = ctx.current_price * SHORT_ENTRY_NEAR_LEVEL
    stop = pdh * SHORT_STOP_BUFFER_ABOVE
    return _short_trade(
        ctx,
        setup_type=SetupType.SHORT_PDH_REJECTION,
        basis=basis,
        entry=entry,
        stop=stop,
        window_minutes=240,
        note="Short rejection от Previous Day High",
    )


def detect_short_overbought_fade(ctx: DetectionContext) -> Setup | None:
    df1h = ctx.ohlcv_1h
    df1m = ctx.ohlcv_1m
    if len(df1h) < 16 or len(df1m) < 10:
        return None
    rsi_1h = compute_rsi(df1h["close"])
    cond_rsi = rsi_1h > RSI_OVERBOUGHT
    cond_momentum_loss = _lower_close_fade(df1m)
    cond_volume = _volume_increasing(df1m, bars=3)
    if not all([cond_rsi, cond_momentum_loss, cond_volume]):
        return None

    recent_high = _recent_swing_high(df1m)
    basis = (
        SetupBasis(f"RSI 1h = {rsi_1h:.0f}", rsi_1h, 1.0),
        SetupBasis("3 lower closes подряд", float(df1m["close"].iloc[-1]), 1.0),
        SetupBasis("Объём elevated на fade", float(df1m["volume"].iloc[-1]), 0.8),
    )
    return _short_trade(
        ctx,
        setup_type=SetupType.SHORT_OVERBOUGHT_FADE,
        basis=basis,
        entry=ctx.current_price,
        stop=recent_high * SWING_HIGH_BUFFER,
        window_minutes=180,
        note="Short fade после overbought momentum loss",
    )


def detect_short_liq_magnet(ctx: DetectionContext) -> Setup | None:
    df1m = ctx.ohlcv_1m
    liq = ctx.portfolio.liq_above_price
    if len(df1m) < 30 or liq is None or liq <= 0.0:
        return None
    if ctx.regime_label in {"trend_up", "impulse_up"}:
        return None
    recent_high = float(df1m["high"].iloc[-30:].max())
    cond_cluster = abs(recent_high - liq) / liq * 100.0 <= 0.5
    cond_reject = ctx.current_price < liq * SHORT_REJECT_MIN
    vol_ratio = _last_volume_ratio(df1m, lookback=20)
    cond_volume = vol_ratio >= 1.5
    if not all([cond_cluster, cond_reject, cond_volume]):
        return None

    basis = (
        SetupBasis(f"Liq cluster ${liq:,.0f}", liq, 1.0),
        SetupBasis("Цена ушла ниже кластера >0.3%", ctx.current_price, 0.9),
        SetupBasis(f"Объём x{vol_ratio:.1f}", vol_ratio, 0.8),
    )
    return _short_trade(
        ctx,
        setup_type=SetupType.SHORT_LIQ_MAGNET,
        basis=basis,
        entry=ctx.current_price * SHORT_ENTRY_NEAR_LEVEL,
        stop=liq * SHORT_STOP_FROM_LIQ,
        window_minutes=180,
        note="Short после похода в верхний liq cluster",
    )


def detect_grid_raise_boundary(ctx: DetectionContext) -> Setup | None:
    df1h = ctx.ohlcv_1h
    df1m = ctx.ohlcv_1m
    if len(df1h) < 5 or len(df1m) < 15:
        return None
    if ctx.portfolio.net_btc >= 0:
        return None

    reference = float(df1h["high"].iloc[-5:-1].max())
    hold = _hold_above_level(df1m, reference, bars=15)
    delta_4h = _price_change_pct(ctx.current_price, float(df1h["close"].iloc[-5]))
    continuation = min(1.0, max(0.0, delta_4h / 1.5))
    shorts_in_stress = ctx.portfolio.free_margin_pct < 45.0
    if not (ctx.current_price > reference * GRID_BOUNDARY_TRIGGER
             and hold and continuation > 0.7 and shorts_in_stress):
        return None

    new_boundary = round(reference * GRID_BOUNDARY_PREMIUM, 1)
    basis = (
        SetupBasis(f"Пробой ref ${reference:,.0f}", reference, 1.0),
        SetupBasis("Hold выше 15м", 15, 1.0),
        SetupBasis(f"Continuation {continuation:.2f}", continuation, 0.9),
        SetupBasis(f"Свободная маржа {ctx.portfolio.free_margin_pct:.1f}%", ctx.portfolio.free_margin_pct, 0.8),
    )
    return _grid_setup(
        ctx,
        setup_type=SetupType.GRID_RAISE_BOUNDARY,
        basis=basis,
        action="raise_boundary +0.3%",
        target_bots=("shorts",),
        param_change={"border.top": new_boundary},
        window_minutes=60,
        note="P-1 защита шортов",
    )


def detect_grid_pause_entries(ctx: DetectionContext) -> Setup | None:
    df1h = ctx.ohlcv_1h
    df1m = ctx.ohlcv_1m
    if len(df1h) < 4 or len(df1m) < 60:
        return None
    if ctx.portfolio.net_btc >= 0:
        return None

    trend_up = _continuous_trend_up(df1h, bars=4)
    delta_3h = _price_change_pct(ctx.current_price, float(df1h["close"].iloc[-4]))
    low_pullback = float((df1m["high"].iloc[-60:] - df1m["low"].iloc[-60:]).max() / max(ctx.current_price, 1.0) * 100.0)
    cond_consolidation = _range_tightening(df1m)
    shorts_in_stress = ctx.portfolio.free_margin_pct < 50.0
    if not (trend_up and delta_3h >= 0.7 and low_pullback < 0.8 and cond_consolidation and shorts_in_stress):
        return None

    basis = (
        SetupBasis(f"Trend up {delta_3h:.1f}% за 3ч", delta_3h, 1.0),
        SetupBasis("Без отката 3+ часа", 3, 1.0),
        SetupBasis("Волатильность сжимается", 1, 0.9),
        SetupBasis(f"Свободная маржа {ctx.portfolio.free_margin_pct:.1f}%", ctx.portfolio.free_margin_pct, 0.8),
    )
    return _grid_setup(
        ctx,
        setup_type=SetupType.GRID_PAUSE_ENTRIES,
        basis=basis,
        action="pause_entries",
        target_bots=("shorts",),
        param_change=None,
        window_minutes=120,
        note="P-4 stop новых short entries",
    )


def detect_grid_booster_activate(ctx: DetectionContext) -> Setup | None:
    if ctx.regime_label not in _RANGE_ONLY:
        return None
    df1h = ctx.ohlcv_1h
    if len(df1h) < 16:
        return None
    rsi_1h = compute_rsi(df1h["close"], period=14)
    if rsi_1h >= RSI_OVERSOLD:
        return None

    near_liq = (
        ctx.portfolio.liq_below_price is not None
        and ctx.portfolio.liq_below_price > 0.0
        and abs(ctx.current_price - ctx.portfolio.liq_below_price) / ctx.current_price * 100.0 <= 1.5
    )
    basis_items: list[SetupBasis] = [
        SetupBasis(f"RSI 1h = {rsi_1h:.0f}", rsi_1h, 1.0),
        SetupBasis(f"Режим: {ctx.regime_label}", ctx.regime_label, 0.8),
    ]
    if near_liq and ctx.portfolio.liq_below_price is not None:
        basis_items.append(
            SetupBasis(f"Ликвидность ниже ${ctx.portfolio.liq_below_price:,.0f}", ctx.portfolio.liq_below_price, 0.9)
        )
    recent_low = float(df1h["low"].iloc[-6:].min())
    entry = round(ctx.current_price, 1)
    stop = round(min(entry * 0.992, recent_low * 0.998), 1)
    risk = max(entry - stop, entry * 0.001)
    tp1 = round(entry + risk * 1.2, 1)
    tp2 = round(entry + risk * 2.0, 1)
    rr = round((tp1 - entry) / max(entry - stop, 1e-9), 2)
    return _grid_setup(
        ctx,
        setup_type=SetupType.GRID_BOOSTER_ACTIVATE,
        basis=tuple(basis_items),
        action="activate_booster",
        target_bots=("Bot 6399265299",),
        param_change=None,
        entry_price=entry,
        stop_price=stop,
        tp1_price=tp1,
        tp2_price=tp2,
        risk_reward=rr,
        window_minutes=45,
        note="P-16 активация boost-бота",
    )


def detect_grid_adaptive_tighten(ctx: DetectionContext) -> Setup | None:
    df1h = ctx.ohlcv_1h
    df1m = ctx.ohlcv_1m
    if len(df1h) < 5 or len(df1m) < 60:
        return None
    if ctx.portfolio.net_btc >= 0:
        return None

    trend_memory = _continuous_trend_up(df1h, bars=5) or _continuous_trend_down(df1h, bars=5)
    margin_stress = ctx.portfolio.free_margin_pct < 35.0
    range_tight = _range_tightening(df1m)
    vol_ratio = _last_volume_ratio(df1m, lookback=30)
    if not (trend_memory and margin_stress and range_tight and vol_ratio < 1.0):
        return None

    basis = (
        SetupBasis("Длительный directional hold", 4, 1.0),
        SetupBasis(f"Свободная маржа {ctx.portfolio.free_margin_pct:.1f}%", ctx.portfolio.free_margin_pct, 1.0),
        SetupBasis("Волатильность сжимается", 1, 0.9),
        SetupBasis(f"Объём x{vol_ratio:.1f}", vol_ratio, 0.7),
    )
    return _grid_setup(
        ctx,
        setup_type=SetupType.GRID_ADAPTIVE_TIGHTEN,
        basis=basis,
        action="tighten",
        target_bots=("shorts",),
        param_change={"target_factor": 0.85, "gs_factor": 0.85},
        window_minutes=60,
        note="P-12 tighten в просадке",
    )


def detect_defensive_margin_low(ctx: DetectionContext) -> Setup | None:
    if ctx.portfolio.free_margin_pct >= 25.0:
        return None
    margin = ctx.portfolio.free_margin_pct
    basis = (
        SetupBasis(f"Свободная маржа {margin:.1f}%", margin, 1.0),
        SetupBasis("Риск принудительной ликвидации", "", 1.0),
    )
    return make_setup(
        setup_type=SetupType.DEFENSIVE_MARGIN_LOW,
        pair=ctx.pair,
        current_price=ctx.current_price,
        regime_label=ctx.regime_label,
        session_label=ctx.session_label,
        strength=9,
        confidence_pct=95.0,
        basis=basis,
        cancel_conditions=("Маржа восстановилась выше 30%", "Позиция сокращена"),
        window_minutes=60,
        portfolio_impact_note="Защитный алерт: маржа критически низкая",
        recommended_size_btc=0.0,
    )


from services.setup_detector.double_top_bottom import (
    detect_double_top_setup,
    detect_double_bottom_setup,
    detect_double_bottom_breakout,
)
from services.setup_detector.multi_divergence import (
    detect_long_multi_divergence,
    detect_long_div_bos_confirmed,
    detect_long_div_bos_15m,
    detect_short_div_bos_15m,
)
from services.setup_detector.multi_asset_confluence import detect_long_multi_asset_confluence
from services.setup_detector.multi_asset_confluence_v2 import detect_long_multi_asset_confluence_v2
from services.setup_detector.mega_setup import detect_long_mega_dump_bounce
from services.setup_detector.rsi_momentum_ga import detect_long_rsi_momentum_ga
from services.setup_detector.mfi_multi_ga import detect_short_mfi_multi_ga
from services.setup_detector.p15_rolling import detect_p15_long, detect_p15_short
from services.setup_detector.session_breakout import detect_session_breakout
# from services.setup_detector.h10_adapter import detect_h10_liquidity_probe
# 2026-05-10: H10 disabled in registry (PF 0.51-0.64 across 4 configs on 365d).

DETECTOR_REGISTRY: tuple[DetectorFn, ...] = (
    detect_long_dump_reversal,
    detect_long_pdl_bounce,
    detect_long_oversold_reclaim,
    detect_long_liq_magnet,
    detect_short_rally_fade,
    detect_short_pdh_rejection,
    detect_short_overbought_fade,
    detect_short_liq_magnet,
    detect_double_bottom_setup,
    # detect_double_bottom_breakout — 2026-05-10: написан и протестирован, но
    # honest backtest на 365д дал PF 0.62 / 94% timeout. Цель TP1 слишком
    # далеко за 240мин окно. Не выводим в prod до trailing TP refactor.
    detect_double_top_setup,
    detect_long_multi_asset_confluence,  # 1h, PF=3.88 hold_1h, BTC+ETH (2026-05-08)
    detect_long_multi_asset_confluence_v2,  # Stage B2: 3-asset BTC+ETH+XRP + corr gate (2026-05-09)
    detect_long_mega_dump_bounce,           # Stage B5: dump_reversal+pdl_bounce confluence, +5.7pp WR (2026-05-09)
    detect_long_rsi_momentum_ga,            # Stage E1 GA-found: RSI>71 + uptrend + vol, PF=2.05 (2026-05-09)
    detect_short_mfi_multi_ga,              # Stage E1 GA-multi: MFI<71 + ETH corr + XRP lead, PF=2.78 SHORT (2026-05-09)
    detect_long_div_bos_confirmed,  # 1h, PF=4.49, walk-forward stable (2026-05-08)
    detect_long_div_bos_15m,        # 15m, PF=5.01 hold_4h, fast reaction (2026-05-08)
    detect_short_div_bos_15m,       # 15m SHORT, PF=3.85 hold_1h, walk-forward stable
    detect_long_multi_divergence,   # 1h base, PF=1.78 (2026-05-08)
    detect_p15_long,                # P-15 LONG leg, +$65k/2y validated (2026-05-09)
    detect_p15_short,               # P-15 SHORT leg, +$67k/2y validated (2026-05-09)
    detect_session_breakout,        # 2026-05-11: Session breakout, PF 1.52 all / 2.09 ny_pm->asia, 4/4 folds
    # detect_h10_liquidity_probe,   # 2026-05-10: DISABLED. 365d sweep PF 0.51-0.64
                                    # все 4 конфигурации убыточны. Original 79.3% claim
                                    # был на специфичном апреле 2026 + 0% liq weight.
                                    # Re-enable когда условия рынка изменятся (cf. H10_PARAM_SWEEP.md).
    detect_grid_raise_boundary,
    detect_grid_pause_entries,
    detect_grid_booster_activate,
    detect_grid_adaptive_tighten,
    detect_defensive_margin_low,
)
