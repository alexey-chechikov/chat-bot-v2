"""Теневой хедж: считает верно и НЕ торгует.

Конструкция по указанию оператора 30.08: кроем ДРУГИМ контрактом того же
актива (линейную сетку — инверсным), потому что на одном инструменте в
net-режиме OKX встречный ордер уменьшил бы позицию самого бота.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from services.hedge_shadow import loop as hs

PRICES = {"BTC-USDT-SWAP": 80_000.0, "ETH-USDT-SWAP": 2_500.0,
          "BTC-USD-SWAP": 79_995.0}


@pytest.fixture(autouse=True)
def _iso(monkeypatch, tmp_path):
    monkeypatch.setattr(hs, "CONFIG_PATH", tmp_path / "cfg.json")
    monkeypatch.setattr(hs, "JOURNAL_PATH", tmp_path / "j.jsonl")
    monkeypatch.setattr(hs, "STATE_PATH", tmp_path / "st.json")
    monkeypatch.setattr("services.order_harvester.loop.okx_price",
                        lambda inst, **kw: PRICES.get(inst))


def _cfg(**over):
    cfg = {"enabled": True, "rebalance_band": 0.05, "min_trade_usd": 50.0,
           "lot_usd": 0.0, "hedge_floor_usd": 0.0,
           "fee_side_pct": 0.05,
           "bots": {"1": {"alias": "BTC", "inst_id": "BTC-USDT-SWAP",
                          "hedge_inst_id": "BTC-USD-SWAP",
                          "inverse": False}}}
    cfg.update(over)
    hs.CONFIG_PATH.write_text(json.dumps(cfg), encoding="utf-8")
    return cfg


class API:
    def __init__(self, pos):
        self.pos = pos
        self.orders_placed = []          # должен остаться пустым всегда

    def get_stat(self, bot_id):
        return SimpleNamespace(position=self.pos)


def _events():
    if not hs.JOURNAL_PATH.exists():
        return []
    return [json.loads(l) for l in hs.JOURNAL_PATH.read_text().splitlines()]


# ─── арифметика хеджа ────────────────────────────────────────────────────
def test_hedge_is_opposite_of_position():
    d = hs.compute_hedge(-0.05, 80_000.0, 0.0, _cfg())
    assert d["want_hedge"] == 0.05, "шорт сетки кроется лонгом"
    assert d["side"] == "buy"
    assert d["should_rebalance"] is True


def test_long_grid_hedged_by_short():
    d = hs.compute_hedge(0.05, 80_000.0, 0.0, _cfg())
    assert d["want_hedge"] == -0.05
    assert d["side"] == "sell"


def test_net_exposure_is_zero_when_hedged():
    d = hs.compute_hedge(-0.05, 80_000.0, 0.05, _cfg())
    assert d["net_exposure_coin"] == pytest.approx(0.0)
    assert d["should_rebalance"] is False


def test_small_drift_inside_band_is_ignored():
    """Отклонение 2% при полосе 5% — не трогаем."""
    d = hs.compute_hedge(-0.051, 80_000.0, 0.05, _cfg())
    assert d["should_rebalance"] is False


def test_size_is_quantised_to_lot():
    """Минимальный контракт BTC-USD-SWAP $100 — дробить нельзя.

    Оператор 31.08: «минимальный ордер там 100 долларов, что нужно
    учитывать при настройках».
    """
    cfg = _cfg(hedge_floor_usd=0.0, lot_usd=100.0)
    # −0.0505 BTC при 80 000 = $4 040 -> округляется до $4 000
    d = hs.compute_hedge(-0.0505, 80_000.0, 0.0, cfg)
    assert d["want_hedge"] * 80_000.0 == pytest.approx(4000.0, abs=1.0)


def test_tiny_drift_disappears_after_quantisation():
    """Дельта в $40 меньше лота и обязана исчезнуть, а не породить сделку."""
    cfg = _cfg(rebalance_band=0.0001, hedge_floor_usd=0.0, lot_usd=100.0)
    d = hs.compute_hedge(-0.0505, 80_000.0, 0.05, cfg)
    assert d["should_rebalance"] is False


def test_small_position_is_not_hedged_at_all():
    """Порог $5 000: мелкую позицию не хеджируем — перебалансировка стоит
    два плеча, а направленный риск в ней ничтожен. Замер: выгода та же,
    что при нулевом пороге, но смен 26 вместо 79."""
    cfg = _cfg(hedge_floor_usd=5000.0)
    d = hs.compute_hedge(-0.01, 80_000.0, 0.0, cfg)   # позиция $800
    assert d["want_hedge"] == 0.0
    assert d["should_rebalance"] is False


def test_large_position_crosses_the_floor():
    cfg = _cfg(hedge_floor_usd=5000.0)
    d = hs.compute_hedge(-0.1, 80_000.0, 0.0, cfg)    # позиция $8 000
    assert d["want_hedge"] * 80_000.0 == pytest.approx(8000.0, abs=1.0)
    assert d["should_rebalance"] is True


def test_hedge_removed_when_position_drops_below_floor():
    """Позиция ушла под порог — хедж снимаем, иначе он голая ставка."""
    cfg = _cfg(hedge_floor_usd=5000.0)
    d = hs.compute_hedge(-0.01, 80_000.0, 0.1, cfg)
    assert d["want_hedge"] == 0.0
    assert d["should_rebalance"] is True
    assert d["side"] == "sell"


def test_big_drift_triggers():
    d = hs.compute_hedge(-0.08, 80_000.0, 0.05, _cfg())
    assert d["should_rebalance"] is True
    assert d["delta_usd"] == pytest.approx(2400.0, abs=1)


# ─── служба ──────────────────────────────────────────────────────────────
def test_tick_journals_but_never_trades():
    _cfg()
    api = API(-0.05)
    assert hs.tick(api=api).startswith("acted")
    assert api.orders_placed == [], "теневая служба не торгует"
    ev = _events()[-1]
    assert ev["event"] == "WOULD_REBALANCE"
    assert ev["side"] == "buy"


def test_hedge_goes_to_the_other_contract():
    """Оператор 30.08: кроем другим контрактом, не тем же инструментом."""
    _cfg()
    hs.tick(api=API(-0.05))
    ev = _events()[-1]
    assert ev["grid_inst"] == "BTC-USDT-SWAP"
    assert ev["hedge_inst"] == "BTC-USD-SWAP"
    assert ev["grid_inst"] != ev["hedge_inst"]


def test_hedge_instrument_derived_when_not_configured():
    _cfg(bots={"1": {"alias": "ETH", "inst_id": "ETH-USDT-SWAP",
                     "inverse": False}})
    hs.tick(api=API(-1.0))
    assert _events()[-1]["hedge_inst"] == "ETH-USD-SWAP"


def test_disabled_does_nothing():
    _cfg(enabled=False)
    assert hs.tick(api=API(-0.05)) == "disabled"
    assert _events() == []


def test_second_tick_without_drift_does_not_rebalance():
    _cfg()
    api = API(-0.05)
    hs.tick(api=api)
    n = len(_events())
    assert hs.tick(api=api) == "ok"
    assert len(_events()) == n, "без дрейфа второй раз не трогаем"
