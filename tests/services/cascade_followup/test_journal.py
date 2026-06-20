"""Tests for cascade_followup.journal."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import services.cascade_followup.journal as journal_mod
from services.cascade_followup.journal import (
    append_signal,
    mark_user_action,
    parse_signal_id,
    pending_outcomes,
    read_all,
    summarize,
    update_record,
)
from services.cascade_followup.signal import build_signal


def _make_record(ts: datetime, variant: str = "short_5btc") -> dict:
    sig = build_signal(variant=variant, qty_btc=6.0, last_price=81500.0, now=ts)
    return {
        "signal_id": sig.signal_id,
        "ts_signal": sig.ts_signal,
        "variant": sig.variant,
        "liq_side": sig.liq_side,
        "threshold_btc": sig.threshold_btc,
        "qty_btc": sig.qty_btc,
        "last_price": sig.last_price,
        "trade_dir": sig.trade_dir,
        "entry": sig.entry,
        "tp1": sig.tp1,
        "tp2": sig.tp2,
        "stop": sig.stop,
        "size_usd": sig.size_usd,
        "size_btc": sig.size_btc,
        "predicted_4h_pct": sig.predicted_4h_pct,
        "edge_drift_flag": False,
        "by_exchange": {},
        "user_action": None,
        "placed_at": None,
        "decision_latency_sec": None,
        "outcome": None,
        "realized_4h_pct": None,
        "realized_12h_pct": None,
        "realized_at_ts": None,
        "exit_reason": None,
    }


def test_parse_signal_id() -> None:
    assert parse_signal_id("cf_20260519_184612_short_5btc") == "short_5btc"
    assert parse_signal_id("cf_20260519_184612_long_5btc_inverted") == "long_5btc_inverted"
    assert parse_signal_id("garbage") is None
    assert parse_signal_id("rh_20260519_184612") is None


def test_append_and_read_auto_route(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(journal_mod, "JOURNAL_DIR", tmp_path)
    ts = datetime(2026, 5, 19, 18, 46, 12, tzinfo=timezone.utc)
    rec = _make_record(ts)
    append_signal(rec)
    path = tmp_path / "cascade_followup_short_5btc.jsonl"
    assert path.exists()
    rows = read_all(path=path)
    assert len(rows) == 1
    assert rows[0]["signal_id"] == rec["signal_id"]


def test_mark_user_action_placed_sets_latency(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(journal_mod, "JOURNAL_DIR", tmp_path)
    ts = datetime(2026, 5, 19, 18, 46, 12, tzinfo=timezone.utc)
    rec = _make_record(ts)
    append_signal(rec)
    later = ts + timedelta(seconds=45)
    ok = mark_user_action(rec["signal_id"], "placed", now=later)
    assert ok
    rows = read_all(path=tmp_path / "cascade_followup_short_5btc.jsonl")
    assert rows[0]["user_action"] == "placed"
    assert rows[0]["decision_latency_sec"] == 45.0


def test_pending_outcomes_filter(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(journal_mod, "JOURNAL_DIR", tmp_path)
    ts = datetime(2026, 5, 19, 18, 46, 12, tzinfo=timezone.utc)
    r1 = _make_record(ts)
    r1["user_action"] = "placed"
    append_signal(r1)
    r2 = _make_record(ts + timedelta(minutes=5))
    r2["user_action"] = "placed"
    r2["realized_4h_pct"] = 0.31
    append_signal(r2)
    r3 = _make_record(ts + timedelta(minutes=10))
    r3["user_action"] = "skipped"
    append_signal(r3)
    path = tmp_path / "cascade_followup_short_5btc.jsonl"
    pending = pending_outcomes(path=path)
    assert len(pending) == 1
    assert pending[0]["signal_id"] == r1["signal_id"]


def test_update_record_routes_by_signal_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(journal_mod, "JOURNAL_DIR", tmp_path)
    ts = datetime(2026, 5, 19, 18, 46, 12, tzinfo=timezone.utc)
    rec = _make_record(ts)
    append_signal(rec)
    ok = update_record(rec["signal_id"], {"realized_4h_pct": 0.42, "outcome": "win"})
    assert ok
    rows = read_all(path=tmp_path / "cascade_followup_short_5btc.jsonl")
    assert rows[0]["realized_4h_pct"] == 0.42
    assert rows[0]["outcome"] == "win"


def test_summarize_basic(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(journal_mod, "JOURNAL_DIR", tmp_path)
    ts = datetime(2026, 5, 19, 18, 46, 12, tzinfo=timezone.utc)
    for i in range(5):
        r = _make_record(ts + timedelta(minutes=i * 5))
        r["user_action"] = "placed"
        if i < 3:
            r["realized_4h_pct"] = 0.45
        elif i == 3:
            r["realized_4h_pct"] = -0.30
        append_signal(r)
    path = tmp_path / "cascade_followup_short_5btc.jsonl"
    s = summarize(path=path, min_n=3)
    assert s["total"] == 5
    assert s["placed"] == 5
    assert s["closed"] == 4
    assert s["wr_4h_pct"] == 75.0
