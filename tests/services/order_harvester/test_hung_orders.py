"""Кулдаун и подтверждение цены — задача из ТЗ оператора.

«Иногда GinArea не закрывает ордера, которые уже набрали профит. Задача не
моментально, а с каким-то кулдауном анализировать, и если есть такие зависшие
реально прибыльные — закрывать их» (02.08).

Кулдаун здесь же работает защитой: кривая цена держится минуты и не
подтвердится, зависший ордер стоит часами.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from services.order_harvester import loop as oh

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)

# реальный открытый ордер AVAX-бота (шорт), снят с GinArea 2026-08-02
ORDER = {
    "id": "70cbdb0b-99ee-4a71-998d-599f1baa8de6", "side": 2, "price": 6.583,
    "quantity": 23.5, "closedPrice": 6.588, "closedQuantity": 23.5,
    "fee": 0.077409, "isOpen": True, "botId": 5900351455, "profit": None,
    "trigger": {"price": 6.5557188, "quantity": 23.5, "initPrice": 6.583},
}


class FakeAPI:
    def __init__(self, orders):
        self._orders = orders

    def get_orders(self, bot_id, **kw):
        return {"orders": self._orders}


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Своё состояние наблюдения на каждый тест; сеть не трогаем."""
    monkeypatch.setattr(oh, "WATCH_PATH", tmp_path / "watch.json")


@pytest.fixture
def _price(monkeypatch):
    """Цена подтверждена обоими источниками: 6.40 (шорт от 6.588 → плюс)."""
    monkeypatch.setattr(oh, "agreed_price", lambda inst, sym: 6.40)


def test_first_sighting_does_not_close(_price):
    """Увидели плюсовой ордер — НЕ закрываем сразу, ставим на наблюдение."""
    api = FakeAPI([ORDER])
    got = oh._candidates(api, "5900351455", 1.5, "AVAXUSDT",
                         inst_id="AVAX-USDT-SWAP", hold_min=15, now=NOW)
    assert got == []
    watch = json.loads(oh.WATCH_PATH.read_text(encoding="utf-8"))
    assert ORDER["id"] in watch


def test_closes_after_cooldown_holds(_price):
    """Продержался 15 минут в плюсе — вот теперь закрываем."""
    api = FakeAPI([ORDER])
    oh._candidates(api, "5900351455", 1.5, "AVAXUSDT",
                   inst_id="AVAX-USDT-SWAP", hold_min=15, now=NOW)
    got = oh._candidates(api, "5900351455", 1.5, "AVAXUSDT",
                         inst_id="AVAX-USDT-SWAP", hold_min=15,
                         now=NOW + timedelta(minutes=16))
    assert len(got) == 1
    assert got[0]["held_min"] == 16
    assert got[0]["profit_usd"] == pytest.approx(4.42 - 0.155, abs=0.02)


def test_price_spike_does_not_survive_cooldown(_price, monkeypatch):
    """Кривая цена мелькнула и ушла — отсчёт сбрасывается, закрытия нет.

    Ровно тот сценарий, что стоил денег: расчёт показал плюс на неверной цене.
    """
    api = FakeAPI([ORDER])
    oh._candidates(api, "5900351455", 1.5, "AVAXUSDT",
                   inst_id="AVAX-USDT-SWAP", hold_min=15, now=NOW)
    monkeypatch.setattr(oh, "agreed_price", lambda inst, sym: 6.60)  # плюс исчез
    assert oh._candidates(api, "5900351455", 1.5, "AVAXUSDT",
                          inst_id="AVAX-USDT-SWAP", hold_min=15,
                          now=NOW + timedelta(minutes=5)) == []
    assert ORDER["id"] not in json.loads(oh.WATCH_PATH.read_text(encoding="utf-8"))
    # цена вернулась — отсчёт начинается заново, мгновенного закрытия нет
    monkeypatch.setattr(oh, "agreed_price", lambda inst, sym: 6.40)
    assert oh._candidates(api, "5900351455", 1.5, "AVAXUSDT",
                          inst_id="AVAX-USDT-SWAP", hold_min=15,
                          now=NOW + timedelta(minutes=20)) == []


def test_unconfirmed_price_blocks_everything(monkeypatch):
    """Источники цены разошлись → не действуем вовсе."""
    monkeypatch.setattr(oh, "agreed_price", lambda inst, sym: None)
    assert oh._candidates(FakeAPI([ORDER]), "5900351455", 1.5, "AVAXUSDT",
                          inst_id="AVAX-USDT-SWAP", hold_min=15, now=NOW) == []


def test_price_divergence_rejected(monkeypatch):
    """Сверка двух источников: расхождение больше 0.3% = цена недостоверна."""
    monkeypatch.setattr(oh, "okx_price", lambda inst, **kw: 6.40)
    monkeypatch.setattr(oh, "market_mark", lambda sym, **kw: 6.50)   # +1.6%
    assert oh.agreed_price("AVAX-USDT-SWAP", "AVAXUSDT") is None
    monkeypatch.setattr(oh, "market_mark", lambda sym, **kw: 6.41)   # +0.16%
    assert oh.agreed_price("AVAX-USDT-SWAP", "AVAXUSDT") == 6.40


def test_no_second_source_means_no_action(monkeypatch):
    monkeypatch.setattr(oh, "okx_price", lambda inst, **kw: 6.40)
    monkeypatch.setattr(oh, "market_mark", lambda sym, **kw: None)
    assert oh.agreed_price("AVAX-USDT-SWAP", "AVAXUSDT") is None


def test_order_past_own_take_profit_is_the_target_case():
    """Ордер ушёл ЗА свой тейк, а бот держит (ждёт среднюю) — то, что ищем."""
    f = oh.order_fields(ORDER)
    assert oh.past_own_trigger(6.40, f) is True     # шорт, рынок ниже тейка
    assert oh.past_own_trigger(6.58, f) is False    # ещё не дошёл
