"""Scalp liq-свип: кластеризация, continuation-полярность карточки, TG-гейт, журнал."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from services.scalp_liq import loop as sl


def test_cluster_vwap_and_sums():
    liqs = [("long", 1.0, 63000.0), ("long", 1.0, 63200.0), ("short", 0.5, 64000.0)]
    c = sl._cluster(liqs)
    assert c["long"][0] == 2.0
    assert abs(c["long"][1] - 63100.0) < 1e-6   # vwap
    assert c["short"][0] == 0.5


def test_build_card_long_sweep_continuation():
    """2026-07-07: полярность перевёрнута — live-журнал (221 свип) опроверг «отбой вверх»:
    WR отбоя 37%@30м, свип = continuation. Карточка обязана читаться как давление ВНИЗ."""
    ctx = {"oi_1h": -0.5, "funding": -0.00006, "taker": 38.0}
    card = sl.build_card("long", 6.3, 63000.0, ctx)
    assert "ЛОНГОВ выбито" in card and "ВНИЗ" in card and "ПРОДОЛЖАЕТСЯ" in card
    assert "НЕ зона лонга" in card
    assert "отбоя ВВЕРХ" not in card            # старое чтение не должно вернуться
    assert "делеверидж" in card                 # OI -0.5 < -0.3
    assert "taker buy 38%" in card
    assert "/levels" in card and "НЕ сигнал входа" in card


def test_build_card_short_sweep_continuation():
    card = sl.build_card("short", 5.8, 64500.0, {"oi_1h": 0.6, "funding": 0.0001, "taker": 62.0})
    assert "ШОРТОВ выбито" in card and "ВВЕРХ" in card and "ПРОДОЛЖАЕТСЯ" in card
    assert "НЕ зона шорта" in card and "отката ВНИЗ" not in card
    assert "набор→тренд" in card                # OI +0.6 > 0.3


def test_build_card_live_stats_line():
    stats = {"n": 121, "cont_wr": 63.0, "avg_move": 0.21}
    card = sl.build_card("long", 6.0, 63000.0, {}, stats=stats)
    assert "живой журнал (121 свипов)" in card
    assert "продолжение вниз 63% @30м" in card


def test_live_stats_needs_min_sample(monkeypatch, tmp_path):
    jp = tmp_path / "j.jsonl"
    rec = {"side": "long", "outcomes": {"30м": -0.2}}
    jp.write_text("\n".join(json.dumps(rec) for _ in range(sl.STATS_MIN_N - 1)) + "\n",
                  encoding="utf-8")
    monkeypatch.setattr(sl, "JOURNAL", jp)
    assert sl._live_stats("long") is None
    jp.write_text("\n".join(json.dumps(rec) for _ in range(sl.STATS_MIN_N)) + "\n",
                  encoding="utf-8")
    s = sl._live_stats("long")
    assert s and s["n"] == sl.STATS_MIN_N
    assert s["cont_wr"] == 100.0                # все исходы < 0 = всё continuation
    assert abs(s["avg_move"] - 0.2) < 1e-9


def _patch_env(monkeypatch, tmp_path, state):
    """detect() пишет в реальные STATE/JOURNAL — в тестах ВСЕГДА подменяем
    (2026-07-07: старый тест загадил боевой журнал фейковым свипом)."""
    jp = tmp_path / "journal.jsonl"
    monkeypatch.setattr(sl, "JOURNAL", jp)
    monkeypatch.setattr(sl, "_read_state", lambda: state)
    monkeypatch.setattr(sl, "_write_state", lambda s: state.update(s))
    monkeypatch.setattr(sl, "_deriv_ctx", lambda: {})
    monkeypatch.setattr(sl, "_live_stats", lambda side: None)
    return jp


def test_detect_below_threshold_silent(monkeypatch, tmp_path):
    state: dict = {}
    jp = _patch_env(monkeypatch, tmp_path, state)
    now = datetime(2026, 6, 19, 16, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(sl, "_read_recent", lambda n: [("long", 0.5, 63000.0)])
    sent: list[str] = []
    assert sl.detect(sent.append, now) == []
    assert not sent and not jp.exists()


def test_detect_journals_small_sweep_without_tg(monkeypatch, tmp_path):
    """1.5 ≤ qty < SEND_MIN_QTY_BTC: журналим (данные), но TG молчит — анти-спам гейт."""
    state: dict = {}
    jp = _patch_env(monkeypatch, tmp_path, state)
    now = datetime(2026, 6, 19, 16, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(sl, "_read_recent", lambda n: [("long", 2.0, 63000.0)])
    sent: list[str] = []
    fired = sl.detect(sent.append, now)
    assert fired == [] and sent == []
    assert len(jp.read_text().splitlines()) == 1        # но в журнале есть


def test_detect_big_sweep_sends_and_escalates(monkeypatch, tmp_path):
    state: dict = {}
    _patch_env(monkeypatch, tmp_path, state)
    now = datetime(2026, 6, 19, 16, 0, tzinfo=timezone.utc)
    sent: list[str] = []

    # крупный свип (≥ SEND_MIN_QTY_BTC) → отправка
    q1 = sl.SEND_MIN_QTY_BTC + 1.0
    monkeypatch.setattr(sl, "_read_recent", lambda n: [("long", q1, 63000.0)])
    fired = sl.detect(sent.append, now)
    assert len(fired) == 1 and "ЛОНГОВ выбито" in fired[0]

    # тот же масштаб через 40 мин: журнальный cooldown прошёл, но send-cooldown держит
    later = now + timedelta(minutes=40)
    monkeypatch.setattr(sl, "_read_recent", lambda n: [("long", q1 + 1.0, 62800.0)])
    assert sl.detect(sent.append, later) == []

    # эскалация ≥2× последней отправленной qty пробивает cooldown
    q3 = q1 * 2.5
    monkeypatch.setattr(sl, "_read_recent", lambda n: [("long", q3, 62500.0)])
    fired = sl.detect(sent.append, later + timedelta(minutes=20))
    assert len(fired) == 1 and f"{q3:.2f} BTC" in fired[0]


def test_fill_outcomes_sign_favors_bounce(monkeypatch, tmp_path):
    """Знак исхода в журнале — в пользу ОТБОЯ (не continuation): long-liq + рост = плюс.
    На этом знаке стоит _live_stats (continuation = v < 0) — не менять молча."""
    jp = tmp_path / "j.jsonl"
    now = datetime(2026, 6, 19, 16, 0, tzinfo=timezone.utc)
    rec = {"id": "x", "ts": (now - timedelta(minutes=70)).isoformat(), "side": "long",
           "qty": 2.0, "price": 63000.0, "ctx": {}, "outcomes": {}}
    jp.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    monkeypatch.setattr(sl, "JOURNAL", jp)
    monkeypatch.setattr(sl, "_btc_price_now", lambda: 63630.0)  # +1.0% вверх
    n = sl.fill_outcomes(now)
    assert n == 3  # 15/30/60м заполнены
    out = json.loads(jp.read_text().splitlines()[0])["outcomes"]
    assert out["60м"] > 0.9
