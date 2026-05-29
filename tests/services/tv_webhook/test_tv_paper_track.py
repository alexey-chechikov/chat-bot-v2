"""Tests for TV→paper side/symbol mapping and symbol-aware recording."""
from __future__ import annotations

import json

from services.tv_webhook import dispatcher as d
from services.tv_webhook.signal_types import (
    BOS_BEARISH, EXHAUSTION_BOTTOM, SQUEEZE_UP, LIQ_CASCADE, CVD_DIVERGENCE,
)


def test_side_from_explicit_direction():
    assert d._tv_side(CVD_DIVERGENCE, {"direction": "bullish"}) == "LONG"
    assert d._tv_side(CVD_DIVERGENCE, {"direction": "bearish"}) == "SHORT"


def test_side_from_inherent_type():
    assert d._tv_side(EXHAUSTION_BOTTOM, {}) == "LONG"
    assert d._tv_side(BOS_BEARISH, {}) == "SHORT"
    assert d._tv_side(SQUEEZE_UP, {}) == "LONG"


def test_side_from_liq_side():
    assert d._tv_side(LIQ_CASCADE, {"liq_side": "SHORTS"}) == "LONG"
    assert d._tv_side(LIQ_CASCADE, {"liq_side": "LONGS"}) == "SHORT"


def test_side_none_when_undeterminable():
    assert d._tv_side("range_boundary", {}) is None


def test_symbol_normalisation():
    assert d._tv_symbol({"ticker": "BTCUSDT.P"}) == "BTCUSDT"
    assert d._tv_symbol({"ticker": "ETHUSDT"}) == "ETHUSDT"
    assert d._tv_symbol({}) == "BTCUSDT"


def test_record_paper_signal_stores_symbol(tmp_path):
    from services.paper_signal_tracker import journal as j
    p = tmp_path / "psig.jsonl"
    j.record_paper_signal(source="tv_test", side="LONG", entry=2000.0,
                          stop_pct=-0.75, tp_pct=1.5, hold_h=8,
                          symbol="ETHUSDT", path=p)
    rec = json.loads(p.read_text().strip())
    assert rec["symbol"] == "ETHUSDT"
    assert rec["source"] == "tv_test"


def test_evaluator_groups_by_symbol(tmp_path, monkeypatch):
    """Pending alt signal must NOT resolve against BTC bars."""
    from services.paper_signal_tracker import evaluator as e
    calls = {}

    def fake_loader(symbol, needed_hours):
        calls[symbol] = calls.get(symbol, 0) + 1
        return []  # no bars → nothing resolves, but routing is what we test

    monkeypatch.setattr(e, "_load_recent_1m_symbol", fake_loader)
    monkeypatch.setattr(e, "_load_recent_1m", lambda needed_hours=12, **k: [])
    pend = [
        {"signal_id": "a", "symbol": "ETHUSDT", "side": "LONG", "entry": 2000,
         "stop": 1980, "tp": 2030, "hold_h": 8, "ts_signal": "2026-05-29T00:00:00+00:00"},
        {"signal_id": "b", "symbol": "XRPUSDT", "side": "SHORT", "entry": 1.4,
         "stop": 1.41, "tp": 1.38, "hold_h": 8, "ts_signal": "2026-05-29T00:00:00+00:00"},
    ]
    monkeypatch.setattr(e, "pending_signals", lambda **k: pend)
    e.tick()
    assert "ETHUSDT" in calls and "XRPUSDT" in calls
