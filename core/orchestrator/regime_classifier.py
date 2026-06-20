from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from utils.safe_io import atomic_write_json, safe_read_json

logger = logging.getLogger(__name__)

PRIMARY_RANGE = "RANGE"
PRIMARY_TREND_UP = "TREND_UP"
PRIMARY_TREND_DOWN = "TREND_DOWN"
PRIMARY_COMPRESSION = "COMPRESSION"
PRIMARY_CASCADE_DOWN = "CASCADE_DOWN"
PRIMARY_CASCADE_UP = "CASCADE_UP"

# Anti-flap: minimum dwell time before a non-cascade transition between
# RANGE↔COMPRESSION pair. Observed 2026-05-19: 4 transitions in 12h spam.
# 90min — 1.5 bars of 1h ATR buffer; cascades override (urgent).
MIN_DWELL_MIN_LOW_VOL_FLIP = 90
LOW_VOL_FLIP_PAIR = frozenset({PRIMARY_RANGE, PRIMARY_COMPRESSION})

MODIFIER_BLACKOUT = "NEWS_BLACKOUT"
MODIFIER_HUGE_DOWN_GAP = "HUGE_DOWN_GAP"
MODIFIER_TREND_UP_SUSPECTED = "TREND_UP_SUSPECTED"
MODIFIER_TREND_DOWN_SUSPECTED = "TREND_DOWN_SUSPECTED"
MODIFIER_POST_FUNDING = "POST_FUNDING_HOUR"
MODIFIER_WEEKEND_LOW_VOL = "WEEKEND_LOW_VOL"
MODIFIER_WEEKEND_GAP = "WEEKEND_GAP_DETECTED"

MODIFIER_PRIORITY = [
    MODIFIER_BLACKOUT,
    MODIFIER_HUGE_DOWN_GAP,
    MODIFIER_TREND_UP_SUSPECTED,
    MODIFIER_TREND_DOWN_SUSPECTED,
    MODIFIER_POST_FUNDING,
    MODIFIER_WEEKEND_LOW_VOL,
    MODIFIER_WEEKEND_GAP,
]


@dataclass
class RegimeMetrics:
    """Computed market metrics used by the classifier."""

    atr_pct_1h: float
    atr_pct_4h: float
    atr_pct_5m: float
    bb_width_pct_1h: float
    bb_upper_1h: float
    bb_mid_1h: float
    bb_lower_1h: float
    adx_1h: float
    adx_slope_1h: float
    ema20_1h: float
    ema50_1h: float
    ema200_1h: float | None
    ema_stack_1h: int
    dist_to_ema200_pct: float
    ema50_slope_1h: float
    range_position: float
    last_move_pct_5m: float
    last_move_pct_15m: float
    last_move_pct_1h: float
    last_move_pct_4h: float
    funding_rate: float | None
    volume_ratio_24h: float
    weekday: int
    hour_utc: int
    minute_in_hour: int
    close: float


@dataclass
class RegimeSnapshot:
    """Serializable regime snapshot returned by classify()."""

    primary_regime: str
    modifiers: List[str]
    regime_age_bars: int
    metrics: RegimeMetrics
    bias_score: int
    session: str
    ts: datetime
    symbol: str
    reasoning: Dict[str, Any]
    hysteresis_state: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["ts"] = _dt_to_str(self.ts)
        return payload


@dataclass
class ModifierState:
    """Persistent state for one modifier."""

    activated_at: datetime
    expires_at: datetime | None
    trigger_context: Dict[str, Any]


@dataclass
class RegimeState:
    """Persistent state for one symbol."""

    current_primary: str = PRIMARY_RANGE
    primary_since: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    hysteresis_counter: int = 0
    pending_primary: str | None = None
    active_modifiers: Dict[str, ModifierState] = field(default_factory=dict)
    regime_age_bars: int = 0
    atr_history_1h: List[float] = field(default_factory=list)
    bb_width_history_1h: List[float] = field(default_factory=list)


class RegimeStateStore:
    """Persistent JSON-backed state for the regime classifier."""

    def __init__(self, path: str = "state/regime_state.json") -> None:
        self.path = Path(path)

    def get_state(self, symbol: str) -> RegimeState:
        payload = self._load()
        raw = ((payload.get("symbols") or {}).get(symbol) or {})
        return self._deserialize_state(raw)

    def save_state(self, symbol: str, state: RegimeState) -> None:
        payload = self._load()
        symbols = payload.setdefault("symbols", {})
        symbols[symbol] = self._serialize_state(state)
        self._write_with_retry(payload)

    def get_blackout(self) -> datetime | None:
        payload = self._load()
        blackout = payload.get("manual_blackout_until")
        return _str_to_dt(blackout) if blackout else None

    def set_blackout(self, blackout_until: datetime | None) -> None:
        payload = self._load()
        payload["manual_blackout_until"] = _dt_to_str(blackout_until) if blackout_until else None
        self._write_with_retry(payload)

    def _load(self) -> Dict[str, Any]:
        default = {"version": 1, "manual_blackout_until": None, "symbols": {}}
        return safe_read_json(str(self.path), default)

    def _write_with_retry(self, payload: Dict[str, Any]) -> None:
        last_error: Exception | None = None
        for delay in (0.0, 0.02, 0.05, 0.1):
            if delay:
                time.sleep(delay)
            try:
                atomic_write_json(str(self.path), payload)
                return
            except PermissionError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error

    def _serialize_state(self, state: RegimeState) -> Dict[str, Any]:
        return {
            "current_primary": state.current_primary,
            "primary_since": _dt_to_str(state.primary_since),
            "regime_age_bars": int(state.regime_age_bars),
            "pending_primary": state.pending_primary,
            "hysteresis_counter": int(state.hysteresis_counter),
            "active_modifiers": {
                name: {
                    "activated_at": _dt_to_str(mod.activated_at),
                    "expires_at": _dt_to_str(mod.expires_at) if mod.expires_at else None,
                    "trigger_context": dict(mod.trigger_context or {}),
                }
                for name, mod in (state.active_modifiers or {}).items()
            },
            "atr_history_1h": [float(x) for x in state.atr_history_1h[-6:]],
            "bb_width_history_1h": [float(x) for x in state.bb_width_history_1h[-720:]],
        }

    def _deserialize_state(self, raw: Dict[str, Any]) -> RegimeState:
        active_modifiers = {}
        for name, payload in (raw.get("active_modifiers") or {}).items():
            activated_at = _str_to_dt(payload.get("activated_at")) or datetime.now(timezone.utc)
            expires_at = _str_to_dt(payload.get("expires_at"))
            active_modifiers[name] = ModifierState(
                activated_at=activated_at,
                expires_at=expires_at,
                trigger_context=dict(payload.get("trigger_context") or {}),
            )
        return RegimeState(
            current_primary=str(raw.get("current_primary") or PRIMARY_RANGE),
            primary_since=_str_to_dt(raw.get("primary_since")) or datetime.now(timezone.utc),
            hysteresis_counter=int(raw.get("hysteresis_counter") or 0),
            pending_primary=raw.get("pending_primary"),
            active_modifiers=active_modifiers,
            regime_age_bars=int(raw.get("regime_age_bars") or 0),
            atr_history_1h=[float(x) for x in list(raw.get("atr_history_1h") or [])[-6:]],
            bb_width_history_1h=[float(x) for x in list(raw.get("bb_width_history_1h") or [])[-720:]],
        )


def calc_atr_pct(candles: List[dict], period: int = 14) -> float:
    """Return ATR as a percentage of the latest close."""
    if len(candles) < period + 1:
        return 0.0
    trs: List[float] = []
    for i in range(1, len(candles)):
        high = _candle_value(candles[i], "high")
        low = _candle_value(candles[i], "low")
        prev_close = _candle_value(candles[i - 1], "close")
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    atr = sum(trs[-period:]) / period
    last_close = _candle_value(candles[-1], "close")
    return (atr / last_close * 100.0) if last_close else 0.0


def calc_adx(candles: List[dict], period: int = 14) -> Tuple[float, float]:
    """Return Wilder ADX and its 3-bar slope."""
    if len(candles) < period * 2 + 4:
        return 0.0, 0.0

    trs: List[float] = []
    plus_dm: List[float] = []
    minus_dm: List[float] = []
    for i in range(1, len(candles)):
        high = _candle_value(candles[i], "high")
        low = _candle_value(candles[i], "low")
        prev_high = _candle_value(candles[i - 1], "high")
        prev_low = _candle_value(candles[i - 1], "low")
        prev_close = _candle_value(candles[i - 1], "close")

        up_move = high - prev_high
        down_move = prev_low - low
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))

    tr14 = sum(trs[:period])
    plus14 = sum(plus_dm[:period])
    minus14 = sum(minus_dm[:period])
    dx_values: List[float] = []
    for idx in range(period, len(trs)):
        tr14 = tr14 - (tr14 / period) + trs[idx]
        plus14 = plus14 - (plus14 / period) + plus_dm[idx]
        minus14 = minus14 - (minus14 / period) + minus_dm[idx]
        plus_di = (plus14 / tr14 * 100.0) if tr14 else 0.0
        minus_di = (minus14 / tr14 * 100.0) if tr14 else 0.0
        denom = plus_di + minus_di
        dx_values.append((abs(plus_di - minus_di) / denom * 100.0) if denom else 0.0)

    if len(dx_values) < period:
        return 0.0, 0.0

    adx_series: List[float] = []
    adx = sum(dx_values[:period]) / period
    adx_series.append(adx)
    for dx in dx_values[period:]:
        adx = ((adx * (period - 1)) + dx) / period
        adx_series.append(adx)

    current_adx = adx_series[-1] if adx_series else 0.0
    anchor = adx_series[-4] if len(adx_series) >= 4 else adx_series[0]
    return current_adx, current_adx - anchor


def calc_ema(candles: List[dict], period: int) -> float:
    """Return exponential moving average of close."""
    if not candles:
        return 0.0
    alpha = 2.0 / (period + 1)
    ema = _candle_value(candles[0], "close")
    for candle in candles[1:]:
        close = _candle_value(candle, "close")
        ema = close * alpha + ema * (1.0 - alpha)
    return ema


def calc_ema_stack(close: float, ema20: float, ema50: float, ema200: float) -> int:
    """Return directional EMA stack score from -2 to +2."""
    if close > ema20 > ema50 > ema200:
        return 2
    if close < ema20 < ema50 < ema200:
        return -2
    above = sum([close > ema20, close > ema50, close > ema200])
    if above >= 2:
        return 1
    if above <= 1:
        return -1
    return 0


def calc_bollinger(candles: List[dict], period: int = 20, k: float = 2.0) -> Tuple[float, float, float, float]:
    """Return Bollinger upper, mid, lower and width percentage."""
    if len(candles) < period:
        close = _candle_value(candles[-1], "close") if candles else 0.0
        return close, close, close, 0.0
    closes = [_candle_value(c, "close") for c in candles[-period:]]
    mid = sum(closes) / period
    var = sum((x - mid) ** 2 for x in closes) / period
    std = var ** 0.5
    upper = mid + k * std
    lower = mid - k * std
    width_pct = ((upper - lower) / mid * 100.0) if mid else 0.0
    return upper, mid, lower, width_pct


def calc_bias_score(metrics: RegimeMetrics) -> int:
    """Return composite directional bias score in [-100, 100]."""
    score = 0.0
    score += metrics.ema_stack_1h * 20
    dist = max(-3.0, min(3.0, metrics.dist_to_ema200_pct))
    score += dist / 3.0 * 20
    if metrics.ema50_slope_1h > 0:
        score += min(20.0, metrics.adx_1h * 0.7)
    else:
        score -= min(20.0, metrics.adx_1h * 0.7)
    score += (metrics.range_position - 0.5) * 20.0
    move_4h = max(-5.0, min(5.0, metrics.last_move_pct_4h))
    score += move_4h * 2.0
    return max(-100, min(100, round(score)))


def calc_range_position(close: float, candles_1h: List[dict], lookback: int = 20) -> float:
    """Return close position inside recent lookback range."""
    if not candles_1h:
        return 0.5
    recent = candles_1h[-lookback:]
    high = max(_candle_value(c, "high") for c in recent)
    low = min(_candle_value(c, "low") for c in recent)
    if high == low:
        return 0.5
    value = (close - low) / (high - low)
    return max(0.0, min(1.0, value))


def calc_session(hour_utc: int) -> str:
    """Return market session name for UTC hour."""
    if 0 <= hour_utc < 7:
        return "ASIAN"
    if 7 <= hour_utc < 13:
        return "EU"
    if 13 <= hour_utc < 22:
        return "US"
    return "ASIAN"


def detect_cascade_down(metrics: RegimeMetrics) -> bool:
    """Return True when a fast downside cascade is detected."""
    return (
        metrics.last_move_pct_15m < -3.0
        or metrics.last_move_pct_1h < -5.0
        or metrics.last_move_pct_4h < -8.0
    )


def detect_cascade_up(metrics: RegimeMetrics) -> bool:
    """Return True when a fast upside cascade is detected."""
    return (
        metrics.last_move_pct_15m > 3.0
        or metrics.last_move_pct_1h > 5.0
        or metrics.last_move_pct_4h > 8.0
    )


def detect_trend_up(metrics: RegimeMetrics) -> bool:
    """Return True when the bull trend criteria are met."""
    if metrics.ema200_1h is None:
        return False
    return (
        metrics.dist_to_ema200_pct > 0
        and metrics.ema50_1h > metrics.ema200_1h
        and metrics.adx_1h > 25
        and metrics.ema50_slope_1h > 0
    )


def detect_trend_down(metrics: RegimeMetrics) -> bool:
    """Return True when the bear trend criteria are met."""
    if metrics.ema200_1h is None:
        return False
    return (
        metrics.dist_to_ema200_pct < 0
        and metrics.ema50_1h < metrics.ema200_1h
        and metrics.adx_1h > 25
        and metrics.ema50_slope_1h < 0
    )


def detect_compression(metrics: RegimeMetrics, atr_history_1h: List[float], bb_width_history: List[float]) -> bool:
    """Return True when ATR stays suppressed and BB width is in the lowest quintile."""
    if len(atr_history_1h) < 6:
        return False
    if any(a >= 0.8 for a in atr_history_1h[-6:]):
        return False
    if len(bb_width_history) < 30:
        return False
    sorted_widths = sorted(bb_width_history)
    p20 = sorted_widths[len(sorted_widths) // 5]
    return metrics.bb_width_pct_1h < p20


def detect_range(metrics: RegimeMetrics) -> bool:
    """Return True when price is ranging inside BB with low ATR."""
    return (
        metrics.atr_pct_1h < 1.5
        and metrics.bb_lower_1h <= metrics.close <= metrics.bb_upper_1h
    )


def apply_hysteresis(
    current: str,
    candidate: str,
    pending: str | None,
    counter: int,
    is_cascade: bool,
) -> Tuple[str, str | None, int]:
    """Apply 2-bar confirmation for non-cascade primary transitions."""
    if is_cascade:
        return candidate, None, 0
    if candidate == current:
        return current, None, 0
    if candidate == pending:
        new_counter = counter + 1
        if new_counter >= 2:
            return candidate, None, 0
        return current, pending, new_counter
    return current, candidate, 1


def detect_weekend_low_vol(metrics: RegimeMetrics) -> bool:
    """Return True on Saturday and Sunday UTC."""
    return metrics.weekday in (5, 6)


def detect_weekend_gap(candles_1h: List[dict], now: datetime) -> Optional[Dict[str, Any]]:
    """Detect the weekly Sunday reopen gap within the alert window."""
    now = _ensure_utc(now)
    if now.weekday() == 6 and now.hour < 23:
        return None
    if now.weekday() == 0 and now.hour >= 6:
        return None
    if now.weekday() not in (6, 0):
        return None

    fri_close = None
    sun_close = None
    for candle in candles_1h:
        ts = _candle_time(candle)
        if ts is None:
            continue
        if ts.weekday() == 4 and ts.hour == 22:
            fri_close = _candle_value(candle, "close")
        elif ts.weekday() == 6 and ts.hour == 23:
            sun_close = _candle_value(candle, "close")
    if not fri_close or not sun_close:
        return None

    gap_pct = (sun_close - fri_close) / fri_close * 100.0
    if abs(gap_pct) < 0.5:
        return None
    return {
        "gap_pct": gap_pct,
        "direction": "UP" if gap_pct > 0 else "DOWN",
        "friday_ref_price": fri_close,
        "sunday_ref_price": sun_close,
    }


def detect_huge_down_gap(weekend_gap: Optional[Dict]) -> bool:
    """Return True when weekend gap is down by more than 5%."""
    return bool(
        weekend_gap
        and weekend_gap.get("direction") == "DOWN"
        and abs(float(weekend_gap.get("gap_pct") or 0.0)) > 5.0
    )


def detect_trend_suspected(primary: str, weekend_gap: Optional[Dict]) -> Optional[str]:
    """Return suspected trend modifier for opposing weekend gaps above 1.5%."""
    if not weekend_gap or abs(float(weekend_gap.get("gap_pct") or 0.0)) < 1.5:
        return None
    if primary == PRIMARY_TREND_UP and weekend_gap.get("direction") == "DOWN":
        return MODIFIER_TREND_UP_SUSPECTED
    if primary == PRIMARY_TREND_DOWN and weekend_gap.get("direction") == "UP":
        return MODIFIER_TREND_DOWN_SUSPECTED
    return None


def detect_post_funding(metrics: RegimeMetrics) -> bool:
    """Return True during the first 30 minutes after funding hours."""
    return metrics.hour_utc in (0, 8, 16) and metrics.minute_in_hour < 30


def detect_blackout(manual_blackout_until: Optional[datetime], now: datetime) -> bool:
    """Return True when manual blackout is still active."""
    if manual_blackout_until is None:
        return False
    return _ensure_utc(now) < _ensure_utc(manual_blackout_until)


def classify(
    symbol: str,
    ts: datetime,
    candles_1m: List[dict],
    candles_15m: List[dict],
    candles_1h: List[dict],
    candles_4h: List[dict],
    funding_rate: float | None,
    manual_blackout_until: datetime | None,
    state_store: RegimeStateStore,
) -> RegimeSnapshot:
    """Classify the current market regime from multi-timeframe candles."""
    ts = _ensure_utc(ts)
    state = state_store.get_state(symbol)

    metrics = _compute_metrics(
        ts=ts,
        candles_1m=candles_1m,
        candles_15m=candles_15m,
        candles_1h=candles_1h,
        candles_4h=candles_4h,
        funding_rate=funding_rate,
    )

    if metrics.ema200_1h is None:
        candidate = PRIMARY_RANGE
        is_cascade = False
        fallback_reason = "ema200_unavailable"
    elif detect_cascade_down(metrics):
        candidate = PRIMARY_CASCADE_DOWN
        is_cascade = True
        fallback_reason = None
    elif detect_cascade_up(metrics):
        candidate = PRIMARY_CASCADE_UP
        is_cascade = True
        fallback_reason = None
    elif detect_trend_up(metrics):
        candidate = PRIMARY_TREND_UP
        is_cascade = False
        fallback_reason = None
    elif detect_trend_down(metrics):
        candidate = PRIMARY_TREND_DOWN
        is_cascade = False
        fallback_reason = None
    elif detect_compression(metrics, state.atr_history_1h, state.bb_width_history_1h):
        candidate = PRIMARY_COMPRESSION
        is_cascade = False
        fallback_reason = None
    elif detect_range(metrics):
        candidate = PRIMARY_RANGE
        is_cascade = False
        fallback_reason = None
    else:
        candidate = state.current_primary or PRIMARY_RANGE
        is_cascade = False
        fallback_reason = "keep_current"

    new_current, new_pending, new_counter = apply_hysteresis(
        state.current_primary,
        candidate,
        state.pending_primary,
        state.hysteresis_counter,
        is_cascade,
    )

    # Min-dwell gate for RANGE↔COMPRESSION flips only. Trend/cascade transitions
    # bypass this check — when the market is genuinely trending, we want fast
    # response. Low-vol pair flap is the observed pathology.
    if (new_current != state.current_primary
            and not is_cascade
            and {new_current, state.current_primary} <= LOW_VOL_FLIP_PAIR
            and state.primary_since is not None):
        try:
            dwell_min = (ts - _ensure_utc(state.primary_since)).total_seconds() / 60.0
        except (TypeError, ValueError):
            dwell_min = MIN_DWELL_MIN_LOW_VOL_FLIP  # treat as eligible if state corrupt
        # Only suppress when dwell is positive but below threshold. Negative
        # dwell (stale state / clock skew / test fixture) is treated as "no
        # recent transition observed" → allow flip.
        if 0 <= dwell_min < MIN_DWELL_MIN_LOW_VOL_FLIP:
            logger.info(
                "regime.min_dwell_suppress symbol=%s from=%s to=%s dwell_min=%.1f threshold=%d",
                symbol, state.current_primary, new_current, dwell_min, MIN_DWELL_MIN_LOW_VOL_FLIP,
            )
            new_current = state.current_primary
            new_pending = None
            new_counter = 0

    weekend_gap = detect_weekend_gap(candles_1h, ts)
    requested_modifiers: Dict[str, Dict[str, Any]] = {}
    if detect_blackout(manual_blackout_until, ts):
        requested_modifiers[MODIFIER_BLACKOUT] = {}
    if detect_huge_down_gap(weekend_gap):
        requested_modifiers[MODIFIER_HUGE_DOWN_GAP] = dict(weekend_gap or {})
    suspect = detect_trend_suspected(new_current, weekend_gap)
    if suspect:
        requested_modifiers[suspect] = dict(weekend_gap or {})
    if detect_post_funding(metrics):
        requested_modifiers[MODIFIER_POST_FUNDING] = {"hour": metrics.hour_utc, "minute": metrics.minute_in_hour}
    if detect_weekend_low_vol(metrics):
        requested_modifiers[MODIFIER_WEEKEND_LOW_VOL] = {"weekday": metrics.weekday}
    if weekend_gap is not None:
        requested_modifiers[MODIFIER_WEEKEND_GAP] = dict(weekend_gap)

    state.atr_history_1h = _append_ringbuffer(state.atr_history_1h, metrics.atr_pct_1h, 6)
    state.bb_width_history_1h = _append_ringbuffer(state.bb_width_history_1h, metrics.bb_width_pct_1h, 720)
    state.active_modifiers = _merge_modifiers(
        current=state.active_modifiers,
        requested=requested_modifiers,
        now=ts,
        primary=new_current,
        price=metrics.close,
    )

    modifiers = [name for name in MODIFIER_PRIORITY if name in state.active_modifiers]

    if new_current != state.current_primary:
        age_bars = 0
        state.primary_since = ts
    else:
        age_bars = state.regime_age_bars + 1

    state.current_primary = new_current
    state.pending_primary = new_pending
    state.hysteresis_counter = new_counter
    state.regime_age_bars = age_bars
    state_store.save_state(symbol, state)

    return RegimeSnapshot(
        primary_regime=new_current,
        modifiers=modifiers,
        regime_age_bars=age_bars,
        metrics=metrics,
        bias_score=calc_bias_score(metrics),
        session=calc_session(metrics.hour_utc),
        ts=ts,
        symbol=symbol,
        reasoning={
            "candidate": candidate,
            "is_cascade": is_cascade,
            "fallback_reason": fallback_reason,
            "weekend_gap": weekend_gap,
        },
        hysteresis_state={"counter": new_counter, "pending": new_pending},
    )


def _compute_metrics(
    ts: datetime,
    candles_1m: List[dict],
    candles_15m: List[dict],
    candles_1h: List[dict],
    candles_4h: List[dict],
    funding_rate: float | None,
) -> RegimeMetrics:
    close = _candle_value(candles_1h[-1], "close") if candles_1h else 0.0
    upper, mid, lower, bb_width_pct = calc_bollinger(candles_1h)
    ema20 = calc_ema(candles_1h[-max(len(candles_1h), 20):], 20) if candles_1h else 0.0
    ema50 = calc_ema(candles_1h[-max(len(candles_1h), 50):], 50) if candles_1h else 0.0
    ema200 = calc_ema(candles_1h[-max(len(candles_1h), 200):], 200) if len(candles_1h) >= 200 else None
    adx, adx_slope = calc_adx(candles_1h)
    ema50_prev = calc_ema(candles_1h[:-1], 50) if len(candles_1h) > 50 else ema50
    ema50_slope = ((ema50 - ema50_prev) / ema50_prev * 100.0) if ema50_prev else 0.0
    range_position = calc_range_position(close, candles_1h)
    dist_to_ema200_pct = ((close - ema200) / ema200 * 100.0) if ema200 else 0.0
    volume_ratio_24h = _volume_ratio_24h(candles_1h)
    return RegimeMetrics(
        atr_pct_1h=calc_atr_pct(candles_1h, 14),
        atr_pct_4h=calc_atr_pct(candles_4h, 14),
        atr_pct_5m=calc_atr_pct(candles_1m, 5),
        bb_width_pct_1h=bb_width_pct,
        bb_upper_1h=upper,
        bb_mid_1h=mid,
        bb_lower_1h=lower,
        adx_1h=adx,
        adx_slope_1h=adx_slope,
        ema20_1h=ema20,
        ema50_1h=ema50,
        ema200_1h=ema200,
        ema_stack_1h=calc_ema_stack(close, ema20, ema50, ema200 if ema200 is not None else close),
        dist_to_ema200_pct=dist_to_ema200_pct,
        ema50_slope_1h=ema50_slope,
        range_position=range_position,
        last_move_pct_5m=_move_pct(candles_1m, 5),
        last_move_pct_15m=_move_pct(candles_15m, 1),
        last_move_pct_1h=_move_pct(candles_1h, 1),
        last_move_pct_4h=_move_pct(candles_4h, 1),
        funding_rate=funding_rate,
        volume_ratio_24h=volume_ratio_24h,
        weekday=ts.weekday(),
        hour_utc=ts.hour,
        minute_in_hour=ts.minute,
        close=close,
    )


def _merge_modifiers(
    current: Dict[str, ModifierState],
    requested: Dict[str, Dict[str, Any]],
    now: datetime,
    primary: str,
    price: float,
) -> Dict[str, ModifierState]:
    active: Dict[str, ModifierState] = {}
    current = dict(current or {})

    for name, state in current.items():
        if _modifier_expired(name, state, now, primary, price):
            continue
        active[name] = state

    for name, context in requested.items():
        expires_at = _modifier_expiry(name, now)
        existing = active.get(name)
        activated_at = existing.activated_at if existing else now
        active[name] = ModifierState(
            activated_at=activated_at,
            expires_at=expires_at,
            trigger_context=dict(context or {}),
        )
    return active


def _modifier_expired(name: str, state: ModifierState, now: datetime, primary: str, price: float) -> bool:
    if state.expires_at is not None and now >= state.expires_at:
        return True
    if name == MODIFIER_HUGE_DOWN_GAP:
        friday_ref = float((state.trigger_context or {}).get("friday_ref_price") or 0.0)
        if friday_ref and price >= friday_ref:
            return True
    if name in {MODIFIER_TREND_UP_SUSPECTED, MODIFIER_TREND_DOWN_SUSPECTED}:
        if name == MODIFIER_TREND_UP_SUSPECTED and primary != PRIMARY_TREND_UP:
            return True
        if name == MODIFIER_TREND_DOWN_SUSPECTED and primary != PRIMARY_TREND_DOWN:
            return True
    return False


def _modifier_expiry(name: str, now: datetime) -> datetime | None:
    if name == MODIFIER_HUGE_DOWN_GAP:
        return now + timedelta(hours=48)
    if name in {MODIFIER_TREND_UP_SUSPECTED, MODIFIER_TREND_DOWN_SUSPECTED}:
        return now + timedelta(hours=48)
    if name == MODIFIER_WEEKEND_GAP:
        return now + timedelta(hours=72)
    return None


def _append_ringbuffer(values: Iterable[float], value: float, max_len: int) -> List[float]:
    items = list(values or [])
    items.append(float(value))
    return items[-max_len:]


def _move_pct(candles: List[dict], bars_back: int) -> float:
    if len(candles) <= bars_back:
        return 0.0
    last_close = _candle_value(candles[-1], "close")
    prev_close = _candle_value(candles[-1 - bars_back], "close")
    return ((last_close - prev_close) / prev_close * 100.0) if prev_close else 0.0


def _volume_ratio_24h(candles_1h: List[dict]) -> float:
    if not candles_1h:
        return 0.0
    current = float(candles_1h[-1].get("volume", 0.0) or 0.0)
    window = candles_1h[-168:] if len(candles_1h) >= 168 else candles_1h
    avg = sum(float(c.get("volume", 0.0) or 0.0) for c in window) / max(1, len(window))
    return (current / avg) if avg else 0.0


def _candle_value(candle: dict, field: str) -> float:
    return float((candle or {}).get(field, 0.0) or 0.0)


def _candle_time(candle: dict) -> datetime | None:
    if not candle:
        return None
    open_time = candle.get("open_time")
    if open_time is None:
        return None
    try:
        value = int(open_time)
    except Exception:
        return None
    if value > 10_000_000_000:
        return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
    return datetime.fromtimestamp(value, tz=timezone.utc)


def _dt_to_str(value: datetime | None) -> str | None:
    if value is None:
        return None
    value = _ensure_utc(value)
    return value.isoformat().replace("+00:00", "Z")


def _str_to_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
