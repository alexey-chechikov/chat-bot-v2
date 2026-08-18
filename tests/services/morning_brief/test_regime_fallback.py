"""Регрессия 2026-06-10 04:00: «режим BTC недоступен: list index out of range» —
пустой/короткий ответ Bybit ронял секцию РЫНОК. Теперь 3 ретрая + фоллбэк.

2026-08-18: фоллбэком был BitMEX (1h с ресемплом в 4h). Оператор:
«битмекс выключай полностью» — биржа закрывается, держать её последним
рубежом брифа нельзя. Фоллбэк переведён на Binance, который отдаёт 4h
напрямую и используется остальным рантаймом. Старая функция оставлена в
коде как `_bitmex_4h_retired` (справка по ресемплу) и не вызывается.
"""
from __future__ import annotations

import pytest

from services.morning_brief import regime as rg


def _flat_bars(n=250, px=60000.0):
    return [px] * n, [px] * n, [px] * n


def test_fallback_to_binance_when_bybit_fails(monkeypatch):
    monkeypatch.setattr(rg.time, "sleep", lambda s: None)
    calls = {"bybit": 0, "binance": 0}

    def bad_bybit():
        calls["bybit"] += 1
        raise IndexError("list index out of range")

    def good_binance(n4h=250):
        calls["binance"] += 1
        return _flat_bars()

    monkeypatch.setattr(rg, "_bybit_4h", bad_bybit)
    monkeypatch.setattr(rg, "_binance_4h", good_binance)
    r = rg.regime()
    assert calls["bybit"] == 3  # три попытки
    assert calls["binance"] == 1
    assert r["px"] == pytest.approx(60000.0)
    assert "FLAT" in r["zone"]


def test_both_sources_dead_raises_informative(monkeypatch):
    monkeypatch.setattr(rg.time, "sleep", lambda s: None)
    monkeypatch.setattr(rg, "_bybit_4h",
                        lambda: (_ for _ in ()).throw(ValueError("bybit пуст")))
    monkeypatch.setattr(rg, "_binance_4h",
                        lambda n4h=250: (_ for _ in ()).throw(
                            ValueError("binance пуст")))
    with pytest.raises(RuntimeError, match="bybit.*binance"):
        rg.regime()


def test_binance_fallback_shape(monkeypatch):
    """Фоллбэк отдаёт три ряда одинаковой длины из колонок high/low/close."""
    import pandas as pd

    n = 260
    df = pd.DataFrame({
        "open_time": pd.date_range("2026-04-01", periods=n, freq="4h",
                                   tz="UTC"),
        "high": [50010.0] * n, "low": [49990.0] * n, "close": [50000.0] * n,
    })
    monkeypatch.setattr("core.data_loader.load_klines",
                        lambda sym, tf, limit=None: df)
    h, lo, c = rg._binance_4h(250)
    assert len(h) == len(lo) == len(c) == n
    assert len(c) >= rg.MIN_BARS
    assert all(x == 50000.0 for x in c)
    assert all(x == 50010.0 for x in h)


def test_binance_fallback_rejects_short_series(monkeypatch):
    """Короткий ответ не должен молча уезжать в расчёт режима."""
    import pandas as pd

    df = pd.DataFrame({"open_time": pd.date_range("2026-04-01", periods=3,
                                                  freq="4h", tz="UTC"),
                       "high": [1.0] * 3, "low": [1.0] * 3, "close": [1.0] * 3})
    monkeypatch.setattr("core.data_loader.load_klines",
                        lambda sym, tf, limit=None: df)
    with pytest.raises(RuntimeError, match="пусто"):
        rg._binance_4h(250)


def test_bitmex_is_not_called_anywhere(monkeypatch):
    """BitMEX выключен: снятая функция не должна вызываться из _fetch_4h."""
    monkeypatch.setattr(rg.time, "sleep", lambda s: None)
    monkeypatch.setattr(rg, "_bybit_4h",
                        lambda: (_ for _ in ()).throw(ValueError("bybit")))

    def boom(n4h=250):
        raise AssertionError("BitMEX не должен вызываться")

    monkeypatch.setattr(rg, "_bitmex_4h_retired", boom)
    monkeypatch.setattr(rg, "_binance_4h", lambda n4h=250: _flat_bars())
    r = rg.regime()
    assert r["px"] == pytest.approx(60000.0)
