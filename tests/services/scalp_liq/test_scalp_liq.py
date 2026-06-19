"""Scalp liq-свип: кластеризация, порог, карточка с OI/funding/taker контекстом."""
from __future__ import annotations

from services.scalp_liq import loop as sl


def test_cluster_vwap_and_sums():
    liqs = [("long", 1.0, 63000.0), ("long", 1.0, 63200.0), ("short", 0.5, 64000.0)]
    c = sl._cluster(liqs)
    assert c["long"][0] == 2.0
    assert abs(c["long"][1] - 63100.0) < 1e-6   # vwap
    assert c["short"][0] == 0.5


def test_build_card_long_sweep_support():
    ctx = {"oi_1h": -0.5, "funding": -0.00006, "taker": 38.0}
    card = sl.build_card("long", 2.3, 63000.0, ctx)
    assert "ЛОНГОВ выбито" in card and "ПОДДЕРЖКИ" in card and "отбоя ВВЕРХ" in card
    assert "делеверидж" in card        # OI -0.5 < -0.3
    assert "taker buy 38%" in card
    assert "/levels" in card


def test_build_card_short_sweep_resistance():
    card = sl.build_card("short", 1.8, 64500.0, {"oi_1h": 0.6, "funding": 0.0001, "taker": 62.0})
    assert "ШОРТОВ выбито" in card and "СОПРОТИВЛЕНИЯ" in card and "отката ВНИЗ" in card
    assert "набор→тренд" in card       # OI +0.6 > 0.3


def test_fill_outcomes_bounce_direction(monkeypatch, tmp_path):
    import json
    from datetime import datetime, timezone, timedelta
    jp = tmp_path / "j.jsonl"
    now = datetime(2026, 6, 19, 16, 0, tzinfo=timezone.utc)
    # long-liq свип @63000 (ждём ВВЕРХ), записан 70 мин назад
    rec = {"id": "x", "ts": (now - timedelta(minutes=70)).isoformat(), "side": "long",
           "qty": 2.0, "price": 63000.0, "ctx": {}, "outcomes": {}}
    jp.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    monkeypatch.setattr(sl, "JOURNAL", jp)
    monkeypatch.setattr(sl, "_btc_price_now", lambda: 63630.0)  # +1.0% ВВЕРХ = в пользу свипа
    n = sl.fill_outcomes(now)
    assert n == 3  # 15/30/60м заполнены
    out = json.loads(jp.read_text().splitlines()[0])["outcomes"]
    assert out["60м"] > 0.9   # long-liq + цена выросла = положительный исход


def test_detect_threshold_and_cooldown(monkeypatch):
    sent = []
    now = __import__("datetime").datetime(2026, 6, 19, 16, 0, tzinfo=__import__("datetime").timezone.utc)
    # ниже порога 1.5 → молчим
    monkeypatch.setattr(sl, "_read_recent", lambda n: [("long", 0.5, 63000.0)])
    monkeypatch.setattr(sl, "_read_state", lambda: {})
    monkeypatch.setattr(sl, "_write_state", lambda s: None)
    monkeypatch.setattr(sl, "_deriv_ctx", lambda: {})
    assert sl.detect(sent.append, now) == []
    # выше порога → пинг
    monkeypatch.setattr(sl, "_read_recent", lambda n: [("long", 2.0, 63000.0)])
    fired = sl.detect(sent.append, now)
    assert fired and "ЛОНГОВ выбито" in fired[0]
