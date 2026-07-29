"""Трендовые сигналы: вход/выход/истощение, теневой учёт без кнопок."""
from __future__ import annotations

import json

import pytest

from services.trend_signals import loop as ts


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(ts, "JOURNAL", tmp_path / "j.jsonl")
    monkeypatch.setattr(ts, "STATE", tmp_path / "s.json")
    monkeypatch.setattr(ts, "CONFIG", tmp_path / "c.json")
    monkeypatch.setattr(ts, "PROFILES", tmp_path / "p.json")
    ts.CONFIG.write_text(json.dumps({"enabled": True, "position_usd": 1500}),
                         encoding="utf-8")
    ts.PROFILES.write_text(json.dumps({"assets": {
        "ETHUSDT": {"trend_bot_ok": True, "leg_move_pct_med": 10.7,
                    "leg_days_med": 3.5, "stretch_atr_med": 1.87,
                    "stretch_atr_p75": 2.5, "rsi_med": 66, "vol_p75": 2.04,
                    "after_full_reversal_pct": 49, "after_deep_pct": 42,
                    "after_small_pct": 9,
                    "trend_edge": {"total_pct": 109.0, "pf": 1.68,
                                   "wr_pct": 41.6, "avg_win": 8.4,
                                   "avg_loss": -3.6}},
        "BTCUSDT": {"trend_bot_ok": False, "trend_edge": {"total_pct": -3.5}},
    }}), encoding="utf-8")


def _events():
    return [json.loads(l)["event"]
            for l in ts.JOURNAL.read_text().splitlines()]


def _patch_analyze(monkeypatch, result, hits=0):
    monkeypatch.setattr("tools.trend_state.analyze",
                        lambda sym, prof: result)
    monkeypatch.setattr("tools.trend_state.exhaustion",
                        lambda s, prof: (hits, ["✔ тест"] * hits, 70.0))


def test_only_validated_assets_are_watched():
    """BTC (trend_bot_ok=false) не отслеживается — у него эджа нет."""
    a = ts.active_assets()
    assert list(a) == ["ETHUSDT"]


def test_entry_signal_journaled_and_sent(monkeypatch):
    _patch_analyze(monkeypatch, {"pos": "LONG", "px": 1900.0, "stop": 1820.0,
                                 "adx": 25.0})
    sent = []
    assert ts.tick(send_fn=sent.append) == 1
    assert "ENTRY" in _events()
    assert sent and "ТРЕНД LONG ETH" in sent[0]
    assert "1,820" in sent[0]                   # стоп в карточке
    assert "риск 4.2%" in sent[0] or "риск" in sent[0]
    st = json.loads(ts.STATE.read_text())
    assert st["ETHUSDT"]["side"] == "LONG"


def test_no_duplicate_entry_while_in_position(monkeypatch):
    _patch_analyze(monkeypatch, {"pos": "LONG", "px": 1900.0, "stop": 1820.0,
                                 "adx": 25.0})
    ts.tick(send_fn=lambda t: None)
    sent = []
    assert ts.tick(send_fn=sent.append) == 0    # второй тик молчит
    assert _events().count("ENTRY") == 1


def test_exit_computes_pnl_without_button(monkeypatch):
    """Теневой учёт: PnL считается сам (урок session_breakout)."""
    _patch_analyze(monkeypatch, {"pos": "LONG", "px": 1900.0, "stop": 1820.0,
                                 "adx": 25.0})
    ts.tick(send_fn=lambda t: None)
    _patch_analyze(monkeypatch, {"pos": None, "px": 2090.0, "hh": 2100.0,
                                 "ll": 1800.0, "adx": 18.0})
    sent = []
    assert ts.tick(send_fn=sent.append) == 1
    rows = [json.loads(l) for l in ts.JOURNAL.read_text().splitlines()]
    ex = [r for r in rows if r["event"] == "EXIT"][0]
    assert abs(ex["pnl_pct"] - 10.0) < 0.01     # 1900 → 2090 = +10%
    assert sent and "ВЫХОД" in sent[0]
    assert json.loads(ts.STATE.read_text()) == {}


def test_exhaustion_fires_once_per_episode(monkeypatch):
    _patch_analyze(monkeypatch, {"pos": "LONG", "px": 1900.0, "stop": 1820.0,
                                 "adx": 25.0})
    ts.tick(send_fn=lambda t: None)
    _patch_analyze(monkeypatch, {"pos": "LONG", "px": 2000.0, "stop": 1900.0,
                                 "adx": 30.0}, hits=3)
    sent = []
    assert ts.tick(send_fn=sent.append) == 1
    assert "ИСТОЩЕНИЕ" in sent[0] and "3/4" in sent[0]
    sent2 = []
    assert ts.tick(send_fn=sent2.append) == 0   # повтора нет
    assert _events().count("EXHAUSTION") == 1


def test_disabled_config_silences(monkeypatch):
    ts.CONFIG.write_text(json.dumps({"enabled": False}), encoding="utf-8")
    _patch_analyze(monkeypatch, {"pos": "LONG", "px": 1900.0, "stop": 1820.0,
                                 "adx": 25.0})
    sent = []
    assert ts.tick(send_fn=sent.append) == 0
    assert not sent


def test_summarize_reads_journal(monkeypatch):
    ts.JOURNAL.write_text("\n".join([
        json.dumps({"event": "ENTRY", "symbol": "ETHUSDT"}),
        json.dumps({"event": "EXIT", "symbol": "ETHUSDT", "pnl_pct": 8.0}),
        json.dumps({"event": "EXIT", "symbol": "ETHUSDT", "pnl_pct": -3.0}),
    ]) + "\n", encoding="utf-8")
    s = ts.summarize()
    assert s["n"] == 2 and s["wr_pct"] == 50 and s["total_pct"] == 5.0
