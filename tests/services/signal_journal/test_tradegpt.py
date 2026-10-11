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
    # настоящая формулировка лонга у TradeGPT (APR/NIL 11.10) — раньше молча не распознавалась
    real_long = SAMPLE.replace("Направление: снижается", "Направление: возрастает")
    assert tg.parse(real_long)["side"] == "LONG"
    assert not tg.is_tradegpt("LEVELS BTCUSD poc=1")


def test_barrier_rules():
    # шорт от 100: сначала против на 2%, потом вниз на 1.2% → тейк 1% при стопе 3%, но стоп при стопе 2%
    k = [(0, 100, 102, 99.5, 101), (60_000, 101, 101, 98.8, 99)]
    assert tg.barrier(k, -1, 100.0, 1.0, 3.0, expired=False) == (1.0 - tg.FEE, "TP")
    assert tg.barrier(k, -1, 100.0, 1.0, 2.0, expired=False) == (-2.0 - tg.FEE, "SL")
    assert tg.barrier(k, -1, 100.0, 5.0, 5.0, expired=False) == (None, "")   # ещё открыта
    res, why = tg.barrier(k, -1, 100.0, 5.0, 5.0, expired=True)              # 72 ч — по закрытию, НЕ «тейк»
    assert abs(res - (1.0 - tg.FEE)) < 1e-9 and why == "TIME"
    # обе границы в одной минуте — стоп (осторожно)
    assert tg.barrier([(0, 100, 104, 98, 100)], 1, 100.0, 1.0, 1.5, expired=False) == (-1.5 - tg.FEE, "SL")


def test_barrier_gap_not_counted():
    """Пропущенная минута (в ней мог быть стоп) — сделка не засчитывается (разбор GPT 11.10)."""
    k = [(0, 100, 100, 99.9, 100), (120_000, 100, 100, 98.9, 99)]           # минуты 60_000 нет
    assert tg.barrier(k, -1, 100.0, 1.0, 3.0, expired=False, start_ms=0) == (None, "дыра")


def test_entry_is_next_full_minute_after_receipt(tmp_path, monkeypatch):
    """Вход — открытие следующей минуты; high/low минуты до получения не учитываются (разбор GPT 11.10)."""
    monkeypatch.setattr(tg, "JOURNAL", tmp_path / "j.jsonl")
    t0 = 1_790_000_030.0                                                     # сигнал в середине минуты
    asked = {}

    def fake_price(symbol, ts):
        asked.setdefault("p0", ts)
        return 100.0
    monkeypatch.setattr(tg, "price_at", fake_price)

    def fake_klines(symbol, a, b):
        asked["k"] = a
        start = int(a * 1000)
        return [(start, 100, 100.2, 99.5, 99.6)]                             # после получения до тейка не дошло
    monkeypatch.setattr(tg, "klines", fake_klines)
    tg.record(SAMPLE, t0)
    rows = tg.update_outcomes(now=t0 + 2 * 3600)
    assert asked["p0"] == asked["k"] == 1_790_000_040.0                      # следующая полная минута
    assert rows[0].get("tp1_sl3") is None and not rows[0].get("tp1_sl3_why")


def test_virtual_trades_in_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(tg, "JOURNAL", tmp_path / "j.jsonl")
    monkeypatch.setattr(tg, "price_at", lambda s, ts: 100.0)
    monkeypatch.setattr(tg, "klines", lambda s, a, b: [(int(a * 1000), 100, 100.2, 98.9, 99)])  # шорт: −1.1%
    t0 = 1_790_000_000.0
    tg.record(SAMPLE, t0)
    rows = tg.update_outcomes(now=t0 + 2 * 3600)
    assert rows[0]["tp1_sl3"] == 1.0 - tg.FEE and rows[0]["tp1_sl3_why"] == "TP"
    assert rows[0]["tp1_sl5"] == 1.0 - tg.FEE
    assert rows[0].get("tp2_sl5") is None                                    # 2% ещё не дошла, 72 ч не прошли


def test_record_dedup_and_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(tg, "JOURNAL", tmp_path / "j.jsonl")
    prices = {0: 100.0, 1: 99.0, 4: 98.0, 24: 101.0}
    t0 = 1_790_000_000.0

    def fake_price(symbol, ts):
        return prices[round((ts - t0) / 3600)]
    monkeypatch.setattr(tg, "price_at", fake_price)
    monkeypatch.setattr(tg, "klines", lambda s, a, b: [])                     # без сети
    assert tg.record(SAMPLE, t0)["side"] == "SHORT"
    assert tg.record(SAMPLE, t0)["duplicate"]
    rows = tg.update_outcomes(now=t0 + 25 * 3600)
    assert rows[0]["p4"] == 98.0
    text = tg.summary()
    assert "через 4 ч: 1 шт., угадано 1" in text and "через 24 ч: 1 шт., угадано 0" in text
    assert len((tmp_path / "j.jsonl").read_text().splitlines()) == 1
