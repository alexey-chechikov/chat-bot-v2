"""Порог считается ПО КАЖДОМУ боту, закрытие частичное 10→20%.

Оператор 2026-08-27: «это 10 процентов должно быть на каждом боте, а не
суммарно — если на одном 6, а на другом 4/5, ничего не должно
закрываться; и после 10 мы закрываем только частично до 20 процентов».
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from services.risk_guard import loop as rg

NOW = datetime.now(timezone.utc)
A, B = "4696727145", "4470088018"
PRICES = {"A-SWAP": 1000.0, "B-SWAP": 1000.0}
DEP = 2000.0


@pytest.fixture(autouse=True)
def _iso(monkeypatch, tmp_path):
    for name in ("CONFIG_PATH", "JOURNAL_PATH", "FROZEN_PATH", "ALERT_STATE",
                 "BREACH_STATE", "REDUCE_STATE"):
        monkeypatch.setattr(rg, name, tmp_path / f"{name.lower()}.json")
    monkeypatch.setattr(rg, "move_character", lambda *a, **k: None)
    monkeypatch.setattr(rg, "_price_of", lambda api, inst: PRICES.get(inst))
    monkeypatch.setattr("services.short_bots_guard.control.pause_bot",
                        lambda bot_id, **kw: {"action": "paused"})


def _cfg(**over):
    cfg = {"enabled": True, "deposit_usd": DEP, "warn_pct": 5,
           "kill_pct": 10, "full_close_pct": 20,
           "first_close_fraction": 0.25, "portfolio_kill_pct": 30,
           "max_leverage": 99, "max_stale_minutes": 15, "allow_close": True,
           "persistence": {"min_hold_minutes": 0},
           "bots": {A: {"alias": "A", "inst_id": "A-SWAP"},
                    B: {"alias": "B", "inst_id": "B-SWAP"}}}
    cfg.update(over)
    rg.CONFIG_PATH.write_text(json.dumps(cfg), encoding="utf-8")
    return cfg


def _bot(bid, pos, cur):
    stat = SimpleNamespace(position=pos, profit=0.0, currentProfit=cur,
                           updatedAt=NOW - timedelta(minutes=1))
    return SimpleNamespace(id=int(bid), status=2, stat=stat)


class API:
    def __init__(self, bots, orders=None):
        self._bots = bots
        self._orders = orders or []
        self.closed: list[int] = []
        self.closed_orders: list[str] = []

    def list_bots(self):
        return self._bots

    def close_position(self, bot_id):
        self.closed.append(int(bot_id))
        return {}

    def get_orders(self, bot_id, **kw):
        return {"orders": self._orders, "totalCount": len(self._orders)}

    def close_order(self, bot_id, order_id):
        self.closed_orders.append(order_id)
        return {}


def _ord(oid, entry, qty):
    return {"id": oid, "side": 2, "price": entry, "quantity": qty,
            "closedPrice": entry, "fee": entry * qty * 0.0005,
            "feeExchangeCurrencyId": 11, "isOpen": True, "profit": None,
            "trigger": {"price": entry}}


def _events():
    if not rg.JOURNAL_PATH.exists():
        return []
    return [json.loads(l) for l in rg.JOURNAL_PATH.read_text().splitlines()]


# ─── ровно случай оператора ──────────────────────────────────────────────
def test_six_and_five_percent_close_nothing():
    """«Если на одном 6, а на другом 4/5 — ничего не должно закрываться»."""
    cfg = _cfg()
    api = API([_bot(A, -0.5, -DEP * 0.06),      # −6%
               _bot(B, -0.5, -DEP * 0.05)])     # −5%, сумма −11%
    d = rg.evaluate(rg.snapshot(api, cfg), cfg)
    assert d["action"] != "KILL", "по сумме 11%, но каждый ниже 10%"
    assert rg.tick(api=api) != "kill"
    assert api.closed == [] and api.closed_orders == []


def test_only_the_breaching_bot_is_touched():
    """Здоровый сосед не должен страдать за больного."""
    cfg = _cfg()
    api = API([_bot(A, -0.5, -DEP * 0.12),      # −12%, за порогом
               _bot(B, -0.5, -DEP * 0.03)],     # −3%, здоров
              orders=[_ord("o1", 1200.0, 1.0), _ord("o2", 1100.0, 1.0)])
    assert rg.tick(api=api) == "kill"
    ev = _events()[-1]
    aliases = [t["alias"] for t in ev["targets"]]
    assert aliases == ["A"], f"тронут только A, а не {aliases}"


# ─── частичное закрытие 10 -> 20% ────────────────────────────────────────
@pytest.mark.parametrize("pct,frac", [
    (-9.9, 0.0),      # ниже порога — не режем
    (-10.0, 0.25),    # на пороге — четверть
    (-15.0, 0.625),   # середина
    (-20.0, 1.0),     # верхняя граница — всё
    (-35.0, 1.0),     # глубже — тоже всё
])
def test_close_fraction_scales_between_10_and_20(pct, frac):
    assert rg.close_fraction_for(pct, _cfg()) == pytest.approx(frac, abs=0.01)


def test_partial_close_uses_orders_not_whole_position():
    """На 12% режем часть книги, позицию целиком не закрываем."""
    _cfg()
    api = API([_bot(A, -1.0, -DEP * 0.12)],
              orders=[_ord("deep", 1300.0, 1.0), _ord("near", 1010.0, 1.0)])
    assert rg.tick(api=api) == "kill"
    assert api.closed == [], "позицию целиком закрывать рано"
    assert api.closed_orders, "часть ордеров должна закрыться"
    assert not rg.is_frozen(), "частичное сокращение — штатная работа"


def test_full_close_at_twenty_percent():
    _cfg()
    api = API([_bot(A, -1.0, -DEP * 0.21)])
    assert rg.tick(api=api) == "kill"
    assert api.closed == [int(A)], "на 20% закрываем позицию целиком"


# ─── страховка портфеля ──────────────────────────────────────────────────
def test_portfolio_backstop_catches_many_small():
    """Дыра по-ботового правила: много ботов чуть ниже порога.

    К концу августа XRP замер на −9.1% и по-ботовое правило не тронуло бы
    его никогда. Шесть таких — 54% депозита без срабатываний.
    """
    cfg = _cfg(portfolio_kill_pct=30)
    api = API([_bot(A, -0.5, -DEP * 0.09),
               _bot(B, -0.5, -DEP * 0.09)])     # каждый ниже 10, сумма 18%
    assert rg.evaluate(rg.snapshot(api, cfg), cfg)["action"] != "KILL"

    api2 = API([_bot(A, -0.5, -DEP * 0.09),
                _bot(B, -0.5, -DEP * 0.09)])
    cfg2 = _cfg(portfolio_kill_pct=15)
    d = rg.evaluate(rg.snapshot(api2, cfg2), cfg2)
    assert d["action"] == "KILL" and "страховка" in d["reason"]
