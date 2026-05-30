"""Pure-logic tests for auto_executor.gates — no network, no I/O."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from services.auto_executor import gates
from services.auto_executor.state import KillState, Position, State


# ─── fixtures ──────────────────────────────────────────────────────
def _setup(**over) -> dict:
    base = {
        "setup_id": "setup-test-1",
        "setup_type": "long_pdl_bounce",
        "pair": "BTCUSDT",
        "entry_price": 77000.0,
        "stop_price": 76500.0,
        "tp1_price": 77600.0,
        "tp2_price": 78200.0,
        "expires_at": "2026-05-30T00:00:00+00:00",
    }
    base.update(over)
    return base


def _state_with_balance(usd: float = 100.0) -> State:
    s = State()
    s.kill.last_known_balance_usd = usd
    s.kill.daily_pnl_date = datetime.now(timezone.utc).date().isoformat()
    return s


# ─── individual gates ──────────────────────────────────────────────
def test_gate_setup_type_allows_allowlist() -> None:
    # 2026-05-30 reality-filter survivors
    assert gates.gate_setup_type("long_pdl_bounce")[0]
    assert gates.gate_setup_type("long_dump_reversal")[0]
    assert gates.gate_setup_type("long_double_bottom")[0]
    # removed: long_multi_divergence (honest −21%)
    assert not gates.gate_setup_type("long_multi_divergence")[0]


def test_gate_setup_type_rejects_unknown() -> None:
    # short_pdh_rejection is a real but non-allowlisted ballast setup (honest −0.32%)
    ok, reason = gates.gate_setup_type("short_pdh_rejection")
    assert not ok
    assert "short_pdh_rejection" in reason


def test_gate_pair_rejects_non_btcusdt() -> None:
    assert not gates.gate_pair("ETHUSDT")[0]


def _open_pos(setup_id: str = "x") -> Position:
    return Position(
        setup_id=setup_id, setup_type="long_pdl_bounce", pair="BTCUSDT",
        bitmex_symbol="XBTUSDT", side="long",
        entry_price=77000, sl_price=76500, tp1_price=77600, tp2_price=78200,
        expires_at="2026-06-01T00:00:00+00:00",
        qty_lots=100, qty_btc=0.0001, nominal_usd=7.7,
        cl_ord_id=f"cl-{setup_id}", status="filled",
    )


def test_gate_max_parallel_allows_below_cap() -> None:
    s = _state_with_balance()
    s.open_positions = [_open_pos("a"), _open_pos("b")]  # 2 < 3
    ok, _ = gates.gate_max_parallel(s)
    assert ok


def test_gate_max_parallel_blocks_at_cap() -> None:
    s = _state_with_balance()
    s.open_positions = [_open_pos("a"), _open_pos("b"), _open_pos("c")]
    ok, reason = gates.gate_max_parallel(s)
    assert not ok
    assert "max_parallel" in reason
    assert "a" in reason and "b" in reason and "c" in reason


def test_gate_daily_loss_blocks_at_or_below_limit() -> None:
    s = _state_with_balance()
    s.kill.daily_pnl_usd = -3.0
    assert not gates.gate_daily_loss(s)[0]
    s.kill.daily_pnl_usd = -2.99
    assert gates.gate_daily_loss(s)[0]


def test_gate_balance_floor_blocks_below_threshold() -> None:
    s = _state_with_balance(usd=39.0)
    assert not gates.gate_balance_floor(s)[0]
    s = _state_with_balance(usd=40.01)
    assert gates.gate_balance_floor(s)[0]


def test_gate_balance_floor_unknown_returns_allow() -> None:
    s = State()  # last_known_balance == 0 default
    ok, reason = gates.gate_balance_floor(s)
    assert ok
    assert "unknown" in reason


def test_gate_global_freeze_blocks_while_active() -> None:
    s = _state_with_balance()
    now = datetime.now(timezone.utc)
    s.kill.freeze_until = (now + timedelta(hours=1)).isoformat()
    assert not gates.gate_global_freeze(s, now=now)[0]
    s.kill.freeze_until = (now - timedelta(hours=1)).isoformat()
    assert gates.gate_global_freeze(s, now=now)[0]


def test_gate_setup_freeze_blocks_when_killswitch_marked() -> None:
    s = _state_with_balance()
    s.kill.setup_frozen["long_pdl_bounce"] = "2026-05-24T00:00:00+00:00"
    assert not gates.gate_setup_freeze(s, "long_pdl_bounce")[0]
    assert gates.gate_setup_freeze(s, "long_multi_divergence")[0]


def test_gate_entry_slippage_rejects_only_when_entry_above_market_by_too_much() -> None:
    """Fixed 2026-05-25 — post-only BUY rejected by BitMEX iff entry > market.
    Resting bid below market is fine; market above limit is fine."""
    # entry $77000, market $76000 → entry is 1.32% ABOVE market → reject (would cross)
    ok, reason = gates.gate_entry_slippage(77000.0, 76000.0)
    assert not ok
    assert "limit_would_cross" in reason
    # entry $77000, market $77050 → market 0.06% above → resting bid → ALLOW
    assert gates.gate_entry_slippage(77000.0, 77050.0)[0]
    # entry $77000, market $78000 → market 1.3% above → resting bid → ALLOW
    assert gates.gate_entry_slippage(77000.0, 78000.0)[0]
    # entry $77000, market $76900 → entry 0.13% above (within 0.30%) → ALLOW
    assert gates.gate_entry_slippage(77000.0, 76900.0)[0]
    # current_price unknown (0) → allow (will retry next tick)
    assert gates.gate_entry_slippage(77000.0, 0.0)[0]


# ─── composite can_open ────────────────────────────────────────────
def test_can_open_happy_path(monkeypatch) -> None:
    s = _state_with_balance(usd=100.0)
    # current_price slightly ABOVE entry — perfect resting-bid scenario
    with patch("services.auto_executor.gates.gate_paper_wr",
                return_value=(True, "healthy")):
        ok, reason = gates.can_open(_setup(), s, current_price=77050.0)
    assert ok, reason


def test_can_open_blocks_when_entry_far_above_market() -> None:
    """If setup.entry_price is way above current market, post-only would cross
    → BitMEX rejects, so we abort early."""
    s = _state_with_balance(usd=100.0)
    with patch("services.auto_executor.gates.gate_paper_wr",
                return_value=(True, "healthy")):
        ok, reason = gates.can_open(_setup(entry_price=77000.0), s,
                                      current_price=76000.0)
    assert not ok
    assert "limit_would_cross" in reason


def test_can_open_blocks_when_paper_wr_unhealthy() -> None:
    s = _state_with_balance()
    with patch("services.auto_executor.gates.gate_paper_wr",
                return_value=(False, "unhealthy WR=30%")):
        ok, reason = gates.can_open(_setup(), s, current_price=77050.0)
    assert not ok
    assert "WR=30" in reason


def test_can_open_blocks_when_setup_frozen() -> None:
    s = _state_with_balance()
    s.kill.setup_frozen["long_pdl_bounce"] = "2026-05-24T00:00:00+00:00"
    with patch("services.auto_executor.gates.gate_paper_wr",
                return_value=(True, "healthy")):
        ok, _ = gates.can_open(_setup(), s, current_price=77050.0)
    assert not ok


def test_can_open_blocks_for_disallowed_setup_type() -> None:
    s = _state_with_balance()
    bad = _setup(setup_type="short_pdh_rejection")  # real but not allowlisted (ballast)
    ok, reason = gates.can_open(bad, s)
    assert not ok
    assert "short_pdh_rejection" in reason


# ─── kill-switch updates ──────────────────────────────────────────
def test_record_outcome_resets_consec_on_win() -> None:
    k = KillState(consecutive_losses=3, daily_pnl_date="2026-05-24",
                   daily_pnl_usd=-1.5)
    gates.record_outcome_update_killstate(
        k, setup_type="long_pdl_bounce", pnl_usd=+0.5,
        now=datetime(2026, 5, 24, 12, 0, tzinfo=timezone.utc),
    )
    assert k.consecutive_losses == 0
    assert k.daily_pnl_usd == pytest.approx(-1.0)


def test_record_outcome_triggers_freeze_after_5_losses() -> None:
    k = KillState(consecutive_losses=4, daily_pnl_date="2026-05-24",
                   daily_pnl_usd=-2.0)
    now = datetime(2026, 5, 24, 12, 0, tzinfo=timezone.utc)
    gates.record_outcome_update_killstate(
        k, setup_type="long_pdl_bounce", pnl_usd=-0.5, now=now,
    )
    assert k.consecutive_losses == 5
    assert k.freeze_until is not None
    until = datetime.fromisoformat(k.freeze_until.replace("Z", "+00:00"))
    assert (until - now).total_seconds() >= 23 * 3600


def test_record_outcome_rolls_daily_pnl_on_new_day() -> None:
    k = KillState(daily_pnl_date="2026-05-23", daily_pnl_usd=-2.5)
    now = datetime(2026, 5, 24, 0, 0, 1, tzinfo=timezone.utc)
    gates.record_outcome_update_killstate(
        k, setup_type="long_pdl_bounce", pnl_usd=+0.5, now=now,
    )
    assert k.daily_pnl_date == "2026-05-24"
    assert k.daily_pnl_usd == pytest.approx(0.5)


def test_evaluate_killswitch_freezes_at_low_wr() -> None:
    k = KillState()
    outcomes = {
        "long_pdl_bounce": [-1, -1, -1, -1, +1],  # 1/5 = 20% WR
        "long_multi_divergence": [+1, +1, +1, -1, +1],  # 80% WR
    }
    newly = gates.evaluate_killswitch_per_setup(
        k, outcomes_by_setup=outcomes,
    )
    assert "long_pdl_bounce" in newly
    assert "long_multi_divergence" not in newly
    assert "long_pdl_bounce" in k.setup_frozen


def test_evaluate_killswitch_skips_low_n() -> None:
    k = KillState()
    outcomes = {"long_pdl_bounce": [-1, -1, -1, -1]}  # n=4 < 5
    newly = gates.evaluate_killswitch_per_setup(
        k, outcomes_by_setup=outcomes,
    )
    assert not newly
    assert k.setup_frozen == {}


def test_evaluate_killswitch_does_not_unfreeze_existing() -> None:
    k = KillState(setup_frozen={"long_pdl_bounce": "2026-05-24T00:00:00+00:00"})
    outcomes = {"long_pdl_bounce": [+1, +1, +1, +1, +1]}  # 100% would be healthy
    newly = gates.evaluate_killswitch_per_setup(
        k, outcomes_by_setup=outcomes,
    )
    assert not newly
    assert "long_pdl_bounce" in k.setup_frozen
