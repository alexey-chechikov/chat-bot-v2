from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
import json
from typing import Any

from utils.safe_io import atomic_append_line


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass
class CalibrationEvent:
    ts: datetime
    event_type: str
    regime: str
    modifiers: list[str]
    reason_ru: str
    triggered_by: str
    category_key: str | None = None
    from_action: str | None = None
    to_action: str | None = None
    reason_en: str | None = None
    affected_bots: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ts"] = self.ts.astimezone(timezone.utc).isoformat()
        data["modifiers"] = list(data.get("modifiers") or [])
        data["affected_bots"] = list(data.get("affected_bots") or [])
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


class CalibrationLog:
    _instance: "CalibrationLog | None" = None

    def __init__(self, base_path: Path | str = Path("state/calibration")) -> None:
        self._base_path = Path(base_path)
        self._base_path.mkdir(parents=True, exist_ok=True)

    @classmethod
    def instance(cls, base_path: Path | str | None = None) -> "CalibrationLog":
        if cls._instance is None:
            cls._instance = cls(base_path or Path("state/calibration"))
        return cls._instance

    def _get_log_path(self, day: date) -> Path:
        return self._base_path / f"{day.isoformat()}.jsonl"

    def log_event(self, event: CalibrationEvent) -> None:
        atomic_append_line(str(self._get_log_path(event.ts.date())), event.to_json())

    def log_action_change(
        self,
        category_key: str,
        from_action: str,
        to_action: str,
        regime: str,
        modifiers: list[str],
        reason_ru: str,
        reason_en: str | None,
        affected_bots: list[str],
        triggered_by: str = "AUTO",
    ) -> None:
        self.log_event(
            CalibrationEvent(
                ts=_utc_now(),
                event_type="ACTION_CHANGE",
                category_key=category_key,
                from_action=from_action,
                to_action=to_action,
                regime=str(regime or "RANGE"),
                modifiers=list(modifiers or []),
                reason_ru=str(reason_ru or ""),
                reason_en=reason_en,
                affected_bots=list(affected_bots or []),
                triggered_by=triggered_by,
            )
        )

    def log_regime_shift(
        self,
        from_regime: str,
        to_regime: str,
        modifiers: list[str],
        reason_ru: str,
    ) -> None:
        self.log_event(
            CalibrationEvent(
                ts=_utc_now(),
                event_type="REGIME_SHIFT",
                regime=str(to_regime or "RANGE"),
                modifiers=list(modifiers or []),
                reason_ru=f"Переход: {from_regime} → {to_regime}. {reason_ru}".strip(),
                reason_en="REGIME_SHIFT",
                triggered_by="AUTO",
            )
        )

    def log_killswitch_trigger(
        self,
        reason: str,
        reason_value: Any,
        regime: str,
        modifiers: list[str],
    ) -> None:
        self.log_event(
            CalibrationEvent(
                ts=_utc_now(),
                event_type="KILLSWITCH_TRIGGER",
                regime=str(regime or "RANGE"),
                modifiers=list(modifiers or []),
                reason_ru=f"Killswitch: {reason} ({reason_value})",
                reason_en=str(reason or ""),
                triggered_by="KILLSWITCH",
            )
        )

    def log_manual_command(
        self,
        command: str,
        category_key: str | None,
        action: str | None,
        regime: str,
        modifiers: list[str],
    ) -> None:
        self.log_event(
            CalibrationEvent(
                ts=_utc_now(),
                event_type="MANUAL_COMMAND",
                category_key=category_key,
                to_action=action,
                regime=str(regime or "RANGE"),
                modifiers=list(modifiers or []),
                reason_ru=f"Оператор: {command}",
                reason_en="MANUAL_COMMAND",
                triggered_by="MANUAL",
            )
        )

    def read_events(self, day: date) -> list[dict[str, Any]]:
        log_path = self._get_log_path(day)
        if not log_path.exists():
            return []
        events: list[dict[str, Any]] = []
        with open(log_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                events.append(payload)
        return events

    def get_last_event(self) -> dict[str, Any] | None:
        candidates = sorted(self._base_path.glob("*.jsonl"))
        for path in reversed(candidates):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in reversed(lines):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    return payload
        return None

    def maybe_log_regime_shift(
        self,
        to_regime: str,
        modifiers: list[str],
        reason_ru: str = "Смена режима зафиксирована оркестратором.",
    ) -> bool:
        last_event = self.get_last_event()
        previous_regime = str((last_event or {}).get("regime") or "")
        current_regime = str(to_regime or "RANGE")
        if previous_regime and previous_regime == current_regime:
            return False
        if not previous_regime:
            previous_regime = "UNKNOWN"
        self.log_regime_shift(previous_regime, current_regime, modifiers, reason_ru)
        return True

    def summarize_day(self, day: date) -> dict[str, Any]:
        events = self.read_events(day)
        summary: dict[str, Any] = {
            "day": day,
            "events": events,
            "total_events": len(events),
            "event_counts": {},
            "action_changes": [],
            "manual_commands": [],
            "killswitch_events": [],
            "regime_shifts": [],
            "categories_changed": set(),
            "bots_touched": set(),
            "latest_regime": None,
        }
        counts: dict[str, int] = {}
        for event in events:
            event_type = str(event.get("event_type") or "UNKNOWN")
            counts[event_type] = counts.get(event_type, 0) + 1
            regime = event.get("regime")
            if regime:
                summary["latest_regime"] = regime
            category_key = event.get("category_key")
            if category_key:
                summary["categories_changed"].add(category_key)
            affected_bots_raw = list(event.get("affected_bots") or [])
            for bot_key in affected_bots_raw:
                summary["bots_touched"].add(bot_key)
            # Fallback: ACTION_CHANGE без явного affected_bots — но category_key
            # вроде "btc_long" сам по себе бот в модели оператора. Иначе на
            # выходе "Ботов затронуто: 0" при наличии ACTION CHANGES — отчёт
            # сам себе противоречит.
            if event_type == "ACTION_CHANGE" and not affected_bots_raw and category_key:
                summary["bots_touched"].add(category_key)
            if event_type == "ACTION_CHANGE":
                summary["action_changes"].append(event)
            elif event_type == "MANUAL_COMMAND":
                summary["manual_commands"].append(event)
            elif event_type == "KILLSWITCH_TRIGGER":
                summary["killswitch_events"].append(event)
            elif event_type == "REGIME_SHIFT":
                summary["regime_shifts"].append(event)
        summary["event_counts"] = counts
        summary["categories_changed"] = sorted(summary["categories_changed"])
        summary["bots_touched"] = sorted(summary["bots_touched"])
        return summary
