"""Tests for paper_signal_tracker journal + evaluator."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.paper_signal_tracker.journal import (
    pending_signals,
    read_all,
    record_paper_signal,
    update_outcome,
)
from services.paper_signal_tracker.evaluator import evaluate_one


def test_record_and_read(tmp_path: Path):
    p = tmp_path / "j.jsonl"
    sid = record_paper_signal(source="cascade_alert", side="LONG",
                                entry=80000.0, stop_pct=-0.5, tp_pct=0.75,
                                hold_h=4, context="long_liq_5btc", path=p)
    rows = read_all(path=p)
    assert len(rows) == 1
    r = rows[0]
    assert r["signal_id"] == sid
    assert r["source"] == "cascade_alert"
    assert r["side"] == "LONG"
    assert r["entry"] == 80000.0
    assert abs(r["stop"] - 79600.0) < 0.1
    assert abs(r["tp"] - 80600.0) < 0.1
    assert r["outcome"] is None


def test_short_signs_correctly(tmp_path: Path):
    p = tmp_path / "j.jsonl"
    record_paper_signal(source="spike_alert", side="SHORT",
                         entry=80000.0, stop_pct=-0.5, tp_pct=0.75,
                         hold_h=4, path=p)
    r = read_all(path=p)[0]
    # SHORT: stop = entry × (1 + (-1) × -0.5%) = entry × 1.005 (price up = SL)
    assert abs(r["stop"] - 80400.0) < 0.1
    # SHORT TP: entry × (1 + (-1) × 0.75%) = entry × 0.9925 (price down = profit)
    assert abs(r["tp"] - 79400.0) < 0.1


def test_pending_filter(tmp_path: Path):
    p = tmp_path / "j.jsonl"
    a = record_paper_signal(source="cascade_alert", side="LONG", entry=80000,
                             stop_pct=-0.5, tp_pct=0.75, hold_h=4, path=p)
    b = record_paper_signal(source="spike_alert", side="SHORT", entry=80000,
                             stop_pct=-0.5, tp_pct=0.75, hold_h=4, path=p)
    update_outcome(a, "tp_hit", datetime.now(timezone.utc),
                    80600.0, 75.0, path=p)
    pend = pending_signals(path=p)
    assert len(pend) == 1
    assert pend[0]["signal_id"] == b


def test_evaluate_tp_hit_long(tmp_path: Path):
    p = tmp_path / "j.jsonl"
    record_paper_signal(source="test", side="LONG", entry=80000,
                         stop_pct=-0.5, tp_pct=0.75, hold_h=4, path=p)
    rec = read_all(path=p)[0]
    sig_ts = datetime.fromisoformat(rec["ts_signal"])
    bars = [
        (sig_ts + timedelta(minutes=5), 80100, 79950, 80050),
        (sig_ts + timedelta(minutes=30), 80650, 80100, 80600),  # TP hit (80600)
        (sig_ts + timedelta(minutes=60), 80700, 80200, 80300),
    ]
    upd = evaluate_one(rec, bars, now=sig_ts + timedelta(hours=1))
    assert upd is not None
    assert upd["outcome"] == "tp_hit"
    assert upd["pnl_usd"] > 0


def test_evaluate_sl_hit_short(tmp_path: Path):
    p = tmp_path / "j.jsonl"
    record_paper_signal(source="test", side="SHORT", entry=80000,
                         stop_pct=-0.5, tp_pct=0.75, hold_h=4, path=p)
    rec = read_all(path=p)[0]
    sig_ts = datetime.fromisoformat(rec["ts_signal"])
    bars = [
        (sig_ts + timedelta(minutes=10), 80500, 80000, 80450),  # SL hit (80400)
    ]
    upd = evaluate_one(rec, bars, now=sig_ts + timedelta(hours=1))
    assert upd is not None
    assert upd["outcome"] == "sl_hit"
    assert upd["pnl_usd"] < 0


def test_evaluate_timeout(tmp_path: Path):
    p = tmp_path / "j.jsonl"
    record_paper_signal(source="test", side="LONG", entry=80000,
                         stop_pct=-0.5, tp_pct=0.75, hold_h=4, path=p)
    rec = read_all(path=p)[0]
    sig_ts = datetime.fromisoformat(rec["ts_signal"])
    bars = [(sig_ts + timedelta(minutes=i), 80100, 79950, 80050)
            for i in range(0, 240, 10)]
    upd = evaluate_one(rec, bars, now=sig_ts + timedelta(hours=4, minutes=5))
    assert upd is not None
    assert upd["outcome"] == "timeout"


def test_evaluate_still_pending(tmp_path: Path):
    p = tmp_path / "j.jsonl"
    record_paper_signal(source="test", side="LONG", entry=80000,
                         stop_pct=-0.5, tp_pct=0.75, hold_h=4, path=p)
    rec = read_all(path=p)[0]
    sig_ts = datetime.fromisoformat(rec["ts_signal"])
    bars = [(sig_ts + timedelta(minutes=5), 80100, 79950, 80050)]
    upd = evaluate_one(rec, bars, now=sig_ts + timedelta(minutes=10))
    assert upd is None
