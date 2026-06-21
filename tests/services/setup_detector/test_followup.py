"""Stage 3: intraday follow-up по пушнутым входам — реестр + карточка."""
from __future__ import annotations

from datetime import datetime, timezone

from services.setup_detector import actionable_registry as reg
from services.setup_detector.models import SetupType, SetupBasis, make_setup
from services.setup_detector.telegram_card import format_followup_card


def _mk(stype="short_rally_fade"):
    return make_setup(
        setup_type=SetupType(stype), pair="BTCUSDT", current_price=64800.0,
        regime_label="range_wide", session_label="EU",
        entry_price=64820.0, stop_price=65400.0, tp1_price=63900.0, tp2_price=63200.0,
        risk_reward=1.96, strength=7, confidence_pct=64.0,
        basis=(SetupBasis(label="x", value=1.0, weight=1.0),),
        cancel_conditions=("стоп выше 65,400",), detected_at=datetime.now(timezone.utc))


def test_registry_record_and_pop_once(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "PATH", tmp_path / "pushed.json")
    s = _mk()
    reg.record_pushed(s)
    rec = reg.pop_if_pushed(s.setup_id)
    assert rec is not None and rec["type"] == "short_rally_fade" and rec["dir"] == "SHORT"
    # второй pop — уже None (пинг один раз)
    assert reg.pop_if_pushed(s.setup_id) is None


def test_registry_pop_unknown_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "PATH", tmp_path / "pushed.json")
    assert reg.pop_if_pushed("never-pushed") is None


def test_registry_prunes_old(tmp_path, monkeypatch):
    import time
    monkeypatch.setattr(reg, "PATH", tmp_path / "pushed.json")
    monkeypatch.setattr(reg, "TTL_SEC", 1)
    s = _mk()
    reg.record_pushed(s)
    time.sleep(1.1)
    s2 = _mk("long_pdl_bounce")
    reg.record_pushed(s2)            # запись s протухла и выпилилась
    assert reg.pop_if_pushed(s.setup_id) is None
    assert reg.pop_if_pushed(s2.setup_id) is not None


def test_followup_tp1():
    card = format_followup_card(_mk(), "tp1_hit", pnl_usd=120.0, mins=45)
    assert "✅ TP1 ВЗЯТ" in card and "SHORT BTCUSDT" in card
    assert "+120$" in card and "45мин" in card and "безубыток" in card


def test_followup_stop():
    card = format_followup_card(_mk(), "stop_hit", pnl_usd=-80.0, mins=30)
    assert "❌ ОТМЕНА (стоп)" in card and "-80$" in card and "вне сделки" in card


def test_followup_expired_no_pnl():
    card = format_followup_card(_mk(), "expired", pnl_usd=None, mins=None)
    assert "⏱ ИСТЁК" in card and "цель не достигнута" in card
