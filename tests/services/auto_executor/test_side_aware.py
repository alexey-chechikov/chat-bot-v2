"""Phase-2 SHORT support — inversion logic (pure helpers) + gate gating."""
from __future__ import annotations

from services.auto_executor import gates
from services.auto_executor.loop import (
    _est_pnl_usd, _sl_tp_prices, _hit_reason, _open_order_side, _exit_order_side,
)


# ── PnL ────────────────────────────────────────────────────────────────
def test_pnl_long_matches_legacy():
    # long profit when exit > entry
    assert _est_pnl_usd("long", 0.0001, 74000, 74500) > 0
    assert abs(_est_pnl_usd("long", 0.0001, 74000, 74500) - (500 * 0.0001)) < 1e-9


def test_pnl_short_profits_when_price_falls():
    assert _est_pnl_usd("short", 0.0001, 74000, 73500) > 0
    assert _est_pnl_usd("short", 0.0001, 74000, 74500) < 0


# ── SL/TP placement ────────────────────────────────────────────────────
def test_sl_tp_long_below_above():
    sl, tp1, tp2 = _sl_tp_prices("long", 1000.0, 1.0, 2.0, 4.0)
    assert sl < 1000 < tp1 < tp2


def test_sl_tp_short_above_below():
    sl, tp1, tp2 = _sl_tp_prices("short", 1000.0, 1.0, 2.0, 4.0)
    assert sl > 1000 > tp1 > tp2


# ── trigger detection ──────────────────────────────────────────────────
def test_hit_long():
    assert _hit_reason("long", 990, 995, 1010) == "sl"     # fell to stop
    assert _hit_reason("long", 1015, 995, 1010) == "tp1"   # rose to target
    assert _hit_reason("long", 1000, 995, 1010) is None


def test_hit_short():
    assert _hit_reason("short", 1015, 1010, 990) == "sl"   # rose to stop
    assert _hit_reason("short", 985, 1010, 990) == "tp1"   # fell to target
    assert _hit_reason("short", 1000, 1010, 990) is None


# ── order sides ────────────────────────────────────────────────────────
def test_order_sides():
    assert _open_order_side("long") == "Buy"
    assert _open_order_side("short") == "Sell"
    assert _exit_order_side("long") == "Sell"
    assert _exit_order_side("short") == "Buy"


# ── 2026-05-30 reality-filter: SHORT reverted (paper PF was debunked; honest
#    precision n=1 each, negative). SHORT code stays but gated off. ──────────
def test_short_side_gated_off_again():
    assert gates.gate_side("long")[0] is True
    assert gates.gate_side("short")[0] is False  # reverted


def test_short_setups_not_allowlisted():
    assert gates.gate_setup_type("short_div_bos_15m")[0] is False
    assert gates.gate_setup_type("short_double_top")[0] is False
    # reality-filter survivor IS allowed
    assert gates.gate_setup_type("long_double_bottom")[0] is True
