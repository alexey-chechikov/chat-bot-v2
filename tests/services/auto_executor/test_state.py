"""State (de)serialization + outcomes + offset persistence."""
from __future__ import annotations

import json

import pytest

from services.auto_executor.state import (
    KillState,
    Position,
    State,
    append_outcome,
    load_offset,
    load_state,
    reset_daily_pnl_if_new_day,
    save_offset,
    save_state,
)


def _make_pos(**over) -> Position:
    base = {
        "setup_id": "setup-1",
        "setup_type": "long_pdl_bounce",
        "pair": "BTCUSDT",
        "bitmex_symbol": "XBTUSDT",
        "side": "long",
        "entry_price": 77000.0,
        "sl_price": 76500.0,
        "tp1_price": 77600.0,
        "tp2_price": 78200.0,
        "expires_at": "2026-06-01T00:00:00+00:00",
        "qty_lots": 100,
        "qty_btc": 0.0001,
        "nominal_usd": 7.7,
        "cl_ord_id": "ae-test",
        "status": "filled",
        "avg_entry_price": 77001.5,
        "filled_at": "2026-05-24T10:00:00+00:00",
    }
    base.update(over)
    return Position(**base)


def test_state_round_trip(tmp_path) -> None:
    path = tmp_path / "state.json"
    s = State(open_position=_make_pos())
    s.kill = KillState(daily_pnl_usd=-1.5, daily_pnl_date="2026-05-24",
                        consecutive_losses=2, last_known_balance_usd=99.0)
    save_state(s, path=path)
    s2 = load_state(path=path)
    assert s2.open_position is not None
    assert s2.open_position.setup_id == "setup-1"
    assert s2.open_position.qty_lots == 100
    assert s2.kill.daily_pnl_usd == pytest.approx(-1.5)
    assert s2.kill.consecutive_losses == 2
    assert s2.kill.last_known_balance_usd == pytest.approx(99.0)


def test_load_state_returns_default_on_missing(tmp_path) -> None:
    s = load_state(path=tmp_path / "nope.json")
    assert s.open_position is None
    assert s.kill.daily_pnl_usd == 0.0


def test_load_state_resilient_to_corruption(tmp_path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not valid json", encoding="utf-8")
    s = load_state(path=path)
    # default state on corrupted file (does NOT raise)
    assert s.open_position is None


def test_append_outcome_writes_one_line(tmp_path) -> None:
    out = tmp_path / "outcomes.jsonl"
    pos = _make_pos(status="closed", exit_reason="tp1",
                     avg_exit_price=77600.5, realized_pnl_usd=+0.59,
                     closed_at="2026-05-24T11:00:00+00:00")
    append_outcome(pos, path=out)
    rec = json.loads(out.read_text(encoding="utf-8").strip())
    assert rec["setup_id"] == "setup-1"
    assert rec["exit_reason"] == "tp1"
    assert rec["realized_pnl_usd"] == pytest.approx(0.59)


def test_append_outcome_skips_unclosed(tmp_path) -> None:
    out = tmp_path / "outcomes.jsonl"
    pos = _make_pos(status="filled")  # not closed
    append_outcome(pos, path=out)
    assert not out.exists() or out.read_text() == ""


def test_offset_round_trip(tmp_path) -> None:
    path = tmp_path / "offset.json"
    save_offset(12345, path=path)
    assert load_offset(path=path) == 12345


def test_offset_default_when_missing(tmp_path) -> None:
    assert load_offset(path=tmp_path / "missing.json") == 0


def test_reset_daily_pnl_rolls_on_new_day() -> None:
    from datetime import datetime, timezone
    k = KillState(daily_pnl_usd=-2.0, daily_pnl_date="2026-05-23")
    now = datetime(2026, 5, 24, 0, 0, 1, tzinfo=timezone.utc)
    rolled = reset_daily_pnl_if_new_day(k, now=now)
    assert rolled
    assert k.daily_pnl_usd == 0.0
    assert k.daily_pnl_date == "2026-05-24"


def test_reset_daily_pnl_noop_same_day() -> None:
    from datetime import datetime, timezone
    k = KillState(daily_pnl_usd=-2.0, daily_pnl_date="2026-05-24")
    now = datetime(2026, 5, 24, 23, 59, tzinfo=timezone.utc)
    rolled = reset_daily_pnl_if_new_day(k, now=now)
    assert not rolled
    assert k.daily_pnl_usd == pytest.approx(-2.0)
