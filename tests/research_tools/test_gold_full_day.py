"""Ревью GPT 15.10 (docs/WEEX_GPT_REVIEW_AND_MANUAL_STRATEGIES_2026-10-15.md §2 п.7): research/gold/sweep_backtest.py
Market считал полноту дня по числу СТРОК — 1440 строк с дублем и пропуском (1439 разных минут) проходили как полный
день и давали уровень L следующего дня, порог дельты и профиль LVN. Полнота — число разных минутных меток UTC-сетки.
То же правило для 15m-свечи: 15 строк ровно на её минутах."""
from __future__ import annotations

import numpy as np

from tests.research_tools._util import load

sb = load("research/gold/sweep_backtest.py")
D = 20_300                                                   # 2025-07-31 UTC


def _day(day: int, price: float, minutes=None, extra_ts=()) -> dict:
    mins = list(range(1440)) if minutes is None else list(minutes)
    ts = np.array(sorted([day * sb.DAY + m * sb.MIN for m in mins] + list(extra_ts)), dtype=np.int64)
    n = len(ts)
    return {"ts": ts, **{k: np.full(n, price) for k in ("open", "high", "low", "close")}, "volume": np.ones(n)}


def _combine(*parts) -> dict:
    out = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
    order = np.argsort(out["ts"], kind="stable")
    return {k: v[order] for k, v in out.items()}


def _dup_and_missing(day: int, price: float, dup: int = 0, missing: int = 17, n: int = 1440) -> dict:
    mins = [m for m in range(n) if m != missing]
    return _day(day, price, mins, extra_ts=[day * sb.DAY + dup * sb.MIN])


def test_1440_rows_with_duplicate_and_missing_minute_is_not_a_full_day():
    bad = _dup_and_missing(D, 100.0)
    assert len(bad["ts"]) == 1440 and len(np.unique(bad["ts"])) == 1439
    a = _combine(_day(D - 1, 90.0), bad, _day(D + 1, 105.0, range(60)))
    m = sb.Market(a, "BTCUSDT_UM", False)
    assert D not in m.complete_days, "1440 строк / 1439 минут принято за полный день"
    assert D - 1 in m.complete_days
    assert m.level[D + 1] == 90.0, f"уровень взят из неполного дня: {m.level[D + 1]}"


def test_off_grid_stamp_does_not_count_as_a_minute():
    mins = [m for m in range(1440) if m != 17]
    bad = _day(D, 100.0, mins, extra_ts=[D * sb.DAY + 17 * sb.MIN + 30_000])   # 1440 строк, минута 17 вне сетки
    a = _combine(_day(D - 1, 90.0), bad, _day(D + 1, 105.0, range(60)))
    m = sb.Market(a, "BTCUSDT_UM", False)
    assert D not in m.complete_days and m.level[D + 1] == 90.0


def test_xau_coverage_counts_distinct_minutes():
    covered = _day(D, 100.0, range(720))
    short = _dup_and_missing(D + 1, 110.0, dup=3, missing=400, n=720)          # 720 строк, 719 минут
    a = _combine(_day(D - 1, 90.0, range(720)), covered, short, _day(D + 2, 105.0, range(60)))
    m = sb.Market(a, "XAU", False)
    assert D in m.complete_days and D + 1 not in m.complete_days
    assert m.level[D + 2] == 100.0


def test_clean_day_is_still_complete():
    a = _combine(_day(D - 1, 90.0), _day(D, 100.0), _day(D + 1, 105.0, range(60)))
    m = sb.Market(a, "BTCUSDT_UM", False)
    assert m.complete_days == [D - 1, D] and m.level[D + 1] == 100.0


def test_15m_bar_with_duplicate_and_missing_minute_is_not_full():
    a = _combine(_day(D - 1, 90.0), _dup_and_missing(D, 100.0, dup=0, missing=7))   # свеча 00:00 — 15 строк, 14 минут
    m = sb.Market(a, "BTCUSDT_UM", False)
    first, second = D * sb.DAY // sb.BAR, D * sb.DAY // sb.BAR + 1
    assert first not in m.b_id.tolist(), "15 строк с дублем и пропуском приняты за полную 15m-свечу"
    assert second in m.b_id.tolist()
    assert len(m.b_id) == 96 + 95
