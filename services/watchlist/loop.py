"""Watchlist async loop — раз в 60 сек проверяет rules и шлёт alerts."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from .rules import load_rules, save_rules, evaluate_rules
from .play_templates import format_play, PLAYS
from .play_journal import append_play_fire, evaluate_pending

logger = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 60
# Extended dedup: taker imbalance остаётся в extreme состоянии 30-90мин подряд,
# 30мин cooldown даёт 25+ fires/24h за rule = spam. 2h cooldown → ~12 fires/24h
# и каждый — отдельное событие. Edge не теряется, frequency адекватная.
DEDUP_COOLDOWN_SEC = 7200  # 2h between повторными alerts одного правила


async def watchlist_loop(stop_event: asyncio.Event, *, send_fn=None, interval_sec: int = POLL_INTERVAL_SEC) -> None:
    logger.info("watchlist.start interval=%ds", interval_sec)
    while not stop_event.is_set():
        try:
            rules = load_rules()
            fired = evaluate_rules(rules)
            if fired:
                now = datetime.now(timezone.utc)
                changed = False
                for rule, value in fired:
                    # Dedup: не шлём чаще чем раз в 30 мин
                    if rule.last_fired:
                        try:
                            last = datetime.fromisoformat(rule.last_fired.replace("Z", "+00:00"))
                            if (now - last).total_seconds() < DEDUP_COOLDOWN_SEC:
                                continue
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
                            extra = format_play(rule.label, value)
                            if extra:
                                text = text + "\n" + extra
                        except Exception:
                            logger.exception("watchlist.play_template_failed rule=%s", rule.id)
                    logger.info("watchlist.fired rule=%s value=%.4f", rule.id, value)
                    if send_fn:
                        try:
                            send_fn(text)
                        except Exception:
                            logger.exception("watchlist.send_failed")
                    # Forward-test journal: записываем каждый fire с play_meta для
                    # последующей оценки 4h/24h forward returns.
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
