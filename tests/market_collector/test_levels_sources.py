"""Tests for level-source tagging (round/border/swing) in get_levels.

2026-05-19: добавлено source-tag для каждого уровня чтобы LEVEL_BREAK alerts
могли фильтровать intraday swings vs major levels (round + bot borders).
"""
from __future__ import annotations

from pathlib import Path

import market_collector.levels as lvl_mod
from market_collector.levels import Levels, get_levels


def test_levels_dataclass_has_sources_field() -> None:
    L = Levels()
    assert L.sources == {}


def test_round_numbers_tagged_as_round(tmp_path: Path, monkeypatch) -> None:
    # Force OHLCV paths to empty (no swing data)
    monkeypatch.setattr(lvl_mod, "OHLCV_15M_CSV", tmp_path / "empty15.csv")
    monkeypatch.setattr(lvl_mod, "OHLCV_1H_CSV", tmp_path / "empty1h.csv")
    L = get_levels(current_price=76500.0)
    # 77000, 78000, 79000... above. 76000, 75000... below.
    assert 77000.0 in L.above
    assert 76000.0 in L.below
    assert "round" in L.sources.get(77000.0, [])
    assert "round" in L.sources.get(76000.0, [])


def test_bot_border_tagged_as_border(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(lvl_mod, "OHLCV_15M_CSV", tmp_path / "empty15.csv")
    monkeypatch.setattr(lvl_mod, "OHLCV_1H_CSV", tmp_path / "empty1h.csv")
    params_csv = tmp_path / "params.csv"
    params_csv.write_text(
        "ts_utc,bot_id,border_top,border_bottom\n"
        "2026-05-19T12:00:00+00:00,bot1,85000,75000\n",
        encoding="utf-8",
    )
    L = get_levels(current_price=80000.0, params_csv=params_csv)
    assert "border" in L.sources.get(85000.0, [])
    assert "border" in L.sources.get(75000.0, [])


def test_round_and_border_overlap_gets_both_tags(tmp_path: Path, monkeypatch) -> None:
    """Bot border at $75,000 — это и round, и border. Оба тэга должны быть."""
    monkeypatch.setattr(lvl_mod, "OHLCV_15M_CSV", tmp_path / "empty15.csv")
    monkeypatch.setattr(lvl_mod, "OHLCV_1H_CSV", tmp_path / "empty1h.csv")
    params_csv = tmp_path / "params.csv"
    params_csv.write_text(
        "ts_utc,bot_id,border_top,border_bottom\n"
        "2026-05-19T12:00:00+00:00,bot1,85000,75000\n",
        encoding="utf-8",
    )
    L = get_levels(current_price=80000.0, params_csv=params_csv)
    tags_85k = L.sources.get(85000.0, [])
    assert "round" in tags_85k
    assert "border" in tags_85k


def test_swing_only_levels_tagged_as_swing(tmp_path: Path, monkeypatch) -> None:
    """76433 — swing low, не round, не border → source ровно 'swing'."""
    # Build a tiny OHLCV with a clear swing low at 76433
    ohlcv = tmp_path / "ohlcv.csv"
    header = "ts_utc,open,high,low,close,volume"
    rows = [header]
    # Need >= 2*LEVEL_LOOKBACK+1 = 41 bars. Make bar #20 the swing low.
    for i in range(41):
        if i == 20:
            low = 76433.0
            high = 76500.0
        else:
            low = 76500.0 + i  # everything else higher
            high = 76600.0 + i
        rows.append(f"2026-05-19T{i:02d}:00:00+00:00,76500,{high},{low},76500,0")
    ohlcv.write_text("\n".join(rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(lvl_mod, "OHLCV_15M_CSV", ohlcv)
    monkeypatch.setattr(lvl_mod, "OHLCV_1H_CSV", tmp_path / "empty1h.csv")
    L = get_levels(current_price=76600.0)
    tags = L.sources.get(76433.0, [])
    assert tags == ["swing"], f"expected ['swing'] for pure swing low, got {tags}"
