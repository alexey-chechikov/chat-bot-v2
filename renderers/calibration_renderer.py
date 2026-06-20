from __future__ import annotations

from datetime import date
from typing import Any


def render_daily_report(summary: dict[str, Any]) -> str:
    day = summary.get("day")
    if isinstance(day, date):
        day_text = day.isoformat()
    else:
        day_text = str(day or "unknown")

    total_events = int(summary.get("total_events") or 0)
    if total_events == 0:
        return (
            "📘 DAILY REPORT\n\n"
            f"Дата: {day_text}\n"
            "Событий calibration log за этот день нет."
        )

    event_counts = dict(summary.get("event_counts") or {})
    action_changes = list(summary.get("action_changes") or [])
    manual_commands = list(summary.get("manual_commands") or [])
    killswitch_events = list(summary.get("killswitch_events") or [])
    regime_shifts = list(summary.get("regime_shifts") or [])
    categories_changed = list(summary.get("categories_changed") or [])
    bots_touched = list(summary.get("bots_touched") or [])
    latest_regime = summary.get("latest_regime") or "UNKNOWN"

    lines = [
        "📘 DAILY REPORT",
        "",
        f"Дата: {day_text}",
        f"Всего событий: {total_events}",
        f"Текущий режим: {latest_regime}",
        "",
        "СВОДКА",
        f"  ACTION_CHANGE: {event_counts.get('ACTION_CHANGE', 0)}",
        f"  REGIME_SHIFT: {event_counts.get('REGIME_SHIFT', 0)}",
        f"  KILLSWITCH_TRIGGER: {event_counts.get('KILLSWITCH_TRIGGER', 0)}",
        f"  MANUAL_COMMAND: {event_counts.get('MANUAL_COMMAND', 0)}",
        "",
        f"Категорий затронуто: {len(categories_changed)}",
        f"Ботов затронуто: {len(bots_touched)}",
    ]

    if regime_shifts:
        lines.extend(["", f"СМЕНЫ РЕЖИМА ({len(regime_shifts)})"])
        # Show all transitions: summary counter и список должны совпадать.
        # При 10+ переходах за день — оператору это сигнал о flapping регима.
        for event in regime_shifts:
            lines.append(f"  • {event.get('reason_ru')}")

    if action_changes:
        lines.extend(["", "ИЗМЕНЕНИЯ ACTION"])
        for event in action_changes[-5:]:
            lines.append(
                f"  • {event.get('category_key')}: {event.get('from_action')} → {event.get('to_action')} "
                f"({event.get('reason_ru')})"
            )

    if manual_commands:
        lines.extend(["", "РУЧНЫЕ КОМАНДЫ"])
        for event in manual_commands[-5:]:
            lines.append(f"  • {event.get('reason_ru')}")

    if killswitch_events:
        lines.extend(["", "KILLSWITCH"])
        for event in killswitch_events[-3:]:
            lines.append(f"  • {event.get('reason_ru')}")

    return "\n".join(lines)
