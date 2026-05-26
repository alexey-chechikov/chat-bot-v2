"""Hybrid entry mode (limit 5min → market fallback) tests."""
from __future__ import annotations

import pytest

from services.auto_executor.loop import _recalc_sl_tp_for_fill
from services.auto_executor.state import Position


def _mk(entry: float, sl: float, tp1: float, tp2: float = 0.0) -> Position:
    return Position(
        setup_id="x", setup_type="long_pdl_bounce", pair="BTCUSDT",
        bitmex_symbol="XBTUSDT", side="long",
        entry_price=entry, sl_price=sl, tp1_price=tp1, tp2_price=tp2,
        expires_at="2026-06-01T00:00:00+00:00",
        qty_lots=100, qty_btc=0.0001, nominal_usd=7.7,
        cl_ord_id="ae-x",
    )


def test_recalc_preserves_sl_distance_pct() -> None:
    pos = _mk(entry=77000.0, sl=76600.0, tp1=77600.0)
    # SL was 0.5194% below entry
    _recalc_sl_tp_for_fill(pos, actual_entry=77100.0)
    # New SL must still be ~0.5194% below actual entry
    expected_sl = 77100.0 * (1 - 400.0 / 77000.0)
    assert pos.sl_price == pytest.approx(expected_sl, rel=1e-4)


def test_recalc_preserves_tp1_distance_pct() -> None:
    pos = _mk(entry=77000.0, sl=76600.0, tp1=77600.0)
    _recalc_sl_tp_for_fill(pos, actual_entry=77100.0)
    expected_tp1 = 77100.0 * (1 + 600.0 / 77000.0)
    assert pos.tp1_price == pytest.approx(expected_tp1, rel=1e-4)


def test_recalc_recomputes_tp2_when_present() -> None:
    pos = _mk(entry=77000.0, sl=76600.0, tp1=77600.0, tp2=78200.0)
    _recalc_sl_tp_for_fill(pos, actual_entry=77100.0)
    expected_tp2 = 77100.0 * (1 + 1200.0 / 77000.0)
    assert pos.tp2_price == pytest.approx(expected_tp2, rel=1e-4)


def test_recalc_noop_when_actual_entry_zero() -> None:
    pos = _mk(entry=77000.0, sl=76600.0, tp1=77600.0)
    orig_sl = pos.sl_price
    orig_tp1 = pos.tp1_price
    _recalc_sl_tp_for_fill(pos, actual_entry=0.0)
    assert pos.sl_price == orig_sl
    assert pos.tp1_price == orig_tp1


def test_recalc_handles_higher_fill_correctly() -> None:
    """Real-world case: limit at PDL, market chased higher, fill 0.15% above."""
    pos = _mk(entry=76410.3, sl=76258.0, tp1=76800.0)
    fill = 76410.3 * 1.0015  # 0.15% slip
    _recalc_sl_tp_for_fill(pos, actual_entry=fill)
    # SL should be ~0.20% below fill
    assert pos.sl_price < fill
    assert pos.sl_price == pytest.approx(fill * (1 - 152.3 / 76410.3), rel=1e-4)
    # TP1 should be ~0.51% above fill
    assert pos.tp1_price > fill


def test_position_default_entry_mode_is_limit() -> None:
    pos = _mk(entry=77000.0, sl=76600.0, tp1=77600.0)
    assert pos.entry_mode == "limit"


def test_position_entry_mode_serializes_through_dict() -> None:
    from services.auto_executor.state import State, save_state, load_state
    import pathlib
    pos = _mk(entry=77000.0, sl=76600.0, tp1=77600.0)
    pos.entry_mode = "market_fallback"
    s = State(open_position=pos)
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "state.json"
        save_state(s, path=p)
        s2 = load_state(path=p)
    assert s2.open_position is not None
    assert s2.open_position.entry_mode == "market_fallback"
