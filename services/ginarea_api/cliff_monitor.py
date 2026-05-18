"""Cliff monitor для SHORT-T2 ботов.

Контекст: в пачке #22 определили что SHORT-T2 имеет cliff между TP=200 и TP=220.
Рекомендованный TP=175 даёт +4 752$ при чистом exit. Но если рынок поменяется
(сильный bull-tail), и накопленный unrealized начнёт расти — это **ранний
индикатор приближения к cliff-режиму**, даже если TP=175.

Логика: для каждого SHORT-T2 бота (gs=0.03) проверяем unrealized_usd.
Если unrealized < CLIFF_WARNING_USD — TG-алерт «приближаемся к cliff-режиму».
Если unrealized < CLIFF_DANGER_USD — критический алерт «остановить бот».

Пороги:
- WARNING -$1500: первое предупреждение, оператор смотрит руками
- DANGER -$3000: половина пути до известного cliff −$6300, экстренная остановка

Идемпотентность: state-файл хранит per-bot уже сработавшие пороги,
чтобы не спамить.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

STATE_PATH = Path("state/short_t2_cliff_alerts.json")

CLIFF_WARNING_USD = -1_500.0
CLIFF_DANGER_USD = -3_000.0

# SHORT-T2 фильтр: gs=0.03, mult=1.3 (известный конфиг T2). Бот определяется
# по metadata в position-snapshot если есть, иначе через эвристику
# (alias содержит "T2" / "ШОРТ" + grid_step из конфига).
SHORT_T2_GS = 0.03


@dataclass
class CliffAlert:
    bot_id: str
    severity: str            # "warning" / "danger"
    unrealized_usd: float
    ts: str


def _read_state(path: Path = STATE_PATH) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(state: dict, path: Path = STATE_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        logger.exception("cliff_monitor.write_failed path=%s", path)


def _severity_for(unrealized: float) -> str | None:
    if unrealized <= CLIFF_DANGER_USD:
        return "danger"
    if unrealized <= CLIFF_WARNING_USD:
        return "warning"
    return None


def check_short_t2_bots(
    bots: list[dict],
    *,
    send_fn: Callable[[str], None] | None = None,
    state_path: Path = STATE_PATH,
) -> list[CliffAlert]:
    """Bots: list of dict with at least bot_id, alias, position_btc, unrealized_usd, grid_step (optional).

    Returns list of NEW alerts (idempotent — previously-warned bots silenced).
    """
    state = _read_state(state_path)
    new_alerts: list[CliffAlert] = []
    now = datetime.now(timezone.utc).isoformat()

    for b in bots:
        bot_id = str(b.get("bot_id", ""))
        if not bot_id:
            continue
        # фильтр на SHORT-T2: только short-bots (position < 0)
        pos = float(b.get("position_btc", 0.0))
        if pos >= 0:
            continue
        unreal = float(b.get("unrealized_usd", 0.0))
        sev = _severity_for(unreal)
        if sev is None:
            # Авто-сброс если bot вернулся в норму
            if bot_id in state:
                state.pop(bot_id, None)
            continue

        prev_sev = state.get(bot_id, {}).get("severity")
        # Notify only on severity escalation: None → warning → danger
        escalated = (
            prev_sev is None
            or (prev_sev == "warning" and sev == "danger")
        )
        if not escalated:
            continue

        msg = _format_alert(b, sev, unreal)
        if send_fn is not None:
            try:
                kb = _build_cliff_keyboard(bot_id)
                try:
                    send_fn(msg, reply_markup=kb)
                except TypeError:
                    send_fn(msg)
            except Exception:
                logger.exception("cliff_monitor.send_failed bot_id=%s", bot_id)
        state[bot_id] = {"severity": sev, "ts": now, "unrealized_usd": unreal}
        new_alerts.append(CliffAlert(bot_id=bot_id, severity=sev, unrealized_usd=unreal, ts=now))

    _write_state(state, state_path)
    return new_alerts


def check_short_bag_aggregate(
    bots: list[dict],
    *,
    send_fn: Callable[[str], None] | None = None,
    state_path: Path = STATE_PATH,
    bag_key: str = "short_bag",
) -> CliffAlert | None:
    """Aggregated alert когда **суммарный** unrealized всех SHORT-ботов
    превышает пороги.

    Мотивация (13.05): 4 SHORT-ботов × −$700 = −$2 800 суммарно. Каждый
    отдельный не достигает порога −$1 500 (per-bot), но bag в danger-зоне.

    Идемпотентность: state[bag_key] хранит последнюю отправленную severity.
    """
    state = _read_state(state_path)
    short_bots = [b for b in bots if float(b.get("position_btc", 0.0)) < 0]
    if not short_bots:
        if bag_key in state:
            state.pop(bag_key, None)
            _write_state(state, state_path)
        return None
    total_unreal = sum(float(b.get("unrealized_usd", 0.0)) for b in short_bots)
    sev = _severity_for(total_unreal)
    if sev is None:
        if bag_key in state:
            state.pop(bag_key, None)
            _write_state(state, state_path)
        return None
    prev_sev = state.get(bag_key, {}).get("severity")
    escalated = prev_sev is None or (prev_sev == "warning" and sev == "danger")
    if not escalated:
        return None
    now = datetime.now(timezone.utc).isoformat()
    msg = _format_bag_alert(short_bots, sev, total_unreal)
    if send_fn is not None:
        try:
            send_fn(msg)
        except Exception:
            logger.exception("cliff_monitor.bag_send_failed")
    state[bag_key] = {"severity": sev, "ts": now, "total_unrealized_usd": total_unreal}
    _write_state(state, state_path)
    return CliffAlert(bot_id=bag_key, severity=sev, unrealized_usd=total_unreal, ts=now)


def _format_bag_alert(bots: list[dict], severity: str, total_unreal: float) -> str:
    """Сводный alert по всем SHORT-ботам."""
    lines = []
    total_pos = sum(float(b.get("position_btc", 0.0)) for b in bots)
    n = len(bots)
    if severity == "danger":
        lines.append(f"🚨 SHORT-BAG CLIFF DANGER")
        lines.append(f"Суммарный unrealized: ${total_unreal:,.0f} (< ${CLIFF_DANGER_USD:,.0f})")
        lines.append(f"Σ position: {total_pos:.3f} BTC across {n} bots")
        lines.append("⚠️ Известный cliff-обвал SHORT-T2 на ~−$6 300. Уже половина пути.")
        lines.append("Рекомендация: рассмотреть закрытие части позиции вручную.")
    else:
        lines.append("⚠️ SHORT-bag cliff warning")
        lines.append(f"Суммарный unrealized: ${total_unreal:,.0f} (< ${CLIFF_WARNING_USD:,.0f})")
        lines.append(f"Σ position: {total_pos:.3f} BTC across {n} bots")
        lines.append("Известный cliff-обвал был −$6 300. Смотри руками.")
    return "\n".join(lines)


def _build_cliff_keyboard(bot_id: str):
    """Inline buttons [⛔ Pause bot] / [✓ Ack] для cliff alert.

    Pause кнопка вызывает GinArea pause_bot API (PUT /bots/{id}/stop).
    Ack просто скрывает кнопки — оператор разберётся вручную.
    """
    try:
        from telebot import types
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("⛔ Pause bot", callback_data=f"cliff:pause:{bot_id}"),
            types.InlineKeyboardButton("✓ Ack", callback_data=f"cliff:ack:{bot_id}"),
        )
        return kb
    except Exception:
        return None


def _format_alert(bot: dict, severity: str, unreal: float) -> str:
    bot_id = bot.get("bot_id", "?")
    alias = bot.get("alias", "")
    pos = bot.get("position_btc", 0.0)
    if severity == "danger":
        return (
            f"🚨 SHORT-T2 CLIFF DANGER\n"
            f"Бот: {alias or bot_id}\n"
            f"unrealized: ${unreal:,.0f} (< ${CLIFF_DANGER_USD:,.0f})\n"
            f"position: {pos:.3f} BTC\n"
            f"⚠️ Известный cliff на ~-$6 300. Половина пути.\n"
            f"Рекомендация: ОСТАНОВИТЬ бот, проверить рынок."
        )
    return (
        f"⚠️ SHORT-T2 cliff warning\n"
        f"Бот: {alias or bot_id}\n"
        f"unrealized: ${unreal:,.0f} (< ${CLIFF_WARNING_USD:,.0f})\n"
        f"position: {pos:.3f} BTC\n"
        f"Известный cliff-обвал на TP=220 был -$6 300.\n"
        f"Рекомендация: смотри руками. Если рынок в squeeze — сократить bag."
    )
