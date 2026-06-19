from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from core.orchestrator.action_matrix import decide_category_action
from core.orchestrator.portfolio_state import PortfolioStore
from renderers.grid_renderer import render_action_alert


@dataclass
class CategoryChange:
    category_key: str
    from_action: str
    to_action: str
    reason_ru: str
    reason_en: str
    affected_bots: list[str]


@dataclass
class Alert:
    kind: str
    category_key: str | None
    text: str


@dataclass
class DispatchResult:
    changed: list[CategoryChange]
    unchanged: list[str]
    alerts: list[Alert]
    ts: datetime


def dispatch_orchestrator_decisions(store: PortfolioStore, regime_snapshot: dict[str, Any]) -> DispatchResult:
    from core.orchestrator.calibration_log import CalibrationLog
    from core.orchestrator.killswitch import KillswitchStore

    portfolio = store.get_snapshot()
    killswitch = KillswitchStore.instance()
    if killswitch.is_active():
        return DispatchResult(
            changed=[],
            unchanged=list(portfolio.categories.keys()),
            alerts=[],
            ts=datetime.now(timezone.utc),
        )

    regime = str(regime_snapshot.get("primary") or "RANGE")
    modifiers = list(regime_snapshot.get("modifiers") or [])
    cal_log = CalibrationLog.instance()
    prev_event = cal_log.get_last_event() or {}
    prev_regime = str(prev_event.get("regime") or "")
    regime_shifted = cal_log.maybe_log_regime_shift(regime, modifiers)

    changes: list[CategoryChange] = []
    unchanged: list[str] = []

    for cat_key, cat in portfolio.categories.items():
        if not cat.enabled:
            unchanged.append(cat_key)
            continue

        decision = decide_category_action(regime, modifiers, cat)
        if decision.action == cat.orchestrator_action:
            unchanged.append(cat_key)
            continue

        affected_bots = [
            bot.key
            for bot in store.get_bots_in_category(cat_key)
            if bot.state != "PAUSED_MANUAL"
        ]

        store.set_category_action(
            key=cat_key,
            action=decision.action,
            base_reason=decision.reason,
            modifiers=modifiers,
        )
        cal_log.log_action_change(
            category_key=cat_key,
            from_action=cat.orchestrator_action,
            to_action=decision.action,
            regime=regime,
            modifiers=modifiers,
            reason_ru=decision.reason,
            reason_en=decision.reason_en,
            affected_bots=affected_bots,
            triggered_by="AUTO",
        )

        changes.append(
            CategoryChange(
                category_key=cat_key,
                from_action=cat.orchestrator_action,
                to_action=decision.action,
                reason_ru=decision.reason,
                reason_en=decision.reason_en,
                affected_bots=affected_bots,
            )
        )

    metrics = regime_snapshot.get("metrics") if isinstance(regime_snapshot.get("metrics"), dict) else None
    alerts = _build_alerts(
        changes,
        regime,
        modifiers,
        metrics,
        regime_snapshot.get("bias_score"),
    )
    if regime_shifted:
        shift_alert = _build_regime_shift_alert(
            prev_regime or "UNKNOWN",
            regime,
            modifiers,
            metrics,
            num_action_changes=len(changes),
        )
        alerts.insert(0, shift_alert)
    return DispatchResult(changed=changes, unchanged=unchanged, alerts=alerts, ts=datetime.now(timezone.utc))


def _build_regime_shift_alert(
    from_regime: str,
    to_regime: str,
    modifiers: list[str],
    regime_metrics: dict[str, Any] | None,
    num_action_changes: int,
) -> Alert:
    """Standalone TG alert on regime flip — fires even when no category action changes."""
    from core.orchestrator.i18n_ru import REGIME_EMOJI, REGIME_RU, tr

    def _strip_primary(r: str) -> str:
        return r[len("PRIMARY_"):] if r.startswith("PRIMARY_") else r

    from_key = _strip_primary(from_regime)
    to_key = _strip_primary(to_regime)
    from_emoji = REGIME_EMOJI.get(from_key, "")
    to_emoji = REGIME_EMOJI.get(to_key, "")

    lines = [
        "🔀 ОРКЕСТРАТОР: СМЕНА РЕЖИМА",
        "",
        f"{from_emoji} {tr(from_key, REGIME_RU)}  →  {to_emoji} {tr(to_key, REGIME_RU)}",
    ]
    if modifiers:
        lines.append(f"Модификаторы: {', '.join(modifiers)}")
    metrics = dict(regime_metrics or {})
    atr_1h = metrics.get("atr_pct_1h")
    if isinstance(atr_1h, (int, float)):
        lines.append(f"ATR 1h: {atr_1h:.2f}%")
    if num_action_changes > 0:
        lines.append("")
        lines.append(f"⚙ Действия категорий: {num_action_changes} (см. карточки ниже)")
    else:
        lines.append("")
        lines.append("ℹ Без авто-действий по категориям — упреждающее уведомление.")

    if to_key in {"TREND_DOWN", "TREND_UP", "CASCADE_DOWN", "CASCADE_UP"} and isinstance(atr_1h, (int, float)) and atr_1h >= 1.5:
        lines.append("⚠ HIGH vol × directional regime — TB R3 может расширить сетку (×1.5).")

    return Alert(kind="REGIME_SHIFT", category_key=None, text="\n".join(lines))


def _build_alerts(
    changes: list[CategoryChange],
    regime: str,
    modifiers: list[str],
    regime_metrics: dict[str, Any] | None = None,
    bias_score: int | None = None,
) -> list[Alert]:
    alerts: list[Alert] = []
    metrics = dict(regime_metrics or {})
    if bias_score is not None and "bias_score" not in metrics:
        metrics["bias_score"] = bias_score

    for change in changes:
        # 2026-06-19 (оператор): холостой PAUSE/STOP без активных ботов — нечего
        # приостанавливать, карточка = чистый шум. Пропускаем (нет affected_bots).
        if change.to_action in {"STOP", "PAUSE"} and not getattr(change, "affected_bots", None):
            continue
        if change.to_action in {"STOP", "PAUSE"}:
            kind = "ACTION_REQUIRED"
        elif change.to_action in {"RUN", "RESET"}:
            kind = "REGIME_CHANGE"
        else:
            kind = "INFO"
        alerts.append(
            Alert(
                kind=kind,
                category_key=change.category_key,
                text=render_action_alert(change, regime, modifiers, metrics or None),
            )
        )
    return alerts
