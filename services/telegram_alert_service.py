from __future__ import annotations

import asyncio
from datetime import date
import logging

logger = logging.getLogger(__name__)
_MAX_MESSAGE_LEN = 3800


def _split_chunks(text: str, limit: int = _MAX_MESSAGE_LEN) -> list[str]:
    body = (text or "").strip()
    if not body:
        return []
    if len(body) <= limit:
        return [body]

    chunks: list[str] = []
    while body:
        if len(body) <= limit:
            chunks.append(body)
            break
        cut = body.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(body[:cut].rstrip())
        body = body[cut:].lstrip()
    return chunks


async def send_telegram_alert(text: str) -> None:
    """
    Send an orchestrator alert to Telegram when configured.
    Logging is always kept for audit/debugging.
    """
    logger.info("[ORCHESTRATOR ALERT]\n%s", text)

    from services.telegram_alert_client import TelegramAlertClient

    client = TelegramAlertClient.instance()
    if not client.is_enabled():
        return

    try:
        for chunk in _split_chunks(text):
            await asyncio.to_thread(client.send, chunk)
    except Exception as exc:
        logger.error("[ORCHESTRATOR ALERT] Delivery failed: %s", exc)


async def send_daily_report(day: date) -> None:
    """Суточный отчёт по СЧЁТУ.

    2026-08-28: раньше здесь строился отчёт из CalibrationLog оркестратора.
    Оператор показал его выдачу за 27.08 — «Всего событий: 2, ботов
    затронуто: 1, btc_short: REDUCE → RUN». В тот день по журналам служб
    было 726 записей, три закрытых ордера на +$13.42 и две остановки
    риск-контуром; ничего из этого в отчёт не попадало.

    Причины две. Оркестратор с 2 мая не выдал ни одной команды, а бот в
    нём — btc_short_l1, у которого вообще нет id GinArea (проверка
    tools/config_coverage.py показывает его как «команды уйдут в никуда»).
    Поэтому источником стали журналы служб, которые реально трогают деньги.
    """
    from services.reports.daily_account_report import (build_report,
                                                       is_empty_day)

    report_text = build_report(day)
    logger.info("[DAILY REPORT]\n%s", report_text)

    from services.telegram_alert_client import TelegramAlertClient

    client = TelegramAlertClient.instance()
    if not client.is_enabled():
        return

    # 2026-05-14: пустые отчёты засоряли канал. В авто-режиме шлём только
    # если за сутки была хоть одна запись; ручной вызов отдаёт всегда.
    if is_empty_day(day):
        logger.info("[DAILY REPORT] skipping send — empty day")
        return

    try:
        for chunk in _split_chunks(report_text):
            await asyncio.to_thread(client.send, chunk)
    except Exception as exc:
        logger.error("[DAILY REPORT] Delivery failed: %s", exc)
