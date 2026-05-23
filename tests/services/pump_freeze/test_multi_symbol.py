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


def test_build_live_features_skips_non_btc():
    """The BTC-trained model must NOT be fed ETH/XRP features — features
    return {} for non-BTC, so score_event() then returns None and the gate
    cleanly falls back to reactive on ETH/XRP."""
    ts = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
    assert build_live_features("anybot", ts, symbol="ETHUSDT") == {}
    assert build_live_features("anybot", ts, symbol="XRPUSDT") == {}
