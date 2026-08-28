"""Выдержка не должна теряться от колебания вокруг порога.

Замер по логу 2026-08-28: 40% ордеров (12 из 30) теряли отсчёт хотя бы
раз, худший перезапускался ТРИНАДЦАТЬ раз и закрылся через три часа
вместо пятнадцати минут. Медианный профит в момент сброса $2.13 при
пороге $2.

Выдержка задумывалась как защита от кривой цены, а не как требование
идеального постоянства.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from services.order_harvester import loop as oh

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
BOT = "4696727145"


@pytest.fixture(autouse=True)
def _iso(monkeypatch, tmp_path):
    monkeypatch.setattr(oh, "WATCH_PATH", tmp_path / "watch.json")
    monkeypatch.setattr(oh, "agreed_price", lambda inst, sym: 79_000.0)


def _order(oid, entry, qty=0.008):
    return {"id": oid, "side": 2, "price": entry, "quantity": qty,
            "closedPrice": entry, "fee": entry * qty * 0.0005,
            "feeExchangeCurrencyId": 11, "isOpen": True, "profit": None,
            "trigger": {"price": entry}}


class API:
    def __init__(self, orders):
        self.orders = orders

    def get_orders(self, bot_id, **kw):
        return {"orders": self.orders, "totalCount": len(self.orders)}


def _entry_for(profit_usd, qty=0.008, mark=79_000.0):
    """Цена входа шорта, дающая нужный профит после двух комиссий."""
    # profit = (entry - mark)*qty - 2*fee, fee = entry*qty*0.0005
    # => entry*(qty - 0.001*qty) = profit + mark*qty
    return (profit_usd + mark * qty) / (qty * 0.999)


def _run(api, at, hold=15.0, thr=2.0):
    return oh._candidates(api, BOT, thr, "BTCUSDT", inst_id="BTC-USDT-SWAP",
                          hold_min=hold, now=at)


def test_dip_below_threshold_keeps_the_hold():
    """Профит просел с $2.15 до $2.05 — отсчёт продолжается."""
    api = API([_order("a", _entry_for(2.15))])
    _run(api, NOW)                                   # завели наблюдение
    api.orders = [_order("a", _entry_for(2.05))]     # просел, но выше 70%
    _run(api, NOW + timedelta(minutes=5))
    w = json.loads(oh.WATCH_PATH.read_text(encoding="utf-8"))
    since = datetime.fromisoformat(w["a"]["since"])
    assert since == NOW, "отсчёт обязан идти с первого раза"


def test_deep_drop_resets_the_hold():
    """Провал ниже 70% порога — это уже не колебание, отсчёт заново."""
    api = API([_order("a", _entry_for(2.15))])
    _run(api, NOW)
    api.orders = [_order("a", _entry_for(1.0))]      # ниже $1.40
    _run(api, NOW + timedelta(minutes=5))
    assert "a" not in json.loads(oh.WATCH_PATH.read_text(encoding="utf-8"))


def test_closes_after_hold_when_above_threshold():
    api = API([_order("a", _entry_for(2.15))])
    _run(api, NOW)
    got = _run(api, NOW + timedelta(minutes=20))
    assert [f["order_id"] for f in got] == ["a"]


def test_does_not_close_while_below_threshold_now():
    """Выдержка набрана, но профит сейчас ниже порога — не закрываем."""
    api = API([_order("a", _entry_for(2.15))])
    _run(api, NOW)
    api.orders = [_order("a", _entry_for(1.6))]      # держим, но не берём
    got = _run(api, NOW + timedelta(minutes=20))
    assert got == []
    assert "a" in json.loads(oh.WATCH_PATH.read_text(encoding="utf-8")), \
        "наблюдение должно сохраниться"


def test_oscillation_around_threshold_still_closes():
    """Ровно случай из лога: колебание $2.03-2.35 больше не мешает."""
    api = API([_order("a", _entry_for(2.33))])
    _run(api, NOW)
    for k, p in enumerate((2.03, 2.13, 2.09, 2.10, 2.28, 2.08), start=1):
        api.orders = [_order("a", _entry_for(p))]
        _run(api, NOW + timedelta(minutes=2 * k))
    api.orders = [_order("a", _entry_for(2.35))]
    got = _run(api, NOW + timedelta(minutes=20))
    assert [f["order_id"] for f in got] == ["a"], \
        "после шести колебаний ордер обязан закрыться"
