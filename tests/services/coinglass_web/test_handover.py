"""Экспорт сверки настроек для GPT и журнал доставки сводки — синтетика."""
import hashlib
import json

from services.coinglass_web import handover, section


def ctl(t, sel=None, pressed=None):
    return {"t": t, "cls": "", "sel": sel, "pressed": pressed}


HEATMAP = {"controls": [ctl("Accept"), ctl("Модель 1", sel="true"), ctl("Модель 2", sel="false"),
                        ctl("Пара", sel="true"), ctl("Символ", sel="false"), ctl("Binance BTC/USDT Бессрочный"),
                        ctl("24 час")],
           "checkboxes": [{"checked": True, "label": "Карта Ликвидаций"}], "threshold": "0.85"}
EXPECTED = {"model": 1, "mode": "pair", "exchange": "Binance", "symbol": "BTCUSDT_perpetual", "window": "24h",
            "threshold": 0.85, "liquidation_map": True, "captured_at_ms": 1}


def test_heatmap_settings_match_reference():
    obs, ev = handover.derive("liq_heatmap", HEATMAP, {})
    assert set(handover.compare(EXPECTED, obs).values()) == {"match"}
    assert any("0.85" in e for e in ev)


def test_unchecked_map_and_missing_field_are_not_silently_matched():
    seen = dict(HEATMAP, checkboxes=[{"checked": False, "label": "Карта Ликвидаций"}],
                controls=[c for c in HEATMAP["controls"] if c["t"] != "24 час"])
    res = handover.compare(EXPECTED, handover.derive("liq_heatmap", seen, {})[0])
    assert res["liquidation_map"] == "mismatch" and res["window"] == "unknown"


def test_book_and_depth_delta():
    book = {"controls": [ctl("Binance BTCUSDT Бессрочный"), ctl("5 минута"), ctl("Уровень слияния : 1")]}
    obs = handover.derive("book_heatmap", book, {})[0]
    assert obs == {"exchange": "Binance", "symbol": "BTCUSDT_perpetual", "bar_interval": "5m", "merge": 1}
    dd = {"controls": [ctl("5"), ctl("Доллары"), ctl("15 минута"), ctl("Spot"), ctl("BTC"), ctl("1%"), ctl("Дельта"),
                       ctl("5"), ctl("Доллары"), ctl("1 час"), ctl("Binance BTC/USDT Бессрочный")]}
    obs = handover.derive("depth_delta", dd, {})[0]
    assert obs == {"currency": "USD", "bar_interval": "15m", "market": "Spot", "symbol": "BTC", "range_percent": 1,
                   "mode": "Delta"}                                  # вторая панель (фьючерс, 1 час) не смешивается


def test_evidence_hides_prices_keeps_settings():
    assert handover._clean("Binance\nBTCUSDT\n81 062,2") == "Binance BTCUSDT <num>"
    assert handover._clean("Порог ликвидности = 0.85") == "Порог ликвидности = 0.85"


def test_delivery_log_records_hashes_without_ids(tmp_path, monkeypatch):
    from services import regime_watch
    monkeypatch.setattr(regime_watch, "DELIVERY_LOG", tmp_path / "d.jsonl")
    section.LAST.clear()
    section.LAST.update(snapshot_run_id="2026-10-19T05:00:03+00:00", section_sha256="s" * 64)
    card = "карточка\n🧲 CoinGlass (Binance BTC, снимок 07:00):"
    sent = []
    monkeypatch.setattr(regime_watch, "_card_push_enabled", lambda: True)
    monkeypatch.setattr(regime_watch, "build_card", lambda now: card)
    monkeypatch.setattr(regime_watch, "CARD_STATE", tmp_path / "card.json")
    from datetime import datetime, timezone
    assert regime_watch.maybe_send_regime_card(send_fn=sent.append, now=datetime(2026, 10, 19, 6, 5, tzinfo=timezone.utc))
    rec = json.loads((tmp_path / "d.jsonl").read_text().splitlines()[0])
    assert rec["card_sha256"] == hashlib.sha256(card.encode()).hexdigest() and rec["coinglass_block_in_card"]
    assert rec["snapshot_run_id"] == "2026-10-19T05:00:03+00:00" and rec["date"] == "2026-10-19"
    assert not any("chat" in k for k in rec)
