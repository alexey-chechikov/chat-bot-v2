"""Auto-detected S/R levels: swing high/low, round numbers, bot borders."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from market_collector.config import (
    LEVEL_LOOKBACK, OHLCV_15M_CSV, OHLCV_1H_CSV, ROUND_STEP,
)


@dataclass
class Levels:
    above: list[float] = field(default_factory=list)
    below: list[float] = field(default_factory=list)
    current_price: float = 0.0
    # 2026-05-19: source-tag per level (swing|round|border). Один уровень может
    # совпадать из нескольких источников (например round 76000 = bot border).
    # Используется в triggers._check_level_break для фильтрации intraday swings
    # из TG-форварда.
    sources: dict[float, list[str]] = field(default_factory=dict)


def _read_highs_lows(path: Path) -> tuple[list[float], list[float]]:
    highs: list[float] = []
    lows: list[float] = []
    if not path.exists():
        return highs, lows
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                highs.append(float(row["high"]))
                lows.append(float(row["low"]))
            except (KeyError, ValueError):
                continue
    return highs, lows


def _swing_highs(highs: list[float], lookback: int) -> list[float]:
    result: list[float] = []
    n = len(highs)
    for i in range(lookback, n - lookback):
        window = highs[i - lookback:i] + highs[i + 1:i + lookback + 1]
        if highs[i] > max(window, default=0.0):
            result.append(round(highs[i], 0))
    return result


def _swing_lows(lows: list[float], lookback: int) -> list[float]:
    result: list[float] = []
    n = len(lows)
    for i in range(lookback, n - lookback):
        window = lows[i - lookback:i] + lows[i + 1:i + lookback + 1]
        if lows[i] < min(window, default=float("inf")):
            result.append(round(lows[i], 0))
    return result


def _round_levels(price: float, step: int = ROUND_STEP, count: int = 5) -> tuple[list[float], list[float]]:
    base = (price // step) * step
    above = [base + step * i for i in range(1, count + 1)]
    below = [base - step * i for i in range(0, count)]
    return above, below


def _read_bot_borders(params_csv: Path) -> list[float]:
    """Latest border_top/border_bottom per bot from params.csv."""
    if not params_csv.exists():
        return []
    bot_latest: dict[str, dict] = {}
    with params_csv.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            bot_id = row.get("bot_id", "")
            ts = row.get("ts_utc", "")
            if not bot_id:
                continue
            existing = bot_latest.get(bot_id)
            if existing is None or ts > existing.get("ts_utc", ""):
                bot_latest[bot_id] = dict(row)
    borders: list[float] = []
    for row in bot_latest.values():
        for col in ("border_top", "border_bottom"):
            try:
                v = float(row.get(col, "") or 0)
                if v > 0:
                    borders.append(round(v, 0))
            except ValueError:
                pass
    return borders


def get_levels(current_price: float, params_csv: Path | None = None, count: int = 5) -> Levels:
    sources_map: dict[float, set[str]] = {}

    def _tag(lvl: float, src: str) -> None:
        sources_map.setdefault(round(float(lvl), 0), set()).add(src)

    for path in (OHLCV_15M_CSV, OHLCV_1H_CSV):
        highs, lows = _read_highs_lows(path)
        for lvl in _swing_highs(highs, LEVEL_LOOKBACK):
            _tag(lvl, "swing")
        for lvl in _swing_lows(lows, LEVEL_LOOKBACK):
            _tag(lvl, "swing")

    round_above, round_below = _round_levels(current_price)
    for lvl in round_above + round_below:
        _tag(lvl, "round")

    if params_csv is not None:
        for lvl in _read_bot_borders(params_csv):
            _tag(lvl, "border")

    all_levels = set(sources_map.keys())
    above = sorted(l for l in all_levels if l > current_price)[:count]
    below = sorted((l for l in all_levels if l < current_price), reverse=True)[:count]
    sources = {lvl: sorted(srcs) for lvl, srcs in sources_map.items()}
    return Levels(above=above, below=below, current_price=current_price, sources=sources)
