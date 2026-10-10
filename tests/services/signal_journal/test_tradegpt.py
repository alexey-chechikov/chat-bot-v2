"""Разбор и журнал сигналов TradeGPT (пример оператора 10.10.2026)."""
import json

from services.signal_journal import tradegpt as tg

SAMPLE = """TradeGPT открытие сигнала
Контрактная пара: AAVEUSDT
Входная цена: 171.6 USDT
Направление: снижается
Плечо: 5
💰AI сигнал:
Разворот формы, в течение последних 6 часов, объем торговли возрастает, текущий MACD разворачивается, показывает снижается
Перейти к контрактной торговле"""


def test_parse_operator_sample():
    assert tg.is_tradegpt(SAMPLE)
    s = tg.parse(SAMPLE)
    assert s["symbol"] == "AAVEUSDT" and s["side"] == "SHORT" and s["price"] == 171.6 and s["leverage"] == 5
    assert "MACD" in s["why"]


def test_long_and_not_tradegpt():
    long_text = SAMPLE.replace("Направление: снижается", "Направление: растёт")
    assert tg.parse(long_text)["side"] == "LONG"
    assert not tg.is_tradegpt("LEVELS BTCUSD poc=1")


def test_record_dedup_and_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(tg, "JOURNAL", tmp_path / "j.jsonl")
    prices = {0: 100.0, 1: 99.0, 4: 98.0, 24: 101.0}
    t0 = 1_790_000_000.0

    def fake_price(symbol, ts):
        return prices[round((ts - t0) / 3600)]
    monkeypatch.setattr(tg, "price_at", fake_price)
    assert tg.record(SAMPLE, t0)["side"] == "SHORT"
    assert tg.record(SAMPLE, t0)["duplicate"]
    rows = tg.update_outcomes(now=t0 + 25 * 3600)
    assert rows[0]["p4"] == 98.0
    text = tg.summary()
    assert "через 4 ч: 1 шт., угадано 1" in text and "через 24 ч: 1 шт., угадано 0" in text
    assert len((tmp_path / "j.jsonl").read_text().splitlines()) == 1
