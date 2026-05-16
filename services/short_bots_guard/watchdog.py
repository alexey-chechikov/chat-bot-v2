"""Watchdog loop: следит за cascade_short triggers и автоматически paus'ит
managed SHORT-ботов на N часов.

Logic:
1. Раз в минуту читает state/cascade_alert_dedup.json
2. Для каждого known trigger key (cascade_short_5.0, cascade_short_2.0):
   - Если ts свежий (< 5 мин назад) AND ещё не обработан → pause affected tiers
   - Пишем pause_until_ts в state/short_bots_auto_pause.json
3. Для каждого paused bot: если now > pause_until_ts → resume

Защита:
- Если bot был manually paused (наш audit не имеет 'paused' для этого bot) — НЕ resume автоматически
- Idempotent: повторный fire того же trigger в окне cooldown игнорируется
- TG-уведомление при каждой смене состояния (paused/resumed)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CASCADE_DEDUP = ROOT / "state" / "cascade_alert_dedup.json"
AUTO_PAUSE_PATH = ROOT / "state" / "short_bots_auto_pause.json"

TRIGGER_FRESHNESS_MIN = 5  # consider trigger fresh if fired within last 5 min
COOLDOWN_PER_TRIGGER_H = 6  # don't act on same trigger within this window


def _read_state() -> dict:
    if not AUTO_PAUSE_PATH.exists():
        return {}
    try:
        return json.loads(AUTO_PAUSE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(data: dict) -> None:
    try:
        AUTO_PAUSE_PATH.parent.mkdir(parents=True, exist_ok=True)
        AUTO_PAUSE_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        logger.exception("short_bots_guard.state_write_failed")


def _read_cascade_dedup() -> dict:
    if not CASCADE_DEDUP.exists():
        return {}
    try:
        return json.loads(CASCADE_DEDUP.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def evaluate_triggers(*, now: Optional[datetime] = None,
                       cascade_dedup_path: Path = CASCADE_DEDUP) -> list[dict]:
    """Возвращает список свежих triggers которые активны (fresh + not in cooldown).
    Каждый: {trigger, fire_ts, bots_to_affect[], pause_hours}"""
    from .config import load_config
    if now is None:
        now = datetime.now(timezone.utc)
    cfg = load_config()
    if not cfg.enabled:
        return []

    state = _read_state()
    triggers_state = state.get("triggers", {})
    dedup = _read_cascade_dedup()

    active = []
    for trigger_name, trigger in cfg.triggers.items():
        # cascade_short_5.0 → key in cascade_dedup is "short_5.0"
        key = trigger_name.replace("cascade_", "")
        ts_str = dedup.get(key)
        if not ts_str:
            continue
        try:
            fire_ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        age_min = (now - fire_ts).total_seconds() / 60.0
        if age_min > TRIGGER_FRESHNESS_MIN:
            continue
        # Check cooldown: don't re-act on same trigger ts
        last_acted = triggers_state.get(trigger_name, {}).get("last_fire_ts")
        if last_acted == fire_ts.isoformat(timespec="seconds"):
            continue
        # Match affected bots by tier
        bots_to_affect = [
            b for b in cfg.managed_bots if b.tier in trigger.affect_tiers
        ]
        active.append({
            "trigger": trigger_name,
            "fire_ts": fire_ts,
            "fire_ts_iso": fire_ts.isoformat(timespec="seconds"),
            "bots_to_affect": bots_to_affect,
            "pause_hours": trigger.pause_hours,
        })
    return active


def check_and_act(*, now: Optional[datetime] = None,
                   send_fn: Optional[Callable[[str], None]] = None,
                   cascade_dedup_path: Path = CASCADE_DEDUP) -> dict:
    """Один tick: проверить triggers, paus'нуть/resum'нуть боты.

    Returns dict with counts of actions taken.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    from .config import load_config
    from .control import pause_bot, resume_bot
    cfg = load_config()
    if not cfg.enabled:
        return {"enabled": False}

    state = _read_state()
    triggers_state = state.setdefault("triggers", {})
    paused_state = state.setdefault("paused", {})  # bot_id → {"until_ts": iso, "trigger": name}

    paused_count = 0
    resumed_count = 0
    skipped_count = 0

    # 1. Apply fresh triggers
    active = evaluate_triggers(now=now, cascade_dedup_path=cascade_dedup_path)
    for tr in active:
        until_ts = (tr["fire_ts"] + timedelta(hours=tr["pause_hours"])).isoformat(timespec="seconds")
        affected_aliases = []
        for bot in tr["bots_to_affect"]:
            rec = pause_bot(
                bot.bot_id,
                dry_run=cfg.dry_run,
                reason=f"auto_pause_until_{until_ts}",
                trigger=tr["trigger"],
            )
            if rec["action"] == "paused":
                paused_count += 1
                paused_state[bot.bot_id] = {
                    "until_ts": until_ts,
                    "trigger": tr["trigger"],
                    "alias": bot.alias,
                    "tier": bot.tier,
                }
                affected_aliases.append(bot.alias)
            elif rec["action"] == "noop_already":
                # already paused — extend pause window if new trigger more severe
                existing = paused_state.get(bot.bot_id, {})
                if existing.get("until_ts", "") < until_ts:
                    paused_state[bot.bot_id] = {
                        "until_ts": until_ts,
                        "trigger": tr["trigger"],
                        "alias": bot.alias,
                        "tier": bot.tier,
                    }
                skipped_count += 1
            else:
                skipped_count += 1
        triggers_state[tr["trigger"]] = {
            "last_fire_ts": tr["fire_ts_iso"],
            "last_action_ts": now.isoformat(timespec="seconds"),
            "affected": affected_aliases,
        }
        if send_fn and affected_aliases:
            try:
                send_fn(
                    f"⚠️ SHORT-BOTS AUTO-PAUSE\n"
                    f"Триггер: {tr['trigger']} ({tr['fire_ts'].strftime('%H:%M UTC')})\n"
                    f"Боты paused: {', '.join(affected_aliases)}\n"
                    f"До: {until_ts}\n"
                    f"Эджа из cascade backtest: 70% pct_up 4h после short-cascade → "
                    f"grid SHORT в риске."
                )
            except Exception:
                logger.exception("short_bots_guard.send_pause_failed")

    # 2. Resume expired pauses — но с проверкой safe-to-resume conditions
    from .resume_conditions import decide_resume_action
    bots_to_clear = []
    extended_count = 0
    bots_by_id = {b.bot_id: b for b in cfg.managed_bots}
    for bot_id, info in list(paused_state.items()):
        try:
            until = datetime.fromisoformat(info["until_ts"])
        except (ValueError, TypeError, KeyError):
            bots_to_clear.append(bot_id)
            continue
        if now < until:
            continue  # ещё не время

        # Determine side from managed bot config
        bot_meta = bots_by_id.get(bot_id)
        side = bot_meta.side if bot_meta else "short"

        action, new_until, reasons = decide_resume_action(info, side, now=now)
        if action == "extend_pause":
            # Не resume — рынок ещё adverse. Продлеваем + TG нудж.
            info["until_ts"] = new_until.isoformat(timespec="seconds")
            info["extends"] = info.get("extends", 0) + 1
            extended_count += 1
            if send_fn:
                try:
                    send_fn(
                        f"⏸ AUTO-PAUSE EXTENDED ({bot_meta.alias if bot_meta else bot_id}, side={side})\n"
                        f"Рынок ещё adverse — pause продлён до {new_until.strftime('%H:%M UTC')} (+{int((new_until-now).total_seconds()/60)}мин).\n"
                        + "\n".join(reasons)
                    )
                except Exception:
                    logger.exception("short_bots_guard.send_extend_failed")
            continue

        # Resume (either safe or max-cap hit)
        rec = resume_bot(
            bot_id,
            dry_run=cfg.dry_run,
            reason=f"auto_resume_{action}",
            trigger=info.get("trigger", "?"),
        )
        if rec["action"] == "resumed":
            resumed_count += 1
            if send_fn:
                try:
                    cap_note = " (MAX_PAUSE_HOURS hit)" if action == "resume_max_cap" else ""
                    send_fn(
                        f"✅ AUTO-RESUME{cap_note} ({bot_meta.alias if bot_meta else bot_id}, side={side})\n"
                        + "\n".join(reasons)
                    )
                except Exception:
                    logger.exception("short_bots_guard.send_resume_failed")
        bots_to_clear.append(bot_id)

    for bot_id in bots_to_clear:
        paused_state.pop(bot_id, None)

    _write_state(state)
    return {
        "enabled": True,
        "dry_run": cfg.dry_run,
        "active_triggers": len(active),
        "paused": paused_count,
        "resumed": resumed_count,
        "extended": extended_count,
        "skipped": skipped_count,
        "currently_paused_count": len(paused_state),
    }
