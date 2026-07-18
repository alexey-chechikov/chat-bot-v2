"""Политика доставки регулярных отчётов в TG.

Оператор 2026-07-18: «все отчёты — только по команде/кнопке, расписания
превращаются в спам». Пуши по расписанию выключены конфигом
state/report_delivery.json; сами отчёты доступны командами:
/card (4ч-карточка), /report_today, /report_week, /status, /kpi и т.д.

Касается ТОЛЬКО расписаний (daily/weekly/digest/morning-brief).
Событийные риск-пинги (alt_guard, EXIT-FAST, каскады, order_harvester)
этой политикой НЕ гейтятся — они не «по кругу».
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "state" / "report_delivery.json"


def scheduled_push_enabled() -> bool:
    """False → расписания молчат (отчёты только по команде).

    Нет файла / битый файл → True (историческое поведение), чтобы чужая
    среда без конфига не меняла семантику молча.
    """
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return True
    except Exception:
        logger.exception("push_policy.config_read_failed — считаю push включённым")
        return True
    return bool(cfg.get("scheduled_push", True))
