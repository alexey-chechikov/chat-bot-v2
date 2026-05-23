"""Watchlist async loop — раз в 60 сек проверяет rules и шлёт alerts."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .rules import load_rules, save_rules, evaluate_rules
from .play_templates import format_play, PLAYS
from .play_journal import append_play_fire, evaluate_pending

logger = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 60
# Extended dedup: taker imbalance остаётся в extreme состоянии 30-90мин подряд,
# 30мин cooldown даёт 25+ fires/24h за rule = spam. 2h cooldown → ~12 fires/24h
# и каждый — отдельное событие. Edge не теряется, frequency адекватная.
DEDUP_COOLDOWN_SEC = 7200  # 2h between повторными alerts одного правила

# Direction-level cooldown: даже если rule.id разные (e5f6/eth/xrp все шлют
# taker_imbalance_short → BTC SHORT), TG не должен видеть 3 SHORT карты подряд.
# Cooldown по (trade_symbol, direction). Подавлённые fires пишутся в
# state/watchlist_suppressed.jsonl для аудита.
DIR_COOLDOWN_SEC = 1800  # 30мин на одно направление

# Label-level cooldown (2026-05-23): одна и та же play-label (например
# `taker_imbalance_short`) часто эмитится 3+ разными rule.id (eth00003 /
# xrp00003 / e5f6a7b8). Per-rule cooldown 2ч × 3 правила = 3 одинаковых
# карточки в TG за 2ч. LABEL-cooldown 2ч душит «один и тот же сетап»
# независимо от того, какое из правил его триггернуло — оставляет только
# первое срабатывание в каждом 2-часовом окне.
LABEL_COOLDOWN_SEC = 7200  # 2ч на одну play-label

ROOT = Path(__file__).resolve().parents[2]
DIR_COOLDOWN_PATH = ROOT / "state" / "watchlist_dir_cooldown.json"
LABEL_COOLDOWN_PATH = ROOT / "state" / "watchlist_label_cooldown.json"
SUPPRESSED_LOG_PATH = ROOT / "state" / "watchlist_suppressed.jsonl"


def _load_dir_cooldown() -> dict:
    try:
        if DIR_COOLDOWN_PATH.exists():
            return json.loads(DIR_COOLDOWN_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("watchlist.dir_cooldown_read_failed")
    return {}


def _save_dir_cooldown(d: dict) -> None:
    try:
        DIR_COOLDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
        DIR_COOLDOWN_PATH.write_text(json.dumps(d, indent=2), encoding="utf-8")
    except OSError:
        logger.exception("watchlist.dir_cooldown_write_failed")


def _load_label_cooldown() -> dict:
    try:
        if LABEL_COOLDOWN_PATH.exists():
            return json.loads(LABEL_COOLDOWN_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("watchlist.label_cooldown_read_failed")
    return {}


def _save_label_cooldown(d: dict) -> None:
    try:
        LABEL_COOLDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
        LABEL_COOLDOWN_PATH.write_text(json.dumps(d, indent=2), encoding="utf-8")
    except OSError:
        logger.exception("watchlist.label_cooldown_write_failed")


def _log_suppressed(rule_id: str, key: str, reason: str, now: datetime) -> None:
    try:
        SUPPRESSED_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": now.isoformat(timespec="seconds"),
            "rule_id": rule_id,
            "dir_key": key,
            "reason": reason,
        }
        with SUPPRESSED_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("watchlist.suppressed_log_failed")


async def watchlist_loop(stop_event: asyncio.Event, *, send_fn=None, interval_sec: int = POLL_INTERVAL_SEC) -> None:
    logger.info("watchlist.start interval=%ds", interval_sec)
    while not stop_event.is_set():
        try:
            rules = load_rules()
            fired = evaluate_rules(rules)
            if fired:
                now = datetime.now(timezone.utc)
                changed = False
                dir_cooldown = _load_dir_cooldown()
                dir_cooldown_dirty = False
                label_cooldown = _load_label_cooldown()
                label_cooldown_dirty = False
                for rule, value in fired:
                    # Dedup: не шлём чаще чем раз в 2ч одно и то же правило
                    if rule.last_fired:
                        try:
                            last = datetime.fromisoformat(rule.last_fired.replace("Z", "+00:00"))
                            if (now - last).total_seconds() < DEDUP_COOLDOWN_SEC:
                                continue
                        except ValueError:
                            pass

                    # Label-level cooldown: одна и та же play-label не чаще
                    # 2ч (см. LABEL_COOLDOWN_SEC). Душит мульти-rule-id спам
                    # для одного сетапа (eth00003+xrp00003+e5f6 → один и тот
                    # же taker_imbalance_short).
                    suppressed_label = False
                    if rule.label:
                        last_label_ts = label_cooldown.get(rule.label)
                        if last_label_ts:
                            try:
                                last_label = datetime.fromisoformat(last_label_ts.replace("Z", "+00:00"))
                                if (now - last_label).total_seconds() < LABEL_COOLDOWN_SEC:
                                    suppressed_label = True
                            except ValueError:
                                pass

                    # Direction-level cooldown: один SHORT-card / 30мин независимо
                    # от rule.id. Подавлённые fires всё равно идут в play_journal
                    # (для forward-test stats), но в TG не идут.
                    dir_key: str = ""
                    suppressed_dir = False
                    if rule.label and rule.label in PLAYS:
                        play_meta = PLAYS[rule.label]
                        trade_sym = play_meta.get("trade_symbol", "BTCUSDT")
                        direction = play_meta.get("dir", "")
                        if direction:
                            dir_key = f"{trade_sym}:{direction}"
                            last_dir_ts = dir_cooldown.get(dir_key)
                            if last_dir_ts:
                                try:
                                    last_dir = datetime.fromisoformat(last_dir_ts.replace("Z", "+00:00"))
                                    if (now - last_dir).total_seconds() < DIR_COOLDOWN_SEC:
                                        suppressed_dir = True
                                except ValueError:
                                    pass

                    text = (
                        f"🔔 WATCHLIST правило сработало\n"
                        f"  {rule.field} {rule.op} {rule.threshold}\n"
                        f"  Текущее значение: {value:.4f}\n"
                        f"  Rule ID: {rule.id}"
                    )
                    # If this rule is tagged with a known play label, enrich with trade plan
                    if rule.label:
                        try:
                            extra = format_play(rule.label, value,
                                                 rule_symbol=rule.symbol)
                            if extra:
                                text = text + "\n" + extra
                        except Exception:
                            logger.exception("watchlist.play_template_failed rule=%s", rule.id)
                    logger.info("watchlist.fired rule=%s value=%.4f label=%s dir_key=%s "
                                "supp_label=%s supp_dir=%s",
                                rule.id, value, rule.label, dir_key,
                                suppressed_label, suppressed_dir)
                    if suppressed_label:
                        _log_suppressed(rule.id, rule.label or "",
                                        f"label_cooldown_{LABEL_COOLDOWN_SEC//60}min", now)
                    elif suppressed_dir:
                        _log_suppressed(rule.id, dir_key, "dir_cooldown_30min", now)
                    elif send_fn:
                        try:
                            send_fn(text)
                        except Exception:
                            logger.exception("watchlist.send_failed")
                        if dir_key:
                            dir_cooldown[dir_key] = now.isoformat(timespec="seconds")
                            dir_cooldown_dirty = True
                        if rule.label:
                            label_cooldown[rule.label] = now.isoformat(timespec="seconds")
                            label_cooldown_dirty = True
                    # Forward-test journal: записываем каждый fire (включая
                    # подавлённые) с play_meta для последующей оценки 4h/24h
                    # forward returns. Edge-статистика не должна страдать от
                    # TG-cooldown'а.
                    if rule.label and rule.label in PLAYS:
                        try:
                            from .play_templates import _last_btc_price
                            price_now = _last_btc_price()
                            if price_now:
                                append_play_fire(
                                    label=rule.label, rule_id=rule.id,
                                    rule_field=rule.field, rule_op=rule.op,
                                    rule_threshold=rule.threshold, trigger_value=value,
                                    play_meta=PLAYS[rule.label],
                                    price_at_fire=price_now, now=now,
                                )
                        except Exception:
                            logger.exception("watchlist.play_journal_append_failed rule=%s", rule.id)
                    rule.last_fired = now.isoformat(timespec="seconds")
                    rule.fire_count += 1
                    changed = True
                if changed:
                    save_rules(rules)
                if dir_cooldown_dirty:
                    _save_dir_cooldown(dir_cooldown)
                if label_cooldown_dirty:
                    _save_label_cooldown(label_cooldown)
        except Exception:
            logger.exception("watchlist.tick_failed")

        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            pass

    logger.info("watchlist.stopped")


PLAY_OUTCOME_POLL_SEC = 1800  # раз в 30 мин достаточно


async def play_outcome_loop(stop_event: asyncio.Event, *, interval_sec: int = PLAY_OUTCOME_POLL_SEC) -> None:
    """Periodic evaluator: для каждой записи в play_journal с pending outcome
    смотрит цену 4h/24h после fire и заполняет realized_pct + hit flags."""
    logger.info("play_outcome.start interval=%ds", interval_sec)
    while not stop_event.is_set():
        try:
            n = evaluate_pending()
            if n > 0:
                logger.info("play_outcome.resolved n=%d", n)
        except Exception:
            logger.exception("play_outcome.tick_failed")
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            continue
    logger.info("play_outcome.stopped")


CONFLUENCE_POLL_SEC = 60


async def confluence_loop(stop_event: asyncio.Event, *, send_fn=None,
                            interval_sec: int = CONFLUENCE_POLL_SEC) -> None:
    """Раз в минуту проверяет если 2+ сигнала в одну сторону сошлись за
    последние 5 мин → шлёт high-conviction карточку с 2× size recommendation."""
    from services.watchlist.confluence import check_and_emit_confluence
    logger.info("confluence.start interval=%ds", interval_sec)
    while not stop_event.is_set():
        try:
            check_and_emit_confluence(send_fn=send_fn)
        except Exception:
            logger.exception("confluence.tick_failed")
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            continue
    logger.info("confluence.stopped")
