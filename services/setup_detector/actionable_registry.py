"""Реестр входов, реально запушенных в личку как 🎯 ОТКРОЙ.

2026-06-21 Stage 3: intraday follow-up (✅TP / ❌отмена) должен пинговать ТОЛЬКО
по сделкам, что оператор реально видел. Трекер резолвит ВСЕ активные сетапы —
без реестра пинговал бы и те, что гейт не пускал = шум. _send пишет сюда при
пуше, трекер pop'ает при резолве (пинг один раз)."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "state" / "actionable_pushed.json"
TTL_SEC = 48 * 3600   # старше — выпиливаем (сетап уже истёк/протух)


def _load() -> dict:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(d: dict) -> None:
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        PATH.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except OSError:
        logger.exception("actionable_registry.save_failed")


def record_pushed(setup) -> None:
    now = time.time()
    d = {k: v for k, v in _load().items() if now - v.get("ts", 0) < TTL_SEC}
    d[setup.setup_id] = {
        "type": setup.setup_type.value,
        "pair": setup.pair,
        "entry": setup.entry_price,
        "dir": "SHORT" if setup.setup_type.value.startswith("short_") else "LONG",
        "ts": now,
    }
    _save(d)


def pop_if_pushed(setup_id: str) -> dict | None:
    """Вернуть запись и удалить (пинг один раз). None если вход не пушился."""
    d = _load()
    rec = d.pop(setup_id, None)
    if rec is not None:
        _save(d)
    return rec
