"""Decision Layer — MVP CORE-WIRE (шаг 1 из 7 по DECISION_LAYER_v1 §8).

Источник истины: docs/DESIGN/DECISION_LAYER_v1.md.

Ограничения этой версии:
  - Реализованы только семейства R-*, M-*, P-*, D-* (всего 14 правил).
  - T-* (MTF disagreement) — DISABLED в этом MVP, будет добавлено в
    TZ-DECISION-LAYER-MTF (шаг 3).
  - E-* (eligibility transitions) — DISABLED, будет в TZ-DECISION-LAYER-MTF.
  - НЕТ эмиссии Telegram (deferred к TZ-DECISION-LAYER-TELEGRAM, шаг 4).
  - Рейт-лимит cap применяется одинаково ко всем PRIMARY (включая M-4
    emergency) per design §2.7 буквально. Operator intent (chat 2026-05-06
    Q5) был "M-4 immune от cap" — задокументирован как DESIGN-OPERATOR-GAP-1,
    resolution в TZ-DECISION-LAYER-DESIGN-v1.1.
  - DESIGN-OPERATOR-GAP-2: M-* семейство dormant в production

    Status в этой версии: правила M-1, M-2, M-3, M-4 реализованы и
    тестируются юнит-тестами, но в live production они не срабатывают
    потому что upstream state (state/state_latest.json) не содержит
    поле margin_coefficient.

    Текущий fallback: при отсутствии margin_coefficient правила M-1..M-4
    остаются невычисленными (None-guard в evaluate()).

    Доступные альтернативные поля в state_latest.json:
      exposure.net_btc, exposure.shorts_btc, exposure.longs_btc
      exposure.nearest_short_liq.{price, distance_pct}
      exposure.nearest_long_liq.{price, distance_pct}
      bots[].live.unrealized_usd

    Distance to liquidation вычисляется из nearest_*_liq.distance_pct
    (минимум из short/long), что покрывает M-4 distance branch.
    Margin coefficient branch остаётся непокрытым.

    Resolution path: открыт TZ-MARGIN-COEFFICIENT-INPUT-WIRE для
    добавления computation margin_coefficient в upstream процесс.
    Этот gap — НЕ для TZ-DECISION-LAYER-CONFIG (config = только
    externalization порогов, не источник значений).
  - DESIGN-OPERATOR-GAP-3: dedup механизм не переиспользует existing dedup_layer

    Состояние: services/telegram/dedup_layer.py имеет (emitter, key, value)
    API с per-emitter value_delta_min — несовместимо с требуемой Decision
    Layer семантикой (rule_id, payload_signature).

    Текущая реализация: в этом модуле создан собственный _DedupState с
    persistence в state/decision_log/_dedup_state.json. Это работает
    автономно от telegram/dedup_layer.

    Mismatch consequence: при будущем wire'е TZ-DECISION-LAYER-TELEGRAM
    (шаг 4 цепочки §8) события Decision Layer проходят через alert_router,
    который, в свою очередь, может применить ещё один слой dedup из
    telegram/dedup_layer. Это может привести к двойному dedup'у одного
    события и потере алертов которые Decision Layer считал валидными
    к эмиссии.

    Resolution path: разрешается на шаге 4 цепочки в рамках
    TZ-DECISION-LAYER-TELEGRAM. Возможные подходы:
      - alert_router пропускает события Decision Layer без re-dedup'а
      - dedup_layer расширяется поддержкой (rule_id, payload_signature)
        семантики и Decision Layer мигрирует на shared registry
      - сохраняется текущая разделённая модель с явной координацией
        cooldown окон
  - M-* latency = длине цикла дашборда. Future enhancement = отдельный
    fast-path для margin emergency путей.
  - Audit log = single file state/decision_log/decisions.jsonl без ротации
    (rotation policy = TZ-DECISION-LAYER-AUDIT-LOG-ROTATION, шаг 5).
  - D-4 (margin_data_stale) добавлено в TZ-MARGIN-COEFFICIENT-INPUT-WIRE
    2026-05-06. Это EXTENSION над DECISION_LAYER_v1 §2.6 (там описаны
    только D-1..D-3). Включено в backlog TZ-DECISION-LAYER-V1.1-DIAGRAM-FIX
    одновременно с §1 path correction.

Авторитет классификатора:
  - R-* / M-* / P-* / E-* / D-* потребляют output Classifier A
    (core/orchestrator/regime_classifier.py, per CLASSIFIER_AUTHORITY_v1 §1).
    Live state пишется в state/regime_state.json через app_runner →
    core/pipeline.py каждые ~5 минут. Decision Layer читает его через
    services/dashboard/regime_adapter.adapt_regime_state(), который
    проецирует Classifier A 6-state taxonomy (RANGE/TREND_UP/TREND_DOWN/
    COMPRESSION/CASCADE_UP/CASCADE_DOWN) в Decision Layer 3-state
    (MARKUP/MARKDOWN/RANGE) и вычисляет regime_confidence/regime_stability
    из hysteresis_counter и regime_age_bars.
  - T-* (когда будут добавлены) потребляют Classifier C (phase_classifier.py).

  ВНИМАНИЕ: docs/DESIGN/DECISION_LAYER_v1.md §1 block diagram содержит
  outdated path reference — указывает "regime_classifier" без квалификации
  пути. Актуальная истина — CLASSIFIER_AUTHORITY_v1.md §1. Diagram fix
  отдельный TZ-DECISION-LAYER-V1.1-DIAGRAM-FIX (backlog, не блок для wire).
  services/regime_red_green/ — это Classifier B (training pipeline,
  retired per CLASSIFIER_AUTHORITY_v1 строка 180), НЕ source для R-*.

R-* алерты (когда будут эмиттиться через Telegram в шаге 4) включают
caveat: "MTF контекст не интегрирован — рекомендована проверка графика
вручную." M-* / P-* / D-* этого caveat не требуют (независимы от MTF).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

# ── Constants from DECISION_LAYER_v1 §3 + operator chat 2026-05-06 ──────────

CRITICAL_LEVELS_USD: list[float] = [78739.0, 80000.0, 82400.0, 96497.0]
# Narrowed from 300 to 120 (operator feedback 2026-05-09): 300 USD is 0.37%
# at $80k — too wide, fires whenever price wanders near round numbers.
# 120 USD (~0.15%) catches actual approach close enough to act on.
PRICE_PROXIMITY_USD: float = 120.0

REGIME_CONF_CONFIRMED: float = 0.80
REGIME_CONF_TRANSITION: float = 0.65
REGIME_STABILITY_OK: float = 0.80
# Lowered from 0.60 to 0.40 (operator feedback 2026-05-09): on flat market
# regime flip-flops between RANGE/COMPRESSION every few hours, stability
# routinely dips below 0.60 — that's normal flat behaviour, not a real
# instability event. 0.40 catches genuine break-down of the regime classifier.
REGIME_STABILITY_INSTABILITY: float = 0.40

HYSTERESIS_BARS_FULL: int = 12
HYSTERESIS_BARS_HALF: int = 6

MARGIN_SAFE_MAX: float = 0.60
MARGIN_ELEVATED_MAX: float = 0.85
MARGIN_CRITICAL_MIN: float = 0.85
MARGIN_EMERGENCY_MIN: float = 0.95
DIST_TO_LIQ_EMERGENCY_PCT: float = 5.0

POSITION_DELTA_BTC_MIN: float = 0.10
POSITION_DELTA_UNREALIZED_MIN: float = 500.0

COOLDOWN_PRIMARY_SEC: int = 1800
COOLDOWN_INFO_SEC: int = 3600
COOLDOWN_M4_SEC: int = 60  # operator chat 2026-05-06 Q4: emergency floor 60s

PRIMARY_HARD_CAP_24H: int = 50  # Raised 2026-05-08 from 20 — that limit was
                                # generating 5725 CAP-DIAG suppression events
                                # in 5879 total decisions (97% noise). 50 still
                                # caps runaway storms but lets meaningful
                                # PRIMARY events through.

TRACKER_STALE_MIN: float = 10.0
REGIME_STALE_HOURS: float = 2.0

# D-4 (margin data stale) — added in TZ-MARGIN-COEFFICIENT-INPUT-WIRE
# 2026-05-06. Extension over DECISION_LAYER_v1 §2.6 (which spans D-1..D-3
# only). Two tiers: INFO at 6-12h, PRIMARY at >12h. Flagged in module
# docstring; doc fix tracked in TZ-DECISION-LAYER-V1.1-DIAGRAM-FIX.
MARGIN_DATA_STALE_INFO_HOURS: float = 6.0
MARGIN_DATA_STALE_PRIMARY_HOURS: float = 12.0
MARGIN_SOURCE_DEAD_HOURS: float = 168.0

# ── Types ────────────────────────────────────────────────────────────────────

SEVERITY_PRIMARY = "PRIMARY"
SEVERITY_VERBOSE = "VERBOSE"
SEVERITY_INFO = "INFO"


@dataclass
class Event:
    """Single decision-layer event. See §2 for trigger spec, §4 for routing."""

    rule_id: str
    event_type: str
    severity: str
    payload: dict[str, Any]
    recommendation: str
    ts: str  # ISO8601 UTC
    payload_signature: str
    stale: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "event_type": self.event_type,
            "severity": self.severity,
            "payload": dict(self.payload),
            "recommendation": self.recommendation,
            "ts": self.ts,
            "payload_signature": self.payload_signature,
            "stale": self.stale,
        }


@dataclass
class DecisionInputs:
    """All inputs the decision layer needs.

    Caller (state_builder hook) is responsible for shaping this from real
    files. Fields that can't be derived are passed as None — affected rules
    short-circuit to no-event.
    """

    now: datetime

    # Regime (services/regime_red_green output, persisted to data/regime/switcher_state.json)
    regime_label: Optional[str] = None
    regime_confidence: Optional[float] = None
    regime_stability: Optional[float] = None
    bars_in_current_regime: Optional[int] = None
    candidate_regime: Optional[str] = None
    candidate_bars: Optional[int] = None
    prev_regime_label: Optional[str] = None  # what state-machine remembers as previous

    # Margin / position (computed by caller from state_latest.json)
    margin_coefficient: Optional[float] = None
    distance_to_liquidation_pct: Optional[float] = None
    position_btc: Optional[float] = None
    unrealized_pnl_usd: Optional[float] = None
    # Age of the margin data record in minutes (feeds D-4). None when no
    # margin data has ever been published.
    margin_data_age_min: Optional[float] = None

    # Price
    current_price: Optional[float] = None

    # Engine / freshness
    snapshots_age_min: Optional[float] = None
    regime_state_age_min: Optional[float] = None
    engine_bugs_detected: Optional[int] = None
    engine_bugs_fixed: Optional[int] = None
    engine_fix_eta: Optional[str] = None

    # MTF phase state (TZ-DECISION-LAYER-MTF, 2026-05-08).
    # Source: services/market_forward_analysis/phase_classifier.build_mtf_phase_state,
    # serialized to state/phase_state.json by market_forward_analysis_loop every 5 min.
    # Per MTF_FEASIBILITY_v1 §3 we adopt phase_classifier as the per-TF classifier.
    # Each entry: {"label": "MARKUP|MARKDOWN|RANGE|...", "direction_bias": int, "confidence": 0..100}.
    mtf_phases: Optional[dict[str, dict[str, Any]]] = None
    mtf_coherent: Optional[bool] = None

    # Stale flag — set if any upstream input is missing/stale
    inputs_stale: bool = False

    # Configurable critical levels (operator-overridable)
    critical_levels_usd: list[float] = field(default_factory=lambda: list(CRITICAL_LEVELS_USD))
    price_proximity_usd: float = PRICE_PROXIMITY_USD


@dataclass
class DecisionLayerResult:
    """Output of evaluate(): block for dashboard + raw events list."""

    events_emitted: list[Event]
    decision_layer_block: dict[str, Any]


# ── Persistence (cooldown, last-event cache, rolling cap) ───────────────────

DEFAULT_DEDUP_STATE_PATH = Path("state/decision_log/_dedup_state.json")
DEFAULT_AUDIT_LOG_PATH = Path("state/decision_log/decisions.jsonl")


@dataclass
class _RuleCache:
    """Per-rule_id state-machine memory."""

    last_severity: Optional[str] = None
    last_payload_signature: Optional[str] = None
    last_emit_ts: Optional[str] = None  # ISO8601


@dataclass
class _DedupState:
    """Persisted state across cycles: per-rule cache + recent PRIMARY emissions."""

    rules: dict[str, _RuleCache] = field(default_factory=dict)
    primary_emissions: list[str] = field(default_factory=list)  # ISO8601 timestamps
    recent_events: list[dict[str, Any]] = field(default_factory=list)  # last 5

    def to_dict(self) -> dict[str, Any]:
        return {
            "rules": {
                rid: {
                    "last_severity": rc.last_severity,
                    "last_payload_signature": rc.last_payload_signature,
                    "last_emit_ts": rc.last_emit_ts,
                }
                for rid, rc in self.rules.items()
            },
            "primary_emissions": list(self.primary_emissions),
            "recent_events": list(self.recent_events),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "_DedupState":
        rules_raw = raw.get("rules", {}) or {}
        rules: dict[str, _RuleCache] = {}
        for rid, rc in rules_raw.items():
            rules[rid] = _RuleCache(
                last_severity=rc.get("last_severity"),
                last_payload_signature=rc.get("last_payload_signature"),
                last_emit_ts=rc.get("last_emit_ts"),
            )
        return cls(
            rules=rules,
            primary_emissions=list(raw.get("primary_emissions", []) or []),
            recent_events=list(raw.get("recent_events", []) or []),
        )


def _load_dedup(path: Path) -> _DedupState:
    if not path.exists():
        return _DedupState()
    try:
        return _DedupState.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError):
        return _DedupState()


def _save_dedup(state: _DedupState, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _append_audit(event: Event, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")


# ── Helpers ─────────────────────────────────────────────────────────────────


def _isoformat(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _payload_signature(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:12]


_SEVERITY_ORDER = {"INFO": 0, "VERBOSE": 1, "PRIMARY": 2}


def _is_escalation(prev: Optional[str], cur: str) -> bool:
    if prev is None:
        return False
    return _SEVERITY_ORDER.get(cur, 0) > _SEVERITY_ORDER.get(prev, 0)


def _cooldown_for(rule_id: str, severity: str) -> int:
    if rule_id == "M-4":
        return COOLDOWN_M4_SEC
    if severity == SEVERITY_PRIMARY:
        return COOLDOWN_PRIMARY_SEC
    return COOLDOWN_INFO_SEC


# ── Rule implementations (14 total) ─────────────────────────────────────────
#
# Each rule is a pure function: (DecisionInputs) -> Optional[Event].
# Cooldown / dedup / cap are applied at the DecisionLayer level, not per-rule.


def _rule_R1(inp: DecisionInputs) -> Optional[Event]:
    """R-1 [§2.1]: regime_label unchanged AND conf>=0.80 AND stability>=0.80 → INFO."""
    if inp.regime_label is None or inp.regime_confidence is None or inp.regime_stability is None:
        return None
    if inp.prev_regime_label is not None and inp.prev_regime_label != inp.regime_label:
        return None
    if inp.regime_confidence < REGIME_CONF_CONFIRMED:
        return None
    if inp.regime_stability < REGIME_STABILITY_OK:
        return None
    payload = {
        "regime_label": inp.regime_label,
        "confidence": round(float(inp.regime_confidence), 2),
        "stability": round(float(inp.regime_stability), 2),
    }
    return Event(
        rule_id="R-1",
        event_type="regulation_status",
        severity=SEVERITY_INFO,
        payload=payload,
        recommendation="Activation matrix stable; admissible configs unchanged.",
        ts=_isoformat(inp.now),
        payload_signature=_payload_signature(payload),
        stale=inp.inputs_stale,
    )


def _rule_R2(inp: DecisionInputs) -> Optional[Event]:
    """R-2 [§2.1]: regime_label changes (persisted >=12 bars OR conf>=0.80 upgrade) → PRIMARY."""
    if inp.regime_label is None or inp.prev_regime_label is None:
        return None
    if inp.regime_label == inp.prev_regime_label:
        return None
    bars = inp.bars_in_current_regime or 0
    conf = inp.regime_confidence or 0.0
    if bars < HYSTERESIS_BARS_FULL and conf < REGIME_CONF_CONFIRMED:
        return None
    payload = {
        "old_regime": inp.prev_regime_label,
        "new_regime": inp.regime_label,
        "bars_persisted": bars,
        "confidence": round(float(conf), 2),
    }
    return Event(
        rule_id="R-2",
        event_type="regime_change",
        severity=SEVERITY_PRIMARY,
        payload=payload,
        recommendation=(
            f"Regime moved {inp.prev_regime_label}→{inp.regime_label}. "
            "Affected configs per REGULATION §3 mirror; review activation status."
        ),
        ts=_isoformat(inp.now),
        payload_signature=_payload_signature(payload),
        stale=inp.inputs_stale,
    )


def _rule_R3(inp: DecisionInputs) -> Optional[Event]:
    """R-3 [§2.1]: stability < 0.60 → PRIMARY (hysteresis-weakening)."""
    if inp.regime_stability is None:
        return None
    if inp.regime_stability >= REGIME_STABILITY_INSTABILITY:
        return None
    payload = {"stability": round(float(inp.regime_stability), 2)}
    return Event(
        rule_id="R-3",
        event_type="regime_instability",
        severity=SEVERITY_PRIMARY,
        payload=payload,
        recommendation=(
            f"Regime stability dropped to {inp.regime_stability:.2f}. "
            "Hysteresis weakening; expect potential transition."
        ),
        ts=_isoformat(inp.now),
        payload_signature=_payload_signature(payload),
        stale=inp.inputs_stale,
    )


def _rule_R4(inp: DecisionInputs) -> Optional[Event]:
    """R-4 [§2.1]: candidate_regime non-null AND candidate_bars >= 6 → VERBOSE."""
    if not inp.candidate_regime:
        return None
    bars = inp.candidate_bars or 0
    if bars < HYSTERESIS_BARS_HALF:
        return None
    payload = {
        "candidate_regime": inp.candidate_regime,
        "candidate_bars": bars,
        "hysteresis_full": HYSTERESIS_BARS_FULL,
    }
    return Event(
        rule_id="R-4",
        event_type="transition_pending",
        severity=SEVERITY_VERBOSE,
        payload=payload,
        recommendation=(
            f"Pending regime change to {inp.candidate_regime}; "
            f"{bars}/{HYSTERESIS_BARS_FULL} hysteresis bars accumulated."
        ),
        ts=_isoformat(inp.now),
        payload_signature=_payload_signature(payload),
        stale=inp.inputs_stale,
    )


def _rule_M1(inp: DecisionInputs) -> Optional[Event]:
    """M-1 [§2.2]: margin_coefficient < 0.60 → INFO (safe band)."""
    if inp.margin_coefficient is None:
        return None
    if inp.margin_coefficient >= MARGIN_SAFE_MAX:
        return None
    payload = {"margin_coefficient": round(float(inp.margin_coefficient), 4)}
    return Event(
        rule_id="M-1",
        event_type="margin_safe",
        severity=SEVERITY_INFO,
        payload=payload,
        recommendation="Margin headroom safe; activation gate G2 met.",
        ts=_isoformat(inp.now),
        payload_signature=_payload_signature(payload),
        stale=inp.inputs_stale,
    )


def _rule_M2(inp: DecisionInputs) -> Optional[Event]:
    """M-2 [§2.2]: margin_coefficient ∈ [0.60, 0.85) → PRIMARY (elevated)."""
    if inp.margin_coefficient is None:
        return None
    if not (MARGIN_SAFE_MAX <= inp.margin_coefficient < MARGIN_ELEVATED_MAX):
        return None
    payload = {"margin_coefficient": round(float(inp.margin_coefficient), 4)}
    return Event(
        rule_id="M-2",
        event_type="margin_elevated",
        severity=SEVERITY_PRIMARY,
        payload=payload,
        recommendation=(
            f"Margin coefficient elevated ({inp.margin_coefficient:.2f}). "
            "Reduce new-position activation; review existing exposure."
        ),
        ts=_isoformat(inp.now),
        payload_signature=_payload_signature(payload),
        stale=inp.inputs_stale,
    )


def _rule_M3(inp: DecisionInputs) -> Optional[Event]:
    """M-3 [§2.2]: margin_coefficient >= 0.85 → PRIMARY (critical).

    Bucketed signature (0.05 step) to prevent payload-drift CAP-DIAG spam.
    """
    if inp.margin_coefficient is None:
        return None
    if inp.margin_coefficient < MARGIN_CRITICAL_MIN:
        return None
    payload = {"margin_coefficient": round(float(inp.margin_coefficient) * 20) / 20}
    return Event(
        rule_id="M-3",
        event_type="margin_critical",
        severity=SEVERITY_PRIMARY,
        payload=payload,
        recommendation=(
            f"Margin coefficient CRITICAL ({inp.margin_coefficient:.2f}). "
            "HALT new activations. Review position cleanup options."
        ),
        ts=_isoformat(inp.now),
        payload_signature=_payload_signature(payload),
        stale=inp.inputs_stale,
    )


def _rule_M4(inp: DecisionInputs) -> Optional[Event]:
    """M-4 [§2.2]: margin_coefficient >= 0.95 OR distance_to_liquidation_pct < 5 → PRIMARY emergency.

    Payload uses BUCKETED values (not raw floats) to stabilize the signature
    across cycles. Without buckets, micro-drift in coef (0.9712 → 0.9714)
    changes the signature every cycle, bypasses cooldown, and spams CAP-DIAG
    (live audit 2026-05-08: 3081 suppressions/24h, mostly M-4).
    """
    coef_trigger = inp.margin_coefficient is not None and inp.margin_coefficient >= MARGIN_EMERGENCY_MIN
    dist_trigger = (
        inp.distance_to_liquidation_pct is not None
        and inp.distance_to_liquidation_pct < DIST_TO_LIQ_EMERGENCY_PCT
    )
    if not (coef_trigger or dist_trigger):
        return None

    # Safety override (operator feedback 2026-05-09): if coef is high but
    # distance to liquidation is comfortable (>= 15%), downgrade from PRIMARY
    # emergency to no-fire. The coef can sit at 0.95-1.0 by design when running
    # cross-margin with multiple bots. The actual risk indicator is dist_to_liq.
    M4_SAFE_DIST_PCT = 15.0
    if (coef_trigger and not dist_trigger
            and inp.distance_to_liquidation_pct is not None
            and inp.distance_to_liquidation_pct >= M4_SAFE_DIST_PCT):
        return None
    # Bucket coef to 0.05 step (0.95, 1.00, 1.05) and dist to 1% step.
    coef_bucket = (
        round(float(inp.margin_coefficient) * 20) / 20
        if inp.margin_coefficient is not None else None
    )
    dist_bucket = (
        round(float(inp.distance_to_liquidation_pct))
        if inp.distance_to_liquidation_pct is not None else None
    )
    payload = {
        "margin_coefficient": coef_bucket,
        "distance_to_liquidation_pct": dist_bucket,
        "trigger": "margin" if coef_trigger else "distance_to_liq",
    }
    return Event(
        rule_id="M-4",
        event_type="margin_emergency",
        severity=SEVERITY_PRIMARY,
        payload=payload,
        recommendation=(
            f"Margin EMERGENCY (coef {inp.margin_coefficient if inp.margin_coefficient is not None else 'n/a'}, "
            f"dist_to_liq {inp.distance_to_liquidation_pct if inp.distance_to_liquidation_pct is not None else 'n/a'}%). "
            "Consider immediate position reduction. Reference: PLAYBOOK_MANUAL_LAUNCH_v1 §5 hard stops."
        ),
        ts=_isoformat(inp.now),
        payload_signature=_payload_signature(payload),
        stale=inp.inputs_stale,
    )


def _rule_M5(
    inp: DecisionInputs,
    prev_position_btc: Optional[float],
    prev_unrealized: Optional[float],
) -> Optional[Event]:
    """M-5 [§2.2]: |Δposition_btc|>=0.10 AND |Δunrealized|>500 → PRIMARY."""
    if inp.position_btc is None or inp.unrealized_pnl_usd is None:
        return None
    if prev_position_btc is None or prev_unrealized is None:
        return None
    delta_btc = float(inp.position_btc) - float(prev_position_btc)
    delta_unr = float(inp.unrealized_pnl_usd) - float(prev_unrealized)
    if abs(delta_btc) < POSITION_DELTA_BTC_MIN:
        return None
    if abs(delta_unr) < POSITION_DELTA_UNREALIZED_MIN:
        return None
    payload = {
        "delta_btc": round(delta_btc, 4),
        "delta_unrealized_usd": round(delta_unr, 0),
        "position_btc_now": round(float(inp.position_btc), 4),
        "unrealized_now": round(float(inp.unrealized_pnl_usd), 0),
    }
    return Event(
        rule_id="M-5",
        event_type="position_change",
        severity=SEVERITY_PRIMARY,
        payload=payload,
        recommendation=(
            f"Position changed by {delta_btc:+.4f} BTC (Δ unrealized {delta_unr:+.0f} USD). "
            "Review whether this matches your manual cleanup plan."
        ),
        ts=_isoformat(inp.now),
        payload_signature=_payload_signature(payload),
        stale=inp.inputs_stale,
    )


def _rule_P1(inp: DecisionInputs) -> list[Event]:
    """P-1 [§2.3]: |price - level| <= proximity → PRIMARY (one event per matched level)."""
    out: list[Event] = []
    if inp.current_price is None:
        return out
    for level in inp.critical_levels_usd:
        distance = abs(float(inp.current_price) - float(level))
        if distance <= inp.price_proximity_usd:
            payload = {
                "level": float(level),
                "current_price": round(float(inp.current_price), 2),
                "distance_usd": round(distance, 2),
            }
            out.append(Event(
                rule_id="P-1",
                event_type="price_near_level",
                severity=SEVERITY_PRIMARY,
                payload=payload,
                recommendation=(
                    f"Price approaching critical level {level:.0f} "
                    f"({distance:.0f} USD away). Review position-cleanup or activation plan."
                ),
                ts=_isoformat(inp.now),
                payload_signature=_payload_signature(payload),
                stale=inp.inputs_stale,
            ))
    return out


def _rule_P2(inp: DecisionInputs, prev_price: Optional[float]) -> list[Event]:
    """P-2 [§2.3]: price crosses a critical level (sign of (current - level) flips) → PRIMARY."""
    out: list[Event] = []
    if inp.current_price is None or prev_price is None:
        return out
    for level in inp.critical_levels_usd:
        prev_side = (float(prev_price) - float(level)) >= 0
        cur_side = (float(inp.current_price) - float(level)) >= 0
        if prev_side != cur_side:
            payload = {
                "level": float(level),
                "current_price": round(float(inp.current_price), 2),
                "prev_price": round(float(prev_price), 2),
            }
            out.append(Event(
                rule_id="P-2",
                event_type="price_crossed_level",
                severity=SEVERITY_PRIMARY,
                payload=payload,
                recommendation=(
                    f"Price crossed level {level:.0f} (now {inp.current_price:,.0f}). "
                    "Recheck position state and active bot configs."
                ),
                ts=_isoformat(inp.now),
                payload_signature=_payload_signature(payload),
                stale=inp.inputs_stale,
            ))
    return out


def _rule_D1(inp: DecisionInputs) -> Optional[Event]:
    """D-1 [§2.6]: snapshots.csv age > 10 min → PRIMARY."""
    if inp.snapshots_age_min is None:
        return None
    if inp.snapshots_age_min <= TRACKER_STALE_MIN:
        return None
    payload = {"age_min": round(float(inp.snapshots_age_min), 1)}
    return Event(
        rule_id="D-1",
        event_type="tracker_stale",
        severity=SEVERITY_PRIMARY,
        payload=payload,
        recommendation=f"Live tracker stale ({inp.snapshots_age_min:.0f} min). Trades may be missed.",
        ts=_isoformat(inp.now),
        payload_signature=_payload_signature(payload),
        stale=True,
    )


def _rule_D2(inp: DecisionInputs) -> Optional[Event]:
    """D-2 [§2.6]: regime_state age > 2h → PRIMARY."""
    if inp.regime_state_age_min is None:
        return None
    if inp.regime_state_age_min <= REGIME_STALE_HOURS * 60.0:
        return None
    payload = {"age_min": round(float(inp.regime_state_age_min), 1)}
    return Event(
        rule_id="D-2",
        event_type="regime_stale",
        severity=SEVERITY_PRIMARY,
        payload=payload,
        recommendation=(
            f"Regime classifier output stale ({inp.regime_state_age_min:.0f} min). "
            "Activation decisions may be based on outdated label."
        ),
        ts=_isoformat(inp.now),
        payload_signature=_payload_signature(payload),
        stale=True,
    )


def _rule_D3(inp: DecisionInputs) -> Optional[Event]:
    """D-3 [§2.6]: engine_status.bugs_detected > bugs_fixed → INFO."""
    if inp.engine_bugs_detected is None or inp.engine_bugs_fixed is None:
        return None
    n = int(inp.engine_bugs_detected) - int(inp.engine_bugs_fixed)
    if n <= 0:
        return None
    payload = {
        "unresolved_bugs": n,
        "detected": int(inp.engine_bugs_detected),
        "fixed": int(inp.engine_bugs_fixed),
    }
    return Event(
        rule_id="D-3",
        event_type="engine_bugs",
        severity=SEVERITY_INFO,
        payload=payload,
        recommendation=(
            f"Engine has {n} unresolved bugs. {inp.engine_fix_eta or 'fix ETA pending'}."
        ),
        ts=_isoformat(inp.now),
        payload_signature=_payload_signature(payload),
        stale=inp.inputs_stale,
    )


def _rule_D4(inp: DecisionInputs) -> Optional[Event]:
    """D-4 [extension over §2.6]: margin data stale.

    Two tiers:
      6h < age <= 12h  → INFO  (dashboard hint to refresh /margin)
      age > 12h        → PRIMARY (M-* rules likely outdated)

    Added in TZ-MARGIN-COEFFICIENT-INPUT-WIRE 2026-05-06; not yet in
    DECISION_LAYER_v1.md §2.6. Tracked under TZ-DECISION-LAYER-V1.1-DIAGRAM-FIX.
    """
    if inp.margin_data_age_min is None:
        return None
    age_h = float(inp.margin_data_age_min) / 60.0
    if age_h <= MARGIN_DATA_STALE_INFO_HOURS:
        return None
    # 2026-10-02: старше недели — источник мёртв (BitMEX закрыт с 23.07),
    # а не «данные устарели». Вечный PRIMARY в /advise был шумом.
    if age_h > MARGIN_SOURCE_DEAD_HOURS:
        return None
    payload = {"age_hours": round(age_h, 1)}
    if age_h > MARGIN_DATA_STALE_PRIMARY_HOURS:
        return Event(
            rule_id="D-4",
            event_type="margin_data_stale",
            severity=SEVERITY_PRIMARY,
            payload=payload,
            recommendation=(
                f"🚨 Margin data {age_h:.1f}h stale. M-* rules likely outdated. "
                "Manual /margin update needed for accurate margin tracking."
            ),
            ts=_isoformat(inp.now),
            payload_signature=_payload_signature(payload),
            stale=True,
        )
    return Event(
        rule_id="D-4",
        event_type="margin_data_stale",
        severity=SEVERITY_INFO,
        payload=payload,
        recommendation=f"Margin data {age_h:.1f}h old. Provide /margin update.",
        ts=_isoformat(inp.now),
        payload_signature=_payload_signature(payload),
        stale=True,
    )


# ── T-* family: MTF disagreement (MTF_DISAGREEMENT_v1 §3) ────────────────────
#
# Activated 2026-05-08 in TZ-DECISION-LAYER-MTF. Source classifier:
# services/market_forward_analysis/phase_classifier.py (Classifier C, per
# MTF_FEASIBILITY_v1 §3 recommendation). Per-TF labels persisted to
# state/phase_state.json by market_forward_analysis_loop.
#
# Three rules:
#   T-1 (mtf_coherent)         INFO     — all TFs agree on direction
#   T-2 (mtf_minor_disagree)   VERBOSE  — LTF lags HTF (e.g. 15m flat in 1d uptrend)
#   T-3 (mtf_major_disagree)   PRIMARY  — HTF↔LTF opposite direction_bias
#
# Confidence floor 0.65 per design §3.1 (= 65 on phase_classifier's 0–100 scale).
# Cells below the floor are reported as `uncertain` and don't contribute.

T_CONFIDENCE_FLOOR: float = 65.0  # phase_classifier scale 0–100
T_HTF_PRIORITY: list[str] = ["1d", "4h"]
T_LTF_PRIORITY: list[str] = ["15m", "1h"]


def _eligible_phases(mtf_phases: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return only phases with confidence >= floor."""
    return {
        tf: p for tf, p in mtf_phases.items()
        if (p.get("confidence") or 0.0) >= T_CONFIDENCE_FLOOR
    }


def _pick_first(eligible: dict[str, dict[str, Any]], priority: list[str]) -> Optional[tuple[str, dict[str, Any]]]:
    for tf in priority:
        if tf in eligible:
            return tf, eligible[tf]
    return None


def _rule_T1(inp: DecisionInputs) -> Optional[Event]:
    """T-1: all eligible TFs agree on direction_bias (or flat) → INFO."""
    if not inp.mtf_phases:
        return None
    eligible = _eligible_phases(inp.mtf_phases)
    if len(eligible) < 2:
        return None
    biases = {p.get("direction_bias", 0) for p in eligible.values()}
    nonzero = {b for b in biases if b != 0}
    if len(nonzero) > 1:  # any opposite bias → not coherent
        return None
    if not nonzero:  # all flat — uninformative
        return None
    payload = {
        "direction": "bullish" if next(iter(nonzero)) > 0 else "bearish",
        "tfs": sorted(eligible.keys()),
        "labels": {tf: p.get("label") for tf, p in eligible.items()},
    }
    return Event(
        rule_id="T-1",
        event_type="mtf_coherent",
        severity=SEVERITY_INFO,
        payload=payload,
        recommendation=f"All TFs agree on {payload['direction']} bias; activation gate G3 met.",
        ts=_isoformat(inp.now),
        payload_signature=_payload_signature(payload),
        stale=inp.inputs_stale,
    )


def _rule_T2(inp: DecisionInputs) -> Optional[Event]:
    """T-2: LTF flat or RANGE while HTF directional → VERBOSE (minor)."""
    if not inp.mtf_phases:
        return None
    eligible = _eligible_phases(inp.mtf_phases)
    htf = _pick_first(eligible, T_HTF_PRIORITY)
    ltf = _pick_first(eligible, T_LTF_PRIORITY)
    if htf is None or ltf is None or htf[0] == ltf[0]:
        return None
    htf_tf, htf_p = htf
    ltf_tf, ltf_p = ltf
    htf_bias = htf_p.get("direction_bias", 0)
    ltf_bias = ltf_p.get("direction_bias", 0)
    # Minor: HTF directional, LTF flat (not opposite — that's T-3).
    if htf_bias == 0:
        return None
    if ltf_bias != 0:
        return None
    payload = {
        "htf": htf_tf, "htf_label": htf_p.get("label"),
        "ltf": ltf_tf, "ltf_label": ltf_p.get("label"),
        "htf_bias": htf_bias,
    }
    return Event(
        rule_id="T-2",
        event_type="mtf_minor_disagreement",
        severity=SEVERITY_VERBOSE,
        payload=payload,
        recommendation=(
            f"LTF {ltf_tf} flat inside {htf_tf} {htf_p.get('label')} — "
            "lag, not contradiction. Watch for confirmation."
        ),
        ts=_isoformat(inp.now),
        payload_signature=_payload_signature(payload),
        stale=inp.inputs_stale,
    )


def _rule_T3(inp: DecisionInputs) -> Optional[Event]:
    """T-3: HTF and LTF have opposite direction_bias → PRIMARY (major)."""
    if not inp.mtf_phases:
        return None
    eligible = _eligible_phases(inp.mtf_phases)
    htf = _pick_first(eligible, T_HTF_PRIORITY)
    ltf = _pick_first(eligible, T_LTF_PRIORITY)
    if htf is None or ltf is None or htf[0] == ltf[0]:
        return None
    htf_tf, htf_p = htf
    ltf_tf, ltf_p = ltf
    htf_bias = htf_p.get("direction_bias", 0)
    ltf_bias = ltf_p.get("direction_bias", 0)
    if htf_bias == 0 or ltf_bias == 0 or htf_bias == ltf_bias:
        return None
    payload = {
        "htf": htf_tf, "htf_label": htf_p.get("label"),
        "htf_confidence": round(float(htf_p.get("confidence") or 0.0), 1),
        "ltf": ltf_tf, "ltf_label": ltf_p.get("label"),
        "ltf_confidence": round(float(ltf_p.get("confidence") or 0.0), 1),
        "dim": "trend",
    }
    return Event(
        rule_id="T-3",
        event_type="mtf_major_disagreement",
        severity=SEVERITY_PRIMARY,
        payload=payload,
        recommendation=(
            f"MTF disagreement: {htf_tf} {htf_p.get('label')} vs "
            f"{ltf_tf} {ltf_p.get('label')} (opposite bias). "
            "Pause new activations until either TF resolves."
        ),
        ts=_isoformat(inp.now),
        payload_signature=_payload_signature(payload),
        stale=inp.inputs_stale,
    )


# Ordered list of rule_ids the layer runs. Rule callables are dispatched
# in DecisionLayer.evaluate() because some need extra args (M-5, P-2).
RULE_IDS: list[str] = [
    "R-1", "R-2", "R-3", "R-4",
    "M-1", "M-2", "M-3", "M-4", "M-5",
    "P-1", "P-2",
    "T-1", "T-2", "T-3",
    "D-1", "D-2", "D-3", "D-4",
]


# ── Engine ──────────────────────────────────────────────────────────────────


@dataclass
class _Memory:
    """Cross-cycle memory beyond cooldown — what was the previous price/position."""

    prev_price: Optional[float] = None
    prev_position_btc: Optional[float] = None
    prev_unrealized: Optional[float] = None
    prev_regime_label: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "prev_price": self.prev_price,
            "prev_position_btc": self.prev_position_btc,
            "prev_unrealized": self.prev_unrealized,
            "prev_regime_label": self.prev_regime_label,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "_Memory":
        return cls(
            prev_price=raw.get("prev_price"),
            prev_position_btc=raw.get("prev_position_btc"),
            prev_unrealized=raw.get("prev_unrealized"),
            prev_regime_label=raw.get("prev_regime_label"),
        )


_MEMORY_PATH_DEFAULT = Path("state/decision_log/_memory.json")


def _load_memory(path: Path) -> _Memory:
    if not path.exists():
        return _Memory()
    try:
        return _Memory.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError):
        return _Memory()


def _save_memory(mem: _Memory, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mem.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


class DecisionLayer:
    """Stateful evaluator with persisted dedup + memory."""

    def __init__(
        self,
        *,
        dedup_path: Path = DEFAULT_DEDUP_STATE_PATH,
        audit_log_path: Path = DEFAULT_AUDIT_LOG_PATH,
        memory_path: Path = _MEMORY_PATH_DEFAULT,
    ) -> None:
        self.dedup_path = dedup_path
        self.audit_log_path = audit_log_path
        self.memory_path = memory_path

    def evaluate(self, inp: DecisionInputs) -> DecisionLayerResult:
        dedup = _load_dedup(self.dedup_path)
        memory = _load_memory(self.memory_path)

        # Inject prev_regime_label from memory if caller didn't supply one
        if inp.prev_regime_label is None and memory.prev_regime_label is not None:
            inp.prev_regime_label = memory.prev_regime_label

        # Run all rules (some emit lists)
        candidate_events: list[Event] = []
        candidate_events.extend(filter(None, [_rule_R1(inp), _rule_R2(inp), _rule_R3(inp), _rule_R4(inp)]))
        candidate_events.extend(filter(None, [_rule_M1(inp), _rule_M2(inp), _rule_M3(inp), _rule_M4(inp)]))
        m5 = _rule_M5(inp, memory.prev_position_btc, memory.prev_unrealized)
        if m5 is not None:
            candidate_events.append(m5)
        candidate_events.extend(_rule_P1(inp))
        candidate_events.extend(_rule_P2(inp, memory.prev_price))
        candidate_events.extend(filter(None, [_rule_T1(inp), _rule_T2(inp), _rule_T3(inp)]))
        candidate_events.extend(filter(None, [_rule_D1(inp), _rule_D2(inp), _rule_D3(inp), _rule_D4(inp)]))

        # Dedup + cooldown + cap
        emitted: list[Event] = self._filter_and_emit(candidate_events, dedup, inp.now)

        # Update memory for next cycle
        memory.prev_price = inp.current_price if inp.current_price is not None else memory.prev_price
        memory.prev_position_btc = (
            inp.position_btc if inp.position_btc is not None else memory.prev_position_btc
        )
        memory.prev_unrealized = (
            inp.unrealized_pnl_usd if inp.unrealized_pnl_usd is not None else memory.prev_unrealized
        )
        memory.prev_regime_label = inp.regime_label or memory.prev_regime_label

        _save_dedup(dedup, self.dedup_path)
        _save_memory(memory, self.memory_path)

        block = self._build_block(dedup, emitted, inp.now)
        return DecisionLayerResult(events_emitted=emitted, decision_layer_block=block)

    def _filter_and_emit(
        self,
        candidates: list[Event],
        dedup: _DedupState,
        now: datetime,
    ) -> list[Event]:
        out: list[Event] = []
        # Prune primary_emissions to rolling 24h window
        cutoff = now - timedelta(hours=24)
        dedup.primary_emissions = [
            ts for ts in dedup.primary_emissions
            if _parse_iso(ts) is not None and _parse_iso(ts) >= cutoff  # type: ignore[operator]
        ]
        for ev in candidates:
            cache = dedup.rules.setdefault(ev.rule_id, _RuleCache())
            # State-change semantics §5: emit only on (a) first entry, (b) escalation,
            # (c) payload signature change.
            sig_changed = cache.last_payload_signature != ev.payload_signature
            sev_escalated = _is_escalation(cache.last_severity, ev.severity)
            first_entry = cache.last_severity is None
            if not (first_entry or sev_escalated or sig_changed):
                continue
            # Cooldown enforcement — applies when payload signature unchanged
            # (escalation / signature change bypass cooldown per §5 state-change semantics).
            if cache.last_emit_ts is not None and not (sev_escalated or sig_changed):
                last_dt = _parse_iso(cache.last_emit_ts)
                if last_dt is not None:
                    cd = _cooldown_for(ev.rule_id, ev.severity)
                    if (now - last_dt).total_seconds() < cd:
                        continue
            # Hard cap on PRIMARY (rolling 24h) — applies uniformly per design §2.7
            if ev.severity == SEVERITY_PRIMARY:
                if len(dedup.primary_emissions) >= PRIMARY_HARD_CAP_24H:
                    self._record_cap_diagnostic(ev, now)
                    continue
                dedup.primary_emissions.append(ev.ts)
            # Commit
            cache.last_severity = ev.severity
            cache.last_payload_signature = ev.payload_signature
            cache.last_emit_ts = ev.ts
            _append_audit(ev, self.audit_log_path)
            # Recent-events ring (last 5)
            dedup.recent_events.append(ev.to_dict())
            dedup.recent_events = dedup.recent_events[-5:]
            out.append(ev)
        return out

    def _record_cap_diagnostic(self, ev: Event, now: datetime) -> None:
        """Per §5: when 21st PRIMARY is suppressed, write INFO diagnostic to audit log only."""
        diag_payload = {
            "suppressed_rule_id": ev.rule_id,
            "suppressed_event_type": ev.event_type,
            "cap": PRIMARY_HARD_CAP_24H,
            "window_hours": 24,
        }
        diag = Event(
            rule_id="CAP-DIAG",
            event_type="alert_volume_exceeded",
            severity=SEVERITY_INFO,
            payload=diag_payload,
            recommendation=(
                f"PRIMARY hard cap ({PRIMARY_HARD_CAP_24H}/24h) reached. "
                f"Suppressed: {ev.rule_id}/{ev.event_type}. Telegram emission unaffected (this TZ has none)."
            ),
            ts=_isoformat(now),
            payload_signature=_payload_signature(diag_payload),
            stale=ev.stale,
        )
        _append_audit(diag, self.audit_log_path)

    def _build_block(
        self,
        dedup: _DedupState,
        emitted_now: list[Event],
        now: datetime,
    ) -> dict[str, Any]:
        # events_24h: filter recent_events by 24h window
        cutoff = now - timedelta(hours=24)
        events_24h: list[dict[str, Any]] = []
        for raw in dedup.recent_events:
            ts = _parse_iso(str(raw.get("ts", "")))
            if ts is not None and ts >= cutoff:
                events_24h.append(raw)
        by_rule: dict[str, int] = {}
        for raw in events_24h:
            rid = str(raw.get("rule_id", ""))
            by_rule[rid] = by_rule.get(rid, 0) + 1
        # active_severity = highest severity of events_emitted this cycle
        active = "NONE"
        for ev in emitted_now:
            if _SEVERITY_ORDER.get(ev.severity, 0) > _SEVERITY_ORDER.get(active, -1):
                active = ev.severity
        oldest = min(
            (ts for ts in dedup.primary_emissions if _parse_iso(ts) is not None),
            default=None,
        )
        return {
            "last_evaluated_at": _isoformat(now),
            "active_severity": active,
            "events_recent": list(dedup.recent_events),
            "events_24h_count": len(events_24h),
            "events_24h_by_rule": by_rule,
            "rate_limit_status": {
                "primary_used_24h": len(dedup.primary_emissions),
                "primary_cap": PRIMARY_HARD_CAP_24H,
                "window_oldest_event_at": oldest,
            },
        }


def _parse_iso(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None


def evaluate(
    inp: DecisionInputs,
    *,
    dedup_path: Path = DEFAULT_DEDUP_STATE_PATH,
    audit_log_path: Path = DEFAULT_AUDIT_LOG_PATH,
    memory_path: Path = _MEMORY_PATH_DEFAULT,
) -> DecisionLayerResult:
    """Functional entrypoint. See DecisionLayer.evaluate() for semantics."""
    layer = DecisionLayer(
        dedup_path=dedup_path,
        audit_log_path=audit_log_path,
        memory_path=memory_path,
    )
    return layer.evaluate(inp)
