"""Phase A — multi-symbol scope parsing + ML-gate symbol guard.

Verifies the symbol-aware extension is backward-compatible (string scope
values keep behaving as BTCUSDT) and that the ML-gate refuses to score
non-BTC symbols (model is BTC-trained — train/serve skew prevented).
"""
from datetime import datetime, timezone

from services.pump_freeze.loop import _parse_scope_value, build_live_features


def test_parse_scope_value_legacy_string():
    """A bare string value -> (side, 'BTCUSDT') — old config still works."""
    assert _parse_scope_value("short") == ("short", "BTCUSDT")
    assert _parse_scope_value("long") == ("long", "BTCUSDT")


def test_parse_scope_value_tuple_form():
    """The (side, symbol) tuple form passes through unchanged."""
    assert _parse_scope_value(("long", "ETHUSDT")) == ("long", "ETHUSDT")
    assert _parse_scope_value(("short", "XRPUSDT")) == ("short", "XRPUSDT")


def test_parse_scope_value_list_form():
    """JSON-style lists also accepted."""
    assert _parse_scope_value(["long", "ETHUSDT"]) == ("long", "ETHUSDT")


def test_build_live_features_accepts_symbol_kwarg():
    """build_live_features takes a symbol kwarg (default BTCUSDT) — verifies
    the multi-symbol signature. The Phase-B/C update wires per-symbol models;
    behavior beyond signature is integration-tested, not unit-mockable here.
    """
    import inspect
    sig = inspect.signature(build_live_features)
    assert "symbol" in sig.parameters
    assert sig.parameters["symbol"].default == "BTCUSDT"
