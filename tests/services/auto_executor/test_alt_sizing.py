"""Phase-2b: multi-symbol sizing from live instrument specs + symbol map."""
from __future__ import annotations

from services.auto_executor.loop import (
    _bitmex_symbol, _qty_from_instrument, NOMINAL_GUARD_MAX_USD,
)

# Real BitMEX specs probed 2026-05-30
ETH_INST = {"symbol": "ETHUSDT", "lotSize": 1000, "underlyingToPositionMultiplier": 100000}
XRP_INST = {"symbol": "XRPUSDT", "lotSize": 100, "underlyingToPositionMultiplier": 100}
XBT_INST = {"symbol": "XBTUSDT", "lotSize": 100, "underlyingToPositionMultiplier": 1000000}


def test_symbol_map():
    assert _bitmex_symbol("BTCUSDT") == "XBTUSDT"
    assert _bitmex_symbol("ETHUSDT") == "ETHUSDT"
    assert _bitmex_symbol("XRPUSDT") == "XRPUSDT"


def test_eth_sizing_min_lot():
    # ETH min lot = 1000 contracts = 0.01 ETH; at $2025 ≈ $20.25 nominal
    lots, under, nominal = _qty_from_instrument(ETH_INST, 2025.0, target_usd=8.0)
    assert lots == 1000              # can't go below one lot-unit
    assert abs(under - 0.01) < 1e-9
    assert 18 < nominal < 22


def test_xrp_sizing_granular():
    # XRP: 1 lot-unit (100) = 1 XRP ≈ $1.35; ~$8 target → ~600 contracts
    lots, under, nominal = _qty_from_instrument(XRP_INST, 1.35, target_usd=8.0)
    assert lots % 100 == 0 and lots > 0
    assert 6 < nominal < 10


def test_xbt_sizing_micro():
    lots, under, nominal = _qty_from_instrument(XBT_INST, 74000.0, target_usd=8.0)
    assert lots == 100               # 100 contracts = 0.0001 BTC
    assert abs(under - 0.0001) < 1e-12
    assert 6 < nominal < 9


def test_nominal_guard_blocks_oversize():
    # absurd price → one lot already exceeds the guard → reject (0,0,0)
    lots, under, nominal = _qty_from_instrument(ETH_INST, 1_000_000.0)
    assert (lots, under, nominal) == (0, 0.0, 0.0)


def test_bad_specs_return_zero():
    assert _qty_from_instrument({}, 2000.0) == (0, 0.0, 0.0)
    assert _qty_from_instrument(ETH_INST, 0.0) == (0, 0.0, 0.0)
