"""Общий потолок счёта WEEX (10.10, «делай все»; идея из разбора GPT: «сетки по $4 000 на сторону дают
2.4× капитала, а с золотом и трендом — больше; бюджет нужен на весь счёт»).

Занято = себестоимость (объём × цена входа) всех ЖИВЫХ лотов всех сеток + позиций трендового бота.
Свободно = потолок − занято. Живые сетки и тренд получают «свободно» в конфиг прохода
(portfolio_free_usd) и не открывают вход больше него. Холостые режимы не ограничиваются (денег не
тратят). 11.10 (разбор GPT): «занято» включает всё, что ещё может исполниться на вход; свободное
считается заново перед каждой сеткой и каждой монетой тренда, а внутри прохода сетки новые входы
вычитаются из места сразу (одно место не раздаётся дважды); нечитаемый учёт — свободное 0.
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
    """Учёт стратегии. Нет файла — пусто; нечитаемый — ОШИБКА (11.10, разбор GPT: битый файл давал 0
    занятого и открывал место под новые входы; вызывающий при ошибке ставит свободное = 0)."""
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"учёт {p.name} не читается: {exc}") from exc


def _order_res(o: dict | None) -> float:
    """Ещё не исполненный остаток входного ордера (стоящего, сироты или неясной постановки), $."""
    if not o:
        return 0.0
    left = float(o.get("qty") or o.get("origQty") or 0) - float(o.get("filled") or o.get("executedQty") or 0)
    return max(left, 0.0) * float(o.get("price") or 0)


def used_usd(grid_states: list[Path], trend_states: list[Path]) -> float:
    """Занято = лоты + всё, что ещё может исполниться на вход: стоящие входы, неясные постановки входа,
    сироты-входы (11.10, разбор GPT: считались только лоты). Каждая сетка — свой файл учёта со СВОИМИ лотами: у сеток
    одного символа (BTC и B34/B49/B89, 15.10) общая позиция биржи делится по учётам без пересечений, поэтому сумма по
    файлам не считает лот дважды; ручная позиция оператора в потолок не входит."""
    total = 0.0
    for p in grid_states:
        st = _read(p)
        for side in ("LONG", "SHORT"):
            s = st.get(side) or {}
            total += sum(float(l["qty"]) * float(l["entry"]) for l in s.get("lots", []))
            total += _order_res(s.get("entry"))
            pend = s.get("pending")
            if pend and pend.get("kind") == "e":
                total += _order_res(pend)
            total += sum(_order_res(x) for x in s.get("strays", []) if x.get("kind") == "e")
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
