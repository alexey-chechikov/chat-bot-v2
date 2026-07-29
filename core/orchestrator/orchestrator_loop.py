from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

from core.orchestrator.anti_flipflop import record_change, should_suppress
from core.orchestrator.command_dispatcher import dispatch_orchestrator_decisions
from core.orchestrator.killswitch_triggers import check_all_killswitch_triggers
from core.orchestrator.portfolio_state import PortfolioStore
from core.pipeline import build_full_snapshot
from services.telegram_alert_service import send_daily_report, send_telegram_alert

logger = logging.getLogger(__name__)


class OrchestratorLoop:
    """
    Background asyncio loop for the orchestrator MVP.
    It checks regime state, killswitch triggers, applies actions, and emits alerts.
    """

    _DAILY_REPORT_STATE_PATH = Path("state/orchestrator_last_daily_report.json")

    def __init__(self, config: dict[str, Any]):
        self.config = dict(config or {})
        self.interval_sec = int(self.config.get("ORCHESTRATOR_LOOP_INTERVAL_SEC", 300))
        self.daily_report_time = str(self.config.get("ORCHESTRATOR_DAILY_REPORT_TIME", "09:00"))
        self.enable_auto_alerts = bool(self.config.get("ORCHESTRATOR_ENABLE_AUTO_ALERTS", True))
        self._running = False
        self._last_daily_report_date: date | None = self._read_last_report_date()

    @classmethod
    def _read_last_report_date(cls) -> date | None:
        p = cls._DAILY_REPORT_STATE_PATH
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            d = data.get("date")
            if d:
                return date.fromisoformat(d)
        except (OSError, json.JSONDecodeError, ValueError):
            pass
        return None

    @classmethod
    def _write_last_report_date(cls, d: date) -> None:
        p = cls._DAILY_REPORT_STATE_PATH
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"date": d.isoformat()}), encoding="utf-8")
        except OSError:
            logger.exception("orchestrator.daily_report.state_write_failed")

    async def start(self) -> None:
        logger.info("[ORCHESTRATOR LOOP] Starting")
        self._running = True
        while self._running:
            try:
                await self._tick()
            except Exception:
                logger.exception("[ORCHESTRATOR LOOP] Tick failed")
            if not self._running:
                break
            await asyncio.sleep(self.interval_sec)

    def stop(self) -> None:
        logger.info("[ORCHESTRATOR LOOP] Stopping")
        self._running = False

    async def _tick(self) -> None:
        logger.debug("[ORCHESTRATOR LOOP] Tick")
        snapshot = build_full_snapshot(symbol="BTCUSDT")
        regime = snapshot.get("regime", {}) if isinstance(snapshot, dict) else {}

        check_all_killswitch_triggers(self.config)

        store = PortfolioStore.instance()
        result = dispatch_orchestrator_decisions(store, regime)

        if self.enable_auto_alerts:
            for change in list(result.changed or []):
                cat_key = getattr(change, "category_key", "?")
                suppress, elapsed = should_suppress(cat_key)
                if suppress:
                    logger.info(
                        "[ORCHESTRATOR] flip-flop suppressed cat=%s elapsed=%.0fs %s→%s",
                        cat_key, elapsed,
                        getattr(change, "from_action", "?"),
                        getattr(change, "to_action", "?"),
                    )
                    continue
                # 2026-07-29 (оператор: «в оба канала приходят разные и
                # одинаковые сообщения»): это сообщение ДУБЛИРОВАЛО карточку
                # действия из _build_alerts — на одну смену режима уходило 3
                # сообщения («ИЗМЕНЕНИЕ» + «СМЕНА РЕЖИМА» + карточка действия).
                # Карточка действия информативнее (в ней «ДЕЙСТВИЕ В GinArea»
                # и метрики), поэтому дубль убран. Изменение по-прежнему
                # фиксируется в record_change для истории.
                record_change(
                    cat_key,
                    getattr(change, "from_action", ""),
                    getattr(change, "to_action", ""),
                )
            for alert in list(result.alerts or []):
                await send_telegram_alert(str(alert.text))

        await self._maybe_send_daily_report()

    def _format_change_alert(self, change: Any, regime: dict[str, Any]) -> str:
        from core.orchestrator.i18n_ru import ACTION_RU, CATEGORY_RU, tr

        lines = [
            "🔄 ОРКЕСТРАТОР: ИЗМЕНЕНИЕ",
            "",
            f"Категория: {tr(change.category_key, CATEGORY_RU)}",
            f"Действие: {tr(change.from_action, ACTION_RU)} → {tr(change.to_action, ACTION_RU)}",
            f"Причина: {change.reason_ru}",
            "",
            f"Режим: {regime.get('primary', 'UNKNOWN')}",
        ]
        modifiers = list(regime.get("modifiers") or [])
        if modifiers:
            lines.append(f"Модификаторы: {', '.join(modifiers)}")
        affected_bots = list(getattr(change, "affected_bots", []) or [])
        if affected_bots:
            lines.extend(["", f"Боты: {', '.join(affected_bots)}"])
        return "\n".join(lines)

    async def _maybe_send_daily_report(self) -> None:
        now = datetime.now(timezone.utc)
        try:
            target_time = time.fromisoformat(self.daily_report_time)
        except Exception:
            logger.error("[ORCHESTRATOR LOOP] Invalid daily report time: %s", self.daily_report_time)
            return

        current_seconds = now.hour * 3600 + now.minute * 60 + now.second
        target_seconds = target_time.hour * 3600 + target_time.minute * 60 + target_time.second
        if abs(current_seconds - target_seconds) >= self.interval_sec:
            return

        today = now.date()
        if self._last_daily_report_date == today:
            return

        await send_daily_report(today)
        self._last_daily_report_date = today
        self._write_last_report_date(today)
