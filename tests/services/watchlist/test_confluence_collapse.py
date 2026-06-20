"""Tests for confluence multi-threshold cascade collapse (2026-05-19 fix).

Bug: cascade_alert_dedup имеет per-threshold ключи (short_2.0, short_5.0,
short_10.0_mega). Одна лавина пробивает несколько порогов одновременно →
конфлюэнс ошибочно считает это "2-3 независимыми источниками" и предлагает
2× size. Реально — один event.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.watchlist.confluence import (
    _recent_cascade_signals,
    detect_confluence,
)


def _write_dedup(tmp_path: Path, entries: dict[str, str]) -> Path:
    p = tmp_path / "cascade_alert_dedup.json"
    p.write_text(json.dumps(entries), encoding="utf-8")
    return p


def test_multi_threshold_short_cascade_collapses_to_one(tmp_path: Path) -> None:
    """short_2.0 + short_5.0 + short_10.0_mega в одном окне = 1 source, не 3."""
    now = datetime(2026, 5, 19, 14, 25, tzinfo=timezone.utc)
    base = now - timedelta(minutes=2)
    dedup = _write_dedup(tmp_path, {
        "short_2.0": (base - timedelta(seconds=65)).isoformat(),
        "short_5.0": base.isoformat(),
        "short_10.0_mega": base.isoformat(),
    })
    sources = _recent_cascade_signals(direction="LONG", now=now, dedup_path=dedup)
    assert len(sources) == 1, f"expected 1 collapsed source, got {len(sources)}"
    # Primary label должна быть самый жирный threshold
    assert "10.0_mega" in sources[0]["label"]
    assert sources[0].get("collapsed_count") == 3


def test_short_5_alone_returns_single_source(tmp_path: Path) -> None:
    now = datetime(2026, 5, 19, 14, 25, tzinfo=timezone.utc)
    dedup = _write_dedup(tmp_path, {
        "short_5.0": (now - timedelta(minutes=2)).isoformat(),
    })
    sources = _recent_cascade_signals(direction="LONG", now=now, dedup_path=dedup)
    assert len(sources) == 1
    assert "5.0" in sources[0]["label"]


def test_stale_cascade_outside_window_ignored(tmp_path: Path) -> None:
    now = datetime(2026, 5, 19, 14, 25, tzinfo=timezone.utc)
    dedup = _write_dedup(tmp_path, {
        "short_5.0": (now - timedelta(minutes=10)).isoformat(),  # older than 5min window
    })
    sources = _recent_cascade_signals(direction="LONG", now=now, dedup_path=dedup,
                                        window_min=5)
    assert sources == []


def test_long_cascade_for_short_direction(tmp_path: Path) -> None:
    """LONG cascade in 2026 = inverted SHORT direction. CASCADE_BEAR includes
    long_2/5/10. Multi-threshold long → collapses."""
    now = datetime(2026, 5, 19, 14, 25, tzinfo=timezone.utc)
    base = now - timedelta(minutes=1)
    dedup = _write_dedup(tmp_path, {
        "long_2.0": base.isoformat(),
        "long_5.0": base.isoformat(),
    })
    sources = _recent_cascade_signals(direction="SHORT", now=now, dedup_path=dedup)
    assert len(sources) == 1
    assert "long_" in sources[0]["label"]


def test_confluence_requires_diverse_sources(tmp_path: Path, monkeypatch) -> None:
    """detect_confluence: 2 cascade-thresholds (collapsed to 1) + 0 plays =
    1 source = не достигает min_sources=2. Confluence не должна сработать."""
    import services.watchlist.confluence as conf
    now = datetime(2026, 5, 19, 14, 25, tzinfo=timezone.utc)
    dedup_path = _write_dedup(tmp_path, {
        "short_2.0": (now - timedelta(seconds=120)).isoformat(),
        "short_5.0": (now - timedelta(seconds=60)).isoformat(),
        "short_10.0_mega": (now - timedelta(seconds=60)).isoformat(),
    })
    monkeypatch.setattr(conf, "CASCADE_DEDUP", dedup_path)
    # No play journal fires
    monkeypatch.setattr(conf, "PLAY_JOURNAL", tmp_path / "no_plays.jsonl")
    result = detect_confluence(direction="LONG", now=now)
    assert result is None, "single cascade event (3 thresholds) не должен быть confluence"
