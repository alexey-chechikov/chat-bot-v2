"""Выключатель отправки карточек «🎯 ОТКРОЙ» в Telegram.

Замер 10.09 по state/setup_outcomes.jsonl за 90 суток, 1 574 исхода:

    цель TP1      69   +$602.74
    стоп         186 −$1 200.59
    истекло      826
    ИТОГО              −$597.85

186 стопов против 69 целей — 2.7 к одному против, и это не полоса, а три
месяца. По типам: long_pdl_bounce 536 сигналов при 30 целях и 113 стопах
(в карточке рекламируется PF 1.63); grid_booster — 396 карточек и НОЛЬ
исходов вообще.

Поэтому отправка глушится. Но ТОЛЬКО отправка: детектор продолжает
работать, record_pushed продолжает вести учёт, журнал исходов продолжает
наполняться. Иначе мы потеряем ровно тот инструмент, которым и вынесли
этот приговор, и через месяц не сможем проверить, изменилось ли что-то.

Вернуть звук: actionable_to_telegram = true в state/setup_push_config.json.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "state" / "setup_push_config.json"


def actionable_push_enabled() -> bool:
    """Слать ли карточки входов в личку. По умолчанию — НЕТ.

    Умолчание намеренно закрытое: если конфиг потеряется или испортится,
    лента должна молчать, а не ожить сама по себе.
    """
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return bool(cfg.get("actionable_to_telegram", False))
