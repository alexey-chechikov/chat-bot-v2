from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any


class SetupType(Enum):
    LONG_DUMP_REVERSAL = "long_dump_reversal"
    LONG_PDL_BOUNCE = "long_pdl_bounce"
    LONG_OVERSOLD_RECLAIM = "long_oversold_reclaim"
    LONG_LIQ_MAGNET = "long_liq_magnet"
    SHORT_RALLY_FADE = "short_rally_fade"
    SHORT_PDH_REJECTION = "short_pdh_rejection"
    SHORT_OVERBOUGHT_FADE = "short_overbought_fade"
    SHORT_LIQ_MAGNET = "short_liq_magnet"
    LONG_DOUBLE_BOTTOM = "long_double_bottom"
    LONG_DOUBLE_BOTTOM_BREAKOUT = "long_double_bottom_breakout"
    SHORT_DOUBLE_TOP = "short_double_top"
    LONG_MULTI_DIVERGENCE = "long_multi_divergence"
    LONG_DIV_BOS_CONFIRMED = "long_div_bos_confirmed"
    LONG_DIV_BOS_15M = "long_div_bos_15m"
    SHORT_DIV_BOS_15M = "short_div_bos_15m"
    LONG_MULTI_ASSET_CONFLUENCE = "long_multi_asset_confluence"
    LONG_MULTI_ASSET_CONFLUENCE_V2 = "long_multi_asset_confluence_v2"
    LONG_MEGA_DUMP_BOUNCE = "long_mega_dump_bounce"
    LONG_RSI_MOMENTUM_GA = "long_rsi_momentum_ga"
    SHORT_MFI_MULTI_GA = "short_mfi_multi_ga"
    # P-15 rolling-trend rebalance (validated 2026-05-08, +$67k 2y on 15m).
    # 5-stage lifecycle: OPEN -> TRACK -> HARVEST -> REENTRY -> CLOSE.
    P15_LONG_OPEN = "p15_long_open"
    P15_LONG_HARVEST = "p15_long_harvest"
    P15_LONG_REENTRY = "p15_long_reentry"
    P15_LONG_CLOSE = "p15_long_close"
    P15_SHORT_OPEN = "p15_short_open"
    P15_SHORT_HARVEST = "p15_short_harvest"
    P15_SHORT_REENTRY = "p15_short_reentry"
    P15_SHORT_CLOSE = "p15_short_close"
    # 2026-05-11: Session breakout — backtest PF 1.52 (all transitions) / 2.09
    # (ny_pm_to_asia). See docs/STRATEGIES/SESSION_BREAKOUT_BACKTEST.md.
    LONG_SESSION_BREAKOUT = "long_session_breakout"
    SHORT_SESSION_BREAKOUT = "short_session_breakout"
    GRID_RAISE_BOUNDARY = "grid_raise_boundary"
    GRID_PAUSE_ENTRIES = "grid_pause_entries"
    GRID_BOOSTER_ACTIVATE = "grid_booster"
    GRID_ADAPTIVE_TIGHTEN = "grid_adaptive"
    DEFENSIVE_LIQ_PROXIMITY = "def_liq_proximity"
    DEFENSIVE_MARGIN_LOW = "def_margin_low"


class SetupStatus(Enum):
    DETECTED = "detected"
    ENTRY_HIT = "entry_hit"
    TP1_HIT = "tp1_hit"
    TP2_HIT = "tp2_hit"
    STOP_HIT = "stop_hit"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"


@dataclass(frozen=True)
class SetupBasis:
    label: str
    value: float | str
    weight: float  # [0.0 .. 1.0] contribution to strength score


@dataclass(frozen=True)
class Setup:
    setup_id: str
    setup_type: SetupType
    detected_at: datetime

    pair: str
    current_price: float
    regime_label: str
    session_label: str

    entry_price: float | None
    stop_price: float | None
    tp1_price: float | None
    tp2_price: float | None
    risk_reward: float | None

    grid_action: str | None
    grid_target_bots: tuple[str, ...]
    grid_param_change: dict[str, Any] | None

    strength: int            # 1..10
    confidence_pct: float    # 0..100
    basis: tuple[SetupBasis, ...]
    cancel_conditions: tuple[str, ...]

    window_minutes: int
    expires_at: datetime
    status: SetupStatus

    portfolio_impact_note: str
    recommended_size_btc: float

    # ICT context at detection time (14 fields from ict_levels parquet).
    # Empty dict when parquet is unavailable or not yet generated.
    ict_context: dict[str, Any] = field(default_factory=dict)

    @property
    def semantic_signature(self) -> str:
        """Stable hash identifying the same logical setup across detector cycles.

        2026-05-10 incident: short_pdh_rejection emitted every 4min on XRP because
        basis values (RSI, volume) drift continuously while the same PDH/PDL
        condition holds. Now: round numerics to 1dp/coarse-bucket so micro-drift
        doesn't break dedup. Setup is "the same" as long as level + regime hold.

        Includes setup_type, pair, regime. Basis numeric values bucketed:
          - RSI/MFI/score → integer (rounded)
          - prices → 1dp
          - volume ratios / vol_z → 1 decimal
        """
        parts = [self.setup_type.value, self.pair, self.regime_label]
        for b in sorted(self.basis, key=lambda x: x.label):
            v = b.value
            label_lower = b.label.lower() if isinstance(b.label, str) else ""
            if isinstance(v, float):
                # Coarse-bucket noisy indicators so micro-drift doesn't bypass dedup.
                # Stride 5 for RSI/MFI (62-67 -> "65"), stride 0.5 for volume ratios.
                if any(k in label_lower for k in ("rsi", "mfi")):
                    v = str(int(round(v / 5.0) * 5))  # bucket by 5
                elif any(k in label_lower for k in ("score", "тест", "wick", "test")):
                    v = str(int(round(v)))  # integer
                elif any(k in label_lower for k in ("объём", "volume", "ratio", "vol_z")):
                    v = f"{round(v * 2) / 2:.1f}"  # 0.5 stride: 1.55 -> 1.5
                else:
                    v = f"{v:.1f}"
            parts.append(f"{b.label}={v}")
        canonical = "|".join(parts)
        return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:12]


def round_price(value: float | None) -> float | None:
    """Magnitude-aware округление цены. 2026-06-21: детекторы рубили round(x,1) —
    ок для BTC ($64000), но XRP $1.1474 → 1.1 (8% тик!) → entry=stop=tp,
    сигнал нечитаем (Win-аудит). Даём значимые знаки под масштаб цены."""
    if value is None:
        return None
    a = abs(value)
    if a >= 1000:
        return round(value, 1)
    if a >= 100:
        return round(value, 2)
    if a >= 1:
        return round(value, 4)
    if a >= 0.01:
        return round(value, 5)
    return round(value, 6)


def make_setup(
    *,
    setup_type: SetupType,
    pair: str,
    current_price: float,
    regime_label: str,
    session_label: str,
    entry_price: float | None = None,
    stop_price: float | None = None,
    tp1_price: float | None = None,
    tp2_price: float | None = None,
    risk_reward: float | None = None,
    grid_action: str | None = None,
    grid_target_bots: tuple[str, ...] = (),
    grid_param_change: dict[str, Any] | None = None,
    strength: int,
    confidence_pct: float,
    basis: tuple[SetupBasis, ...],
    cancel_conditions: tuple[str, ...],
    window_minutes: int = 120,
    portfolio_impact_note: str = "",
    recommended_size_btc: float = 0.05,
    detected_at: datetime | None = None,
    ict_context: dict[str, Any] | None = None,
) -> Setup:
    now = detected_at if detected_at is not None else datetime.now(timezone.utc)
    setup_id = f"setup-{now.strftime('%Y-%m-%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    return Setup(
        setup_id=setup_id,
        setup_type=setup_type,
        detected_at=now,
        pair=pair,
        current_price=current_price,
        regime_label=regime_label,
        session_label=session_label,
        entry_price=round_price(entry_price),
        stop_price=round_price(stop_price),
        tp1_price=round_price(tp1_price),
        tp2_price=round_price(tp2_price),
        risk_reward=risk_reward,
        grid_action=grid_action,
        grid_target_bots=grid_target_bots,
        grid_param_change=grid_param_change,
        strength=strength,
        confidence_pct=confidence_pct,
        basis=basis,
        cancel_conditions=cancel_conditions,
        window_minutes=window_minutes,
        expires_at=now + timedelta(minutes=window_minutes),
        status=SetupStatus.DETECTED,
        portfolio_impact_note=portfolio_impact_note,
        recommended_size_btc=recommended_size_btc,
        ict_context=ict_context if ict_context is not None else {},
    )


def setup_side(setup: Setup) -> str:
    """Returns 'long', 'short', 'grid', 'defensive', or 'p15_long' / 'p15_short'."""
    v = setup.setup_type.value
    if v.startswith("p15_long_"):
        return "p15_long"
    if v.startswith("p15_short_"):
        return "p15_short"
    if v.startswith("long_"):
        return "long"
    if v.startswith("short_"):
        return "short"
    if v.startswith("grid_"):
        return "grid"
    return "defensive"
