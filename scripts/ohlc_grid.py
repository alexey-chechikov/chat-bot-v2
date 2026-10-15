"""Точная UTC-сетка минут для часовых баров frozen — один валидатор на производителя и на починку.

Ревью GPT 15.10 (docs/WEEX_GPT_REVIEW_AND_MANUAL_STRATEGIES_2026-10-15.md §1, P2): scripts/ohlcv_ingest.py
(_fill_1h_from_1m, каждый прогон gapfill) проверял только возраст часа — час из ОДНОЙ минуты записывался как OHLC, а
правильная проверка жила только в research/weex/repair_frozen_1m.py (_full_hours). Теперь оба импортируют её отсюда.

Час полный, только если в нём ровно 60 разных меток hour + k·60000, k = 0..59: без дублей, без меток вне сетки
(hour + 30 с и т. п.), и каждая минута — валидный OHLCV: конечные числа, 0 < low ≤ min(open, close),
high ≥ max(open, close), объём ≥ 0. Иначе часа нет: ни «из одной минуты», ни из 59, ни из 60 строк с дублем.
"""
from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable

MIN = 60_000
HOUR = 3_600_000
VOL_DIGITS = 8          # объём часа — сумма минут, округлённая до 8 знаков (производитель и починка пишут одно число)


def valid_bar(v) -> bool:
    """(open, high, low, close, volume) — конечные числа, 0 < low ≤ min(open, close), high ≥ max(open, close), объём ≥ 0."""
    try:
        o, h, l, c, vol = (float(x) for x in v)
    except (TypeError, ValueError):
        return False
    return (all(math.isfinite(x) for x in (o, h, l, c, vol))
            and 0 < l <= min(o, c) and h >= max(o, c) and vol >= 0)


def full_hours(rows: Iterable[tuple[int, tuple]], from_ms: int = 0) -> tuple[dict[int, list[tuple]], list[int]]:
    """rows — пары (ts_ms, (open, high, low, close, volume)) в любом порядке; учитываются ts ≥ from_ms.

    Возвращает ({час: 60 баров в порядке времени}, отвергнутые часы по возрастанию). Час, часть которого лежит до
    from_ms, получается неполным и отвергается."""
    by_hour: dict[int, dict[int, tuple]] = defaultdict(dict)
    dup: set[int] = set()
    for ts, v in rows:
        ts = int(ts)
        if ts < from_ms:
            continue
        h = ts // HOUR * HOUR
        if ts in by_hour[h]:
            dup.add(h)
        by_hour[h][ts] = tuple(v)
    full: dict[int, list[tuple]] = {}
    rejected: list[int] = []
    for h in sorted(by_hour):
        m = by_hour[h]
        grid = [h + k * MIN for k in range(60)]
        if h not in dup and len(m) == 60 and all(t in m for t in grid) and all(valid_bar(m[t]) for t in grid):
            full[h] = [m[t] for t in grid]
        else:
            rejected.append(h)
    return full, rejected


def hour_bar(bars: list[tuple]) -> tuple[float, float, float, float, float]:
    """OHLCV часа из его 60 минут (порядок времени): open первой, max high, min low, close последней, Σ объёма."""
    return (float(bars[0][0]), float(max(b[1] for b in bars)), float(min(b[2] for b in bars)), float(bars[-1][3]),
            round(float(sum(b[4] for b in bars)), VOL_DIGITS))
