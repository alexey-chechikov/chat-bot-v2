"""Тесты CoinGlass не ходят в сеть: Binance REST подменён отказом (тест, которому нужны цены, подаёт свои), повтор
выгрузки без ожидания."""
import pytest

from services.coinglass_web import compare, hypothesis, tv_export


@pytest.fixture(autouse=True)
def _no_network(monkeypatch, tmp_path):
    def refuse(*a, **kw):
        raise RuntimeError("сеть в тестах запрещена")
    monkeypatch.setattr(compare, "_get", refuse)
    monkeypatch.setattr(tv_export, "RETRY_WAIT_MS", 0)
    monkeypatch.setattr(hypothesis, "LOG", tmp_path / "hypothesis_log.jsonl")
