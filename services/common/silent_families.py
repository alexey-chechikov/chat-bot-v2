"""Какие семьи сигналов молчат в TG (копятся в журнал).

Оператор 2026-07-18 и 2026-07-22: в ленту попадает только то, что требует
ЕГО решения или сообщает о сделанном. Недоказанные направленные сигналы
(n < 30 или эдж не подтверждён) копятся молча — журналы всё равно пишутся,
и по ним считается живая статистика ([[project-edge-gate]]).

Конфиг: state/silent_families.json — {"muted": ["alt_decorr", ...]}.
Нет файла / битый → ничего не глушим (историческое поведение).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "state" / "silent_families.json"


def muted_families() -> set[str]:
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set()
    except Exception:
        logger.exception("silent_families.config_read_failed")
        return set()
    return set(cfg.get("muted") or [])


def tg_muted(family: str) -> bool:
    return family in muted_families()
