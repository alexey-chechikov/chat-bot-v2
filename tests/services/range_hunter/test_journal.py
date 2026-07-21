"""Tests for range_hunter.journal."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.range_hunter.journal import (
    JOURNAL_PATH,
    append_signal,
    journal_path_for,
    mark_user_action,
    parse_signal_id,
    pending_signals,
    read_all,
    signal_id_from_ts,
    summarize,
    update_record,
)


def _make_record(ts: datetime, signal_id: str | None = None) -> dict:
    return {
        "signal_id": signal_id or signal_id_from_ts(ts),
        "ts_signal": ts.isoformat(timespec="seconds"),
        "mid_signal": 81500.0,
        "buy_level": 81418.5,
        "sell_level": 81581.5,
        "stop_loss_pct": 0.20,
        "size_usd": 10000.0,
        "size_btc": 0.1227,
        "contract": "XBTUSDT",
        "hold_h": 6,
        "range_4h_pct": 0.43,
        "atr_pct": 0.07,
        "trend_pct_per_h": 0.04,
        "placed_at": None,
        "user_action": None,
        "decision_latency_sec": None,
        "buy_fill_ts": None,
        "sell_fill_ts": None,
        "exit_ts": None,
        "exit_reason": None,
        "legs_filled": None,
        "pnl_usd": None,
    }


def test_append_and_read(tmp_path: Path) -> None:
    p = tmp_path / "j.jsonl"
    rec = _make_record(datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc))
    append_signal(rec, path=p)
    rows = read_all(path=p)
    assert len(rows) == 1
    assert rows[0]["signal_id"] == rec["signal_id"]


def test_mark_user_action_placed_sets_latency(tmp_path: Path) -> None:
    p = tmp_path / "j.jsonl"
    ts = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    rec = _make_record(ts)
    append_signal(rec, path=p)
    later = ts + timedelta(seconds=45)
    ok = mark_user_action(rec["signal_id"], "placed", now=later, path=p)
    assert ok
    rows = read_all(path=p)
    assert rows[0]["user_action"] == "placed"
    assert rows[0]["placed_at"] is not None
    assert rows[0]["decision_latency_sec"] == 45.0


def test_mark_user_action_skipped(tmp_path: Path) -> None:
    p = tmp_path / "j.jsonl"
    ts = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    rec = _make_record(ts)
    append_signal(rec, path=p)
    ok = mark_user_action(rec["signal_id"], "skipped", path=p)
    assert ok
    rows = read_all(path=p)
    assert rows[0]["user_action"] == "skipped"
    assert rows[0]["exit_reason"] == "user_skip"


def test_pending_signals_filter(tmp_path: Path) -> None:
    p = tmp_path / "j.jsonl"
    ts = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    # 3 records: placed-no-outcome, placed-with-outcome, skipped
    r1 = _make_record(ts, signal_id="rh_1")
    r1["user_action"] = "placed"
    append_signal(r1, path=p)

    r2 = _make_record(ts + timedelta(hours=3), signal_id="rh_2")
    r2["user_action"] = "placed"
    r2["exit_reason"] = "pair_win"
    r2["pnl_usd"] = 24.0
    append_signal(r2, path=p)

    r3 = _make_record(ts + timedelta(hours=6), signal_id="rh_3")
    r3["user_action"] = "skipped"
    append_signal(r3, path=p)

    # 2026-07-21: теневой учёт — pending = ВСЕ без исхода, а не только
    # «placed» (кнопки не жмут → из 428 сигналов исход был записан у одного)
    pending = pending_signals(path=p)
    assert [r["signal_id"] for r in pending] == ["rh_1", "rh_3"]
    assert all(r.get("exit_reason") is None for r in pending)


def test_update_record(tmp_path: Path) -> None:
    p = tmp_path / "j.jsonl"
    ts = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    rec = _make_record(ts)
    append_signal(rec, path=p)
    ok = update_record(rec["signal_id"], {
        "exit_reason": "pair_win",
        "legs_filled": 2,
        "pnl_usd": 24.0,
    }, path=p)
    assert ok
    rows = read_all(path=p)
    assert rows[0]["exit_reason"] == "pair_win"
    assert rows[0]["pnl_usd"] == 24.0


def test_parse_signal_id_round_trip() -> None:
    ts = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    for symbol, variant in [
        ("BTCUSDT", "1m"),
        ("BTCUSDT", "5m"),
        ("ETHUSDT", "1m"),
        ("ETHUSDT", "5m"),
        ("XRPUSDT", "1m"),
    ]:
        sid = signal_id_from_ts(ts, symbol=symbol, variant=variant)
        assert parse_signal_id(sid) == (symbol, variant)


def test_parse_signal_id_malformed_defaults_to_btc() -> None:
    assert parse_signal_id("garbage") == ("BTCUSDT", "1m")
    assert parse_signal_id("rh_only") == ("BTCUSDT", "1m")


def test_mark_user_action_auto_routes_by_signal_id(tmp_path: Path, monkeypatch) -> None:
    """Without explicit path, mark_user_action must route to per-symbol journal."""
    import services.range_hunter.journal as journal_mod
    monkeypatch.setattr(journal_mod, "JOURNAL_PATH", tmp_path / "rh_btc.jsonl")

    ts = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    eth_sid = signal_id_from_ts(ts, symbol="ETHUSDT", variant="1m")
    eth_path = journal_path_for("ETHUSDT", "1m")
    eth_path.parent.mkdir(parents=True, exist_ok=True)
    rec = _make_record(ts, signal_id=eth_sid)
    rec["contract"] = "ETHUSDT"
    append_signal(rec, path=eth_path)

    later = ts + timedelta(seconds=30)
    ok = mark_user_action(eth_sid, "placed", now=later)
    assert ok, "auto-routed call should find the ETH record"
    rows = read_all(path=eth_path)
    assert rows[0]["user_action"] == "placed"
    assert rows[0]["decision_latency_sec"] == 30.0

    btc_path = tmp_path / "rh_btc.jsonl"
    assert not btc_path.exists() or read_all(path=btc_path) == [], \
        "BTC journal must remain untouched by an ETH callback"


def test_summarize_basic(tmp_path: Path) -> None:
    p = tmp_path / "j.jsonl"
    ts = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    # 5 placed, 3 pair_win, 1 buy_stopped, 1 pending
    for i in range(5):
        r = _make_record(ts + timedelta(hours=i), signal_id=f"rh_{i}")
        r["user_action"] = "placed"
        if i < 3:
            r["exit_reason"] = "pair_win"
            r["legs_filled"] = 2
            r["pnl_usd"] = 24.0
        elif i == 3:
            r["exit_reason"] = "buy_stopped"
            r["legs_filled"] = 1
            r["pnl_usd"] = -25.5
        # i==4 — pending
        append_signal(r, path=p)

    summary = summarize(path=p, min_n=3)
    assert summary["total"] == 5
    assert summary["placed"] == 5
    assert summary["closed"] == 4
    assert summary["pair_win_pct"] == 75.0  # 3/4
    assert summary["legs_filled_2"] == 3
    assert summary["legs_filled_1"] == 1
    # empirical_fill_rate = (2*3 + 1*1) / (2*4) = 7/8 = 0.875
    assert summary["empirical_fill_rate"] == 0.875
    # PnL = 3*24 + (-25.5) = 46.5
    assert abs(summary["total_pnl_usd"] - 46.5) < 0.01
