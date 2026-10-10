"""Общий потолок счёта WEEX (10.10, «делай все»; идея из разбора GPT: «сетки по $4 000 на сторону дают
2.4× капитала, а с золотом и трендом — больше; бюджет нужен на весь счёт»).

Занято = себестоимость (объём × цена входа) всех ЖИВЫХ лотов всех сеток + позиций трендового бота.
Свободно = потолок − занято. Живые сетки и тренд получают «свободно» в конфиг прохода
(portfolio_free_usd) и не открывают вход больше него. Холостые режимы не ограничиваются (денег не
тратят). Проверка раз за проход: в одном проходе два входа могут взять одно и то же место — превышение
не больше одного ордера на сторону.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from services.weex_grid import engine as eg

logger = logging.getLogger(__name__)
CONFIG = eg.ROOT / "state" / "weex_portfolio_config.json"
DEFAULT = {"enabled": True, "gross_cap_usd": 12000.0}


def load() -> dict:
    if not CONFIG.exists():
        eg.atomic_write(CONFIG, json.dumps({"_note": "общий потолок всех живых сеток и тренда WEEX "
                                                     "(себестоимость позиций); /weex портфель 12000", **DEFAULT},
                                           ensure_ascii=False, indent=1))
        return dict(DEFAULT)
    try:
        return {**DEFAULT, **json.loads(CONFIG.read_text(encoding="utf-8"))}
    except (OSError, ValueError) as exc:
        raise eg.ConfigError(f"конфиг {CONFIG.name} не читается: {exc}") from exc


def _read(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        return {}


def used_usd(grid_states: list[Path], trend_states: list[Path]) -> float:
    total = 0.0
    for p in grid_states:
        st = _read(p)
        for side in ("LONG", "SHORT"):
            total += sum(float(l["qty"]) * float(l["entry"]) for l in (st.get(side) or {}).get("lots", []))
    for p in trend_states:
        ep = _read(p).get("episode") or {}
        if ep.get("qty"):
            total += float(ep["qty"]) * float(ep.get("entry_px") or ep.get("chand") or 0)
    return total


def free_usd(grid_states: list[Path], trend_states: list[Path]) -> tuple[float | None, float, float]:
    """(свободно или None если выключено, занято, потолок)."""
    cfg = load()
    used = used_usd(grid_states, trend_states)
    cap = float(cfg["gross_cap_usd"])
    return (cap - used if cfg.get("enabled", True) else None), used, cap
