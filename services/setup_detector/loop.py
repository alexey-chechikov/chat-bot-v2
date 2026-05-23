from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .combo_filter import filter_setups, is_combo_allowed
from .runtime_disabled import is_detector_disabled
from .ict_context import ICT_CONTEXT_COLS, ICTContextReader
from .models import Setup
from .pipeline_metrics import record as metrics_record, record_setup
from .setup_types import DETECTOR_REGISTRY, DetectionContext, PortfolioSnapshot
from .storage import SetupStorage
from .telegram_card import format_telegram_card

logger = logging.getLogger(__name__)

_LOOP_INTERVAL_SEC = 300  # 5 min
_MIN_STRENGTH = 6

# Semantic dedup: suppress re-emission of the same logical setup (same
# divergence pivot, same regime) within this TTL. Without this, a 20h-window
# divergence fires every 5min cycle = ~240 duplicate setups in TG + paper trades.
# Bug observed live 2026-05-08 evening: same long_multi_divergence
# (price_LL 79500->79181) fired 18:54/18:59/19:04/19:09/19:14 etc.
_SETUP_DEDUP_TTL_MIN = 240  # 4h — covers most setup window_minutes (240min)
_DEDUP_PATH = Path("state/setup_detector_semantic_dedup.json")

# 2026-05-11 TZ-N3: shadow mode. When env GC_SHADOW_MODE=1, GC decisions
# are recorded in the audit (alignment, would-be decision) but NOT applied
# to the setup. Lets operator collect a week of data on a candidate config
# (e.g. relaxed HARD_BLOCK or higher score threshold) before committing.
import os as _os  # local alias to avoid touching toplevel imports
def _gc_shadow_mode() -> bool:
    return _os.environ.get("GC_SHADOW_MODE", "").strip() in ("1", "true", "yes")
# 2026-05-10: belt-and-suspenders dedup. semantic_signature includes basis
# label strings with embedded numeric formatting (e.g. "Объём x1.4") which
# drifts every 5min loop, leaking through dedup. Cap to 1 emit per
# setup_type+pair per N minutes regardless of basis differences.
# Observed live: short_pdh_rejection emitted 29× on 2026-05-01 trending day.
_TYPE_PAIR_DEDUP_MIN = 60
_TYPE_PAIR_DEDUP_PATH = Path("state/setup_detector_type_pair_dedup.json")
_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_ICT_PARQUET = _ROOT / "data" / "ict_levels" / "BTCUSDT_ict_levels_1m.parquet"

# 2026-05-10 GC-confirmation: see docs/STRATEGIES/GRID_COORDINATOR_VS_DETECTORS.md.
# Detectors with high alignment (>=30% aligned, 0% misaligned) get confidence
# boost when GC confirms; detectors with high misalignment (multi_divergence,
# double_top/bottom) get suppressed when GC contradicts.
_GC_AUDIT_PATH = Path("state/gc_confirmation_audit.jsonl")
_GC_BOOST_PCT = 15.0     # +15% confidence when aligned
_GC_PENALTY_PCT = 30.0   # -30% confidence when misaligned
_GC_MISALIGNED_HARD_BLOCK = {  # detectors so noisy they're hard-blocked when misaligned
    "long_multi_divergence",       # 9% aligned vs 9% misaligned (worst signal-to-GC)
    "long_double_bottom",          # 1% aligned vs 9% misaligned (predict-against-trend)
    "short_double_top",            # 1% aligned vs 9% misaligned
    "long_rsi_momentum_ga",        # 0% aligned vs 80% misaligned (90d sample)
}
_GC_SCORE_MIN = 3

# 2026-05-10 MTF disagreement (DESIGN/MTF_DISAGREEMENT_v1.md):
# - 3/3 TF agreement on side → +10% confidence
# - top-down conflict (15m vs 4h opposite) → -20% confidence
# - other → no change
_MTF_BOOST_PCT = 10.0
_MTF_PENALTY_PCT = 20.0


def _query_grid_coordinator() -> dict | None:
    """Run a fresh evaluate_exhaustion on current 1h BTC/ETH + deriv state.

    Returns {'upside_score': int, 'downside_score': int, 'details': dict} or None
    if data unavailable. Cached errors swallowed.
    """
    try:
        from services.grid_coordinator.loop import evaluate_exhaustion, _read_deriv
        from core.data_loader import load_klines
        btc = load_klines(symbol="BTCUSDT", timeframe="1h", limit=50)
        eth = load_klines(symbol="ETHUSDT", timeframe="1h", limit=50)
        deriv = _read_deriv()
        return evaluate_exhaustion(btc, eth, deriv)
    except Exception:
        logger.exception("setup_detector.gc_query_failed")
        return None


def _gc_alignment(setup: Setup, gc_state: dict) -> str:
    """Returns 'aligned' / 'misaligned' / 'neutral'.

    aligned:    LONG setup + downside_score>=3, OR SHORT setup + upside_score>=3
    misaligned: LONG setup + upside_score>=3, OR SHORT setup + downside_score>=3
    neutral:    GC has no strong signal (both <3) or only same-direction signal
    """
    setup_side = "long" if "long" in setup.setup_type.value.lower() else "short"
    up = int(gc_state.get("upside_score", 0))
    down = int(gc_state.get("downside_score", 0))
    if setup_side == "long":
        if down >= _GC_SCORE_MIN: return "aligned"
        if up >= _GC_SCORE_MIN: return "misaligned"
    else:  # short
        if up >= _GC_SCORE_MIN: return "aligned"
        if down >= _GC_SCORE_MIN: return "misaligned"
    return "neutral"


def _gc_audit_write(record: dict) -> None:
    try:
        _GC_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _GC_AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def _apply_gc_confirmation(setup: Setup, gc_state: dict, now_iso: str) -> tuple[Setup | None, str]:
    """Apply GC alignment to a setup.

    Returns (setup_or_None, decision_str). None means hard-blocked.
    """
    alignment = _gc_alignment(setup, gc_state)
    audit = {
        "ts": now_iso,
        "setup_type": setup.setup_type.value,
        "pair": setup.pair,
        "setup_id": setup.setup_id,
        "side": "long" if "long" in setup.setup_type.value.lower() else "short",
        "gc_upside": gc_state.get("upside_score", 0),
        "gc_downside": gc_state.get("downside_score", 0),
        "alignment": alignment,
        "before_confidence": setup.confidence_pct,
    }

    if alignment == "neutral":
        audit["decision"] = "pass-through"
        audit["after_confidence"] = setup.confidence_pct
        _gc_audit_write(audit)
        return setup, "neutral"

    if alignment == "aligned":
        new_conf = min(99.0, setup.confidence_pct + _GC_BOOST_PCT)
        boosted = dataclasses.replace(setup, confidence_pct=new_conf)
        audit["decision"] = f"boost +{_GC_BOOST_PCT}%"
        audit["after_confidence"] = new_conf
        _gc_audit_write(audit)
        return boosted, "aligned"

    # misaligned
    if setup.setup_type.value in _GC_MISALIGNED_HARD_BLOCK:
        audit["decision"] = "hard-block (high-noise detector)"
        audit["after_confidence"] = None
        _gc_audit_write(audit)
        return None, "misaligned-blocked"

    new_conf = max(10.0, setup.confidence_pct - _GC_PENALTY_PCT)
    penalised = dataclasses.replace(setup, confidence_pct=new_conf)
    audit["decision"] = f"penalty -{_GC_PENALTY_PCT}%"
    audit["after_confidence"] = new_conf
    _gc_audit_write(audit)
    return penalised, "misaligned-penalty"


def _apply_mtf_check(setup: Setup, ctx) -> tuple[Setup, str]:
    """Apply MTF (15m/1h/4h) trend agreement modifier.

    Returns (setup, decision_str) — never blocks, only adjusts confidence.
    """
    try:
        from services.setup_detector.mtf_check import compute_mtf_view, mtf_setup_alignment
    except ImportError:
        return setup, "no-mtf"
    view = compute_mtf_view(ctx)
    side = "long" if "long" in setup.setup_type.value.lower() else "short"
    align = mtf_setup_alignment(side, view)
    if align == "aligned":
        new_conf = min(99.0, setup.confidence_pct + _MTF_BOOST_PCT)
        return dataclasses.replace(setup, confidence_pct=new_conf), "mtf-aligned"
    if align == "conflict":
        new_conf = max(10.0, setup.confidence_pct - _MTF_PENALTY_PCT)
        return dataclasses.replace(setup, confidence_pct=new_conf), "mtf-conflict"
    return setup, "mtf-neutral"


def _simple_session_label(now_utc: datetime) -> str:
    """Fallback session label without advise_v2 dependency."""
    h = now_utc.hour
    if 0 <= h < 8:
        return "asia"
    if 8 <= h < 13:
        return "london"
    if 13 <= h < 17:
        return "ny_am"
    if 17 <= h < 21:
        return "ny_pm"
    return "asia"


def _simple_regime_label(snapshot: dict) -> str:
    """Map raw regime to a simple label without advise_v2."""
    regime = snapshot.get("regime") or {}
    primary = regime.get("primary") or "RANGE"
    mapping = {
        "TREND_UP": "trend_up", "CASCADE_UP": "impulse_up",
        "TREND_DOWN": "trend_down", "CASCADE_DOWN": "impulse_down",
        "RANGE": "range_wide", "COMPRESSION": "consolidation",
    }
    return mapping.get(primary, "range_wide")


def _build_detection_context(pair: str = "BTCUSDT") -> DetectionContext | None:
    """Build live DetectionContext from core pipeline. Returns None on failure.

    No longer depends on services.advise_v2 (which crashed on missing pydantic).
    """
    try:
        import pandas as pd

        from core.data_loader import load_klines
        from core.pipeline import build_full_snapshot

        snapshot = build_full_snapshot(symbol=pair)
        current_price = float(snapshot.get("price", 0.0))
        if current_price <= 0.0:
            logger.warning("setup_detector.build_context: invalid price for %s", pair)
            return None

        regime_label = _simple_regime_label(snapshot)
        now_utc = datetime.now(timezone.utc)
        session_label = _simple_session_label(now_utc)

        df_1m: pd.DataFrame = load_klines(symbol=pair, timeframe="1m", limit=200)
        # 1h limit raised 50 -> 250 to support EMA200 in P-15 detector (was
        # always returning None because len < 200). Other detectors using
        # 1h still work fine with a longer history.
        df_1h: pd.DataFrame = load_klines(symbol=pair, timeframe="1h", limit=250)
        # 15m frame for fast-reaction detectors. limit=200 = ~50h of history,
        # enough for divergence detection (needs >=50 bars). Failure here is
        # non-fatal — detectors that need it guard for empty df_15m.
        try:
            df_15m: pd.DataFrame = load_klines(symbol=pair, timeframe="15m", limit=200)
        except Exception:
            logger.exception("setup_detector.build_context.15m_load_failed pair=%s", pair)
            df_15m = pd.DataFrame()
        if df_1m.empty or df_1h.empty:
            return None

        portfolio = _build_portfolio_snapshot(snapshot)

        return DetectionContext(
            pair=pair,
            current_price=current_price,
            regime_label=regime_label,
            session_label=session_label,
            ohlcv_1m=df_1m,
            ohlcv_1h=df_1h,
            portfolio=portfolio,
            ict_context={},
            ohlcv_15m=df_15m,
        )
    except Exception:
        logger.exception("setup_detector.build_context_failed pair=%s", pair)
        return None


def _load_semantic_dedup() -> dict[str, str]:
    """Load {signature: last_emitted_iso}. Survives restart."""
    if not _DEDUP_PATH.exists():
        return {}
    try:
        return json.loads(_DEDUP_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _save_semantic_dedup(state: dict[str, str]) -> None:
    try:
        _DEDUP_PATH.parent.mkdir(parents=True, exist_ok=True)
        _DEDUP_PATH.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        logger.exception("setup_detector.semantic_dedup_write_failed")


def _is_recently_emitted(setup: Setup, dedup: dict[str, str], now: datetime) -> bool:
    last_iso = dedup.get(setup.semantic_signature)
    if not last_iso:
        return False
    try:
        last = datetime.fromisoformat(last_iso.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (now - last) < timedelta(minutes=_SETUP_DEDUP_TTL_MIN)


def _load_type_pair_dedup() -> dict[str, str]:
    if not _TYPE_PAIR_DEDUP_PATH.exists():
        return {}
    try:
        return json.loads(_TYPE_PAIR_DEDUP_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _save_type_pair_dedup(state: dict[str, str]) -> None:
    try:
        _TYPE_PAIR_DEDUP_PATH.parent.mkdir(parents=True, exist_ok=True)
        _TYPE_PAIR_DEDUP_PATH.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        logger.exception("setup_detector.type_pair_dedup_write_failed")


def _is_type_pair_recently_emitted(setup: Setup, dedup: dict[str, str],
                                    now: datetime) -> bool:
    key = f"{setup.setup_type.value}|{setup.pair}"
    last_iso = dedup.get(key)
    if not last_iso:
        return False
    try:
        last = datetime.fromisoformat(last_iso.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (now - last) < timedelta(minutes=_TYPE_PAIR_DEDUP_MIN)


def _build_portfolio_snapshot(snapshot: dict) -> PortfolioSnapshot:
    try:
        state_exposure = snapshot.get("exposure", {})
        free_margin = float(state_exposure.get("free_margin_pct", 100.0) or 100.0)
        net_btc = float(state_exposure.get("net_btc", 0.0) or 0.0)
        return PortfolioSnapshot(free_margin_pct=free_margin, net_btc=net_btc)
    except Exception:
        return PortfolioSnapshot()


async def setup_detector_loop(
    stop_event: asyncio.Event,
    *,
    storage: SetupStorage | None = None,
    send_fn: object = None,
    pairs: tuple[str, ...] = ("BTCUSDT",),
    interval_sec: float = _LOOP_INTERVAL_SEC,
    ict_parquet: str | Path | None = None,
) -> None:
    """5-minute async loop: build context → run detectors → write + notify."""
    store = storage or SetupStorage()
    ict_reader = ICTContextReader.load(ict_parquet or _DEFAULT_ICT_PARQUET)
    if ict_reader.is_loaded():
        logger.info("setup_detector_loop.ict_reader_ready")
    else:
        logger.warning("setup_detector_loop.ict_reader_empty — ICT context will be blank")

    tick_count = 0
    while not stop_event.is_set():
        now_utc = datetime.now(timezone.utc)
        for pair in pairs:
            ctx = _build_detection_context(pair)
            if ctx is None:
                continue
            # ict_reader is BTCUSDT-only (parquet built for BTC). Apply only
            # when pair matches; other symbols get an empty ICT context, which
            # is fine — detectors that need ICT short-circuit on missing data.
            if pair == "BTCUSDT":
                ctx.ict_context = ict_reader.lookup(now_utc)
            else:
                ctx.ict_context = {}
            _run_detectors_once(ctx, store, send_fn)

        # Heartbeat every 12 ticks (~1h at 5min interval). Lets the
        # daily KPI / status report detect a wedged loop.
        tick_count += 1
        if tick_count % 12 == 0:
            logger.info("setup_detector_loop.heartbeat tick=%d pairs=%s",
                         tick_count, list(pairs))
        # File-based heartbeat for stale_monitor — written every tick so the
        # monitor distinguishes "loop alive but emitting no setups" (quiet
        # market or runtime_disabled) from "loop wedged" (the 2026-05-07
        # incident class). setups.jsonl staleness alone is ambiguous.
        try:
            _hb = Path("state") / "setup_detector_heartbeat.json"
            _hb.parent.mkdir(parents=True, exist_ok=True)
            _hb.write_text(json.dumps({
                "last_tick_utc": now_utc.isoformat(timespec="seconds"),
                "tick_count": tick_count,
                "pairs": list(pairs),
            }), encoding="utf-8")
        except OSError:
            logger.exception("setup_detector_loop.heartbeat_write_failed")

        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            pass


def _run_detectors_once(
    ctx: DetectionContext,
    store: SetupStorage,
    send_fn: object,
) -> list[Setup]:
    """Run all detectors, apply combo filter, store and notify allowed setups."""
    candidates: list[Setup] = []
    ict_ctx = ctx.ict_context  # captured once per tick

    for detector in DETECTOR_REGISTRY:
        if is_detector_disabled(detector.__name__):
            metrics_record(stage_outcome="env_disabled",
                           drop_reason=detector.__name__)
            continue
        try:
            setup = detector(ctx)
            if setup is None:
                continue
            if setup.strength < _MIN_STRENGTH:
                logger.debug(
                    "setup_detector.below_threshold type=%s strength=%d",
                    setup.setup_type.value, setup.strength,
                )
                record_setup(setup, "below_strength",
                             drop_reason=f"strength={setup.strength}<{_MIN_STRENGTH}")
                continue
            # Attach ICT context to each setup (frozen dataclass → use replace)
            if ict_ctx:
                setup = dataclasses.replace(setup, ict_context=ict_ctx)
            candidates.append(setup)
        except Exception:
            logger.exception("setup_detector.detector_failed fn=%s", detector.__name__)
            metrics_record(stage_outcome="detector_failed",
                           drop_reason=detector.__name__)

    allowed, blocked = filter_setups(candidates)

    for s in blocked:
        _, reason = is_combo_allowed(s)
        logger.info(
            "setup_detector.combo_blocked type=%s regime=%s pair=%s",
            s.setup_type.value, s.regime_label, s.pair,
        )
        record_setup(s, "combo_blocked", drop_reason=reason)

    # ── Semantic dedup: skip setups whose signature was emitted within TTL.
    now_utc = datetime.now(timezone.utc)
    dedup = _load_semantic_dedup()
    # Prune entries older than TTL
    cutoff = now_utc - timedelta(minutes=_SETUP_DEDUP_TTL_MIN)
    dedup = {
        sig: ts for sig, ts in dedup.items()
        if (lambda t: t is not None and t >= cutoff)(
            _parse_iso_safe(ts)
        )
    }

    # Type+pair time-based dedup (belt-and-suspenders for label-drift leaks).
    type_pair_dedup = _load_type_pair_dedup()
    tp_cutoff = now_utc - timedelta(minutes=_TYPE_PAIR_DEDUP_MIN)
    type_pair_dedup = {
        k: ts for k, ts in type_pair_dedup.items()
        if (lambda t: t is not None and t >= tp_cutoff)(
            _parse_iso_safe(ts)
        )
    }

    # Query grid_coordinator once per cycle for GC-confirmation gating.
    gc_state = _query_grid_coordinator() if allowed else None
    now_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    new_setups: list[Setup] = []
    for setup in allowed:
        if _is_recently_emitted(setup, dedup, now_utc):
            logger.info(
                "setup_detector.semantic_dedup_skip type=%s sig=%s pair=%s",
                setup.setup_type.value, setup.semantic_signature, setup.pair,
            )
            record_setup(setup, "semantic_dedup_skip",
                         drop_reason=f"ttl={_SETUP_DEDUP_TTL_MIN}min")
            continue
        if _is_type_pair_recently_emitted(setup, type_pair_dedup, now_utc):
            logger.info(
                "setup_detector.type_pair_dedup_skip type=%s pair=%s ttl=%dmin",
                setup.setup_type.value, setup.pair, _TYPE_PAIR_DEDUP_MIN,
            )
            record_setup(setup, "type_pair_dedup_skip",
                         drop_reason=f"ttl={_TYPE_PAIR_DEDUP_MIN}min")
            continue

        # GC-confirmation: skip P-15 lifecycle (handled separately) and only
        # apply when GC state is available (else pass-through unchanged).
        if gc_state is not None and not setup.setup_type.value.startswith("p15_"):
            adjusted, decision = _apply_gc_confirmation(setup, gc_state, now_iso)
            # Shadow mode: audit recorded inside _apply_gc_confirmation, but we
            # do NOT apply hard-block or confidence adjustment to the setup.
            if _gc_shadow_mode():
                if adjusted is None:
                    logger.info(
                        "setup_detector.gc_shadow_would_block type=%s pair=%s reason=%s",
                        setup.setup_type.value, setup.pair, decision,
                    )
                else:
                    if decision != "neutral":
                        logger.info(
                            "setup_detector.gc_shadow_would_%s type=%s pair=%s "
                            "delta_conf=%.0f%%",
                            decision, setup.setup_type.value, setup.pair,
                            adjusted.confidence_pct - setup.confidence_pct,
                        )
                # Pass-through unchanged: setup stays as it was.
                record_setup(setup, "gc_shadow", extra={
                    "gc_upside": gc_state.get("upside_score", 0),
                    "gc_downside": gc_state.get("downside_score", 0),
                    "would_decision": decision,
                })
            elif adjusted is None:
                logger.info(
                    "setup_detector.gc_blocked type=%s pair=%s gc_up=%d gc_down=%d reason=%s",
                    setup.setup_type.value, setup.pair,
                    gc_state.get("upside_score", 0), gc_state.get("downside_score", 0),
                    decision,
                )
                record_setup(setup, "gc_blocked", drop_reason=decision, extra={
                    "gc_upside": gc_state.get("upside_score", 0),
                    "gc_downside": gc_state.get("downside_score", 0),
                })
                continue
            else:
                # Real (non-shadow) mode: adjusted is not None here.
                if decision != "neutral":
                    logger.info(
                        "setup_detector.gc_%s type=%s pair=%s conf %.0f%% -> %.0f%%",
                        decision, setup.setup_type.value, setup.pair,
                        setup.confidence_pct, adjusted.confidence_pct,
                    )
                # Record GC outcome for every passed-through setup
                # (boost / penalty / neutral).
                gc_stage = "gc_aligned" if decision == "aligned" else (
                    "gc_misaligned_penalty" if decision == "misaligned-penalty"
                    else "gc_neutral"
                )
                record_setup(adjusted, gc_stage, extra={
                    "gc_upside": gc_state.get("upside_score", 0),
                    "gc_downside": gc_state.get("downside_score", 0),
                    "before_confidence": round(setup.confidence_pct, 1),
                })
                setup = adjusted

        # MTF (15m/1h/4h) trend agreement modifier — never blocks.
        if not setup.setup_type.value.startswith("p15_"):
            mtf_adjusted, mtf_decision = _apply_mtf_check(setup, ctx)
            if mtf_decision in ("mtf-aligned", "mtf-conflict"):
                logger.info(
                    "setup_detector.%s type=%s pair=%s conf %.0f%% -> %.0f%%",
                    mtf_decision, setup.setup_type.value, setup.pair,
                    setup.confidence_pct, mtf_adjusted.confidence_pct,
                )
            mtf_stage = {
                "mtf-aligned": "mtf_aligned",
                "mtf-conflict": "mtf_conflict",
                "mtf-neutral": "mtf_neutral",
                "no-mtf": "mtf_neutral",
            }.get(mtf_decision, "mtf_neutral")
            record_setup(mtf_adjusted, mtf_stage, extra={
                "before_confidence": round(setup.confidence_pct, 1),
            })
            setup = mtf_adjusted

        # 2026-05-12: Confluence boost. If 2+ other detectors fired in same
        # direction within last 6h → bump confidence. Backtest shows K>=4
        # alignment gives PF 2-7 (rare, ~15 events/2y). K=2-3 still adds
        # signal quality.
        try:
            from services.setup_detector.confluence_score import (
                apply_boost, get_tracker,
            )
            tracker = get_tracker()
            side_for_conf = (
                "long" if "long" in setup.setup_type.value.lower() else "short"
            )
            # First record this setup so future setups in window see it...
            tracker.record(now_utc, setup.setup_type.value, side_for_conf)
            # ...then ask boost factor *excluding* ourselves.
            n_others = tracker.count_distinct(
                now_utc, side_for_conf,
                exclude_detector=setup.setup_type.value,
            )
            if n_others >= 2:
                boosted_conf = apply_boost(
                    now_utc, setup.confidence_pct, side_for_conf,
                    own_detector=setup.setup_type.value,
                )
                if boosted_conf > setup.confidence_pct:
                    logger.info(
                        "setup_detector.confluence_boost type=%s conf %.0f -> %.0f "
                        "(N_other=%d in 6h)",
                        setup.setup_type.value, setup.confidence_pct,
                        boosted_conf, n_others,
                    )
                    setup = dataclasses.replace(setup, confidence_pct=boosted_conf)
        except Exception:
            logger.exception("setup_detector.confluence_boost_failed")

        emit_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        dedup[setup.semantic_signature] = emit_iso
        type_pair_dedup[f"{setup.setup_type.value}|{setup.pair}"] = emit_iso
        store.write(setup)
        new_setups.append(setup)
        record_setup(setup, "emitted")
        logger.info(
            "setup_detector.new_setup type=%s pair=%s strength=%d confidence=%.0f%%",
            setup.setup_type.value, setup.pair, setup.strength, setup.confidence_pct,
        )
        if send_fn is not None:
            # If setup qualifies for propose-confirm flow, create a proposal
            # token + send a propose-card; otherwise send the regular setup card.
            try:
                from services.setup_detector.proposals import (
                    create_proposal, format_proposal_card, should_propose,
                )
                use_proposal = should_propose(setup)
            except Exception:
                logger.exception("setup_detector.propose_check_failed")
                use_proposal = False

            try:
                if use_proposal:
                    proposal = create_proposal(setup)
                    card = format_proposal_card(proposal)
                    logger.info(
                        "setup_detector.proposal_created token=%s type=%s conf=%.0f",
                        proposal.token, setup.setup_type.value, setup.confidence_pct,
                    )
                else:
                    card = format_telegram_card(setup)
                # Send via either signature.
                if callable(send_fn):
                    try:
                        send_fn(card, setup)  # type: ignore[call-arg]
                    except TypeError:
                        send_fn(card)  # type: ignore[operator]
            except Exception:
                logger.exception("setup_detector.send_failed type=%s", setup.setup_type.value)

            # P-15 paper-trader integration: auto-execute lifecycle events.
            if setup.setup_type.value.startswith("p15_"):
                try:
                    from services.paper_trader.p15_handler import handle_p15_setup
                    handle_p15_setup(setup)
                except Exception:
                    logger.exception("setup_detector.p15_paper_trader_failed")

    _save_semantic_dedup(dedup)
    _save_type_pair_dedup(type_pair_dedup)
    return new_setups


def _parse_iso_safe(s: str) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None
