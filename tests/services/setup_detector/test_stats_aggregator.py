from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from services.setup_detector.models import SetupBasis, SetupStatus, SetupType, make_setup
from services.setup_detector.stats_aggregator import compute_setup_stats, format_stats_card
from services.setup_detector.storage import SetupStorage

# Use a recent, *relative* timestamp so fixtures always fall inside the
# lookback window (compute_setup_stats filters setups by detected_at). A
# hardcoded absolute date here is a time-bomb: once "now" advances past the
# lookback horizon the setups get filtered out and every aggregation reads 0.
_RECENT_DETECTED_AT = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


def _write_setups(path: Path, setups: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for s in setups:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")


def _write_outcomes(path: Path, outcomes: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for o in outcomes:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")


def _setup_dict(
    setup_id: str,
    setup_type: str = "long_dump_reversal",
    session: str = "NY_AM",
    regime: str = "consolidation",
    strength: int = 8,
    detected_at: str = _RECENT_DETECTED_AT,
) -> dict:
    return {
        "setup_id": setup_id,
        "setup_type": setup_type,
        "detected_at": detected_at,
        "pair": "BTCUSDT",
        "current_price": 80000.0,
        "regime_label": regime,
        "session_label": session,
        "entry_price": 79760.0,
        "stop_price": 79000.0,
        "tp1_price": 80520.0,
        "tp2_price": 81280.0,
        "risk_reward": 1.0,
        "strength": strength,
        "confidence_pct": 72.0,
        "basis": [{"label": "test", "value": 1.0, "weight": 1.0}],
        "cancel_conditions": ["cancel"],
        "window_minutes": 120,
        "expires_at": "2026-04-30T12:00:00+00:00",
        "status": "detected",
        "portfolio_impact_note": "test",
        "recommended_size_btc": 0.05,
    }


def _outcome_dict(setup_id: str, new_status: str, pnl: float = 38.0) -> dict:
    return {
        "setup_id": setup_id,
        "ts": "2026-04-30T11:00:00+00:00",
        "old_status": "entry_hit",
        "new_status": new_status,
        "close_price": 80520.0,
        "hypothetical_pnl_usd": pnl,
        "hypothetical_r": 1.0,
        "time_to_outcome_min": 60,
        "setup_type": "long_dump_reversal",
        "pair": "BTCUSDT",
        "regime_label": "consolidation",
        "session_label": "NY_AM",
        "strength": 8,
    }


def test_aggregation_by_type(tmp_path: Path) -> None:
    setups_path = tmp_path / "setups.jsonl"
    outcomes_path = tmp_path / "outcomes.jsonl"
    _write_setups(setups_path, [
        _setup_dict("s1", "long_dump_reversal"),
        _setup_dict("s2", "short_rally_fade"),
        _setup_dict("s3", "long_dump_reversal"),
    ])
    _write_outcomes(outcomes_path, [
        _outcome_dict("s1", "tp1_hit", pnl=38.0),
        _outcome_dict("s3", "stop_hit", pnl=-38.0),
    ])

    stats = compute_setup_stats(
        lookback_days=30,
        include_backtest=False,
        setups_path=setups_path,
        outcomes_path=outcomes_path,
    )
    assert "long_dump_reversal" in stats.by_type
    ldr = stats.by_type["long_dump_reversal"]
    assert ldr.detected == 2
    assert ldr.wins == 1


def test_aggregation_by_session(tmp_path: Path) -> None:
    setups_path = tmp_path / "setups.jsonl"
    outcomes_path = tmp_path / "outcomes.jsonl"
    _write_setups(setups_path, [
        _setup_dict("s1", session="NY_AM"),
        _setup_dict("s2", session="LONDON"),
        _setup_dict("s3", session="NY_AM"),
    ])
    _write_outcomes(outcomes_path, [_outcome_dict("s1", "tp1_hit")])

    stats = compute_setup_stats(
        lookback_days=30,
        include_backtest=False,
        setups_path=setups_path,
        outcomes_path=outcomes_path,
    )
    assert stats.by_session["NY_AM"].detected == 2
    assert stats.by_session["LONDON"].detected == 1


def test_hypothetical_pnl_calculation(tmp_path: Path) -> None:
    setups_path = tmp_path / "setups.jsonl"
    outcomes_path = tmp_path / "outcomes.jsonl"
    _write_setups(setups_path, [_setup_dict("s1"), _setup_dict("s2")])
    _write_outcomes(outcomes_path, [
        _outcome_dict("s1", "tp1_hit", pnl=50.0),
        _outcome_dict("s2", "stop_hit", pnl=-30.0),
    ])

    stats = compute_setup_stats(
        lookback_days=30,
        include_backtest=False,
        setups_path=setups_path,
        outcomes_path=outcomes_path,
    )
    assert stats.total_hypothetical_pnl_usd == pytest.approx(20.0, abs=0.01)


def test_strength_filter(tmp_path: Path) -> None:
    setups_path = tmp_path / "setups.jsonl"
    outcomes_path = tmp_path / "outcomes.jsonl"
    _write_setups(setups_path, [
        _setup_dict("s1", strength=6),
        _setup_dict("s2", strength=8),
    ])
    _write_outcomes(outcomes_path, [
        _outcome_dict("s1", "tp1_hit", pnl=30.0),
        _outcome_dict("s2", "tp1_hit", pnl=50.0),
    ])

    stats = compute_setup_stats(
        lookback_days=30,
        include_backtest=False,
        setups_path=setups_path,
        outcomes_path=outcomes_path,
    )
    # strength_7plus should only count s2
    assert stats.total_hypothetical_pnl_strength_7plus == pytest.approx(50.0, abs=0.01)
    assert stats.total_hypothetical_pnl_strength_8plus == pytest.approx(50.0, abs=0.01)


def test_format_stats_card(tmp_path: Path) -> None:
    setups_path = tmp_path / "setups.jsonl"
    outcomes_path = tmp_path / "outcomes.jsonl"
    _write_setups(setups_path, [_setup_dict("s1")])
    _write_outcomes(outcomes_path, [_outcome_dict("s1", "tp1_hit")])

    stats = compute_setup_stats(
        lookback_days=7,
        include_backtest=False,
        setups_path=setups_path,
        outcomes_path=outcomes_path,
    )
    card = format_stats_card(stats)
    assert "SETUP STATS" in card
    assert "BY TYPE:" in card
    assert "BY SESSION:" in card
    assert "BY REGIME:" in card
