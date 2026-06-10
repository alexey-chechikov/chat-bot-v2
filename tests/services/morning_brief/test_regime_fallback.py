"""Регрессия 2026-06-10 04:00: «режим BTC недоступен: list index out of range» —
пустой/короткий ответ Bybit ронял секцию РЫНОК. Теперь 3 ретрая + фоллбэк BitMEX.
"""
from __future__ import annotations

import pytest

from services.morning_brief import regime as rg


def _flat_bars(n=250, px=60000.0):
    return [px] * n, [px] * n, [px] * n


def test_fallback_to_bitmex_when_bybit_fails(monkeypatch):
    monkeypatch.setattr(rg.time, "sleep", lambda s: None)
    calls = {"bybit": 0, "bitmex": 0}

    def bad_bybit():
        calls["bybit"] += 1
        raise IndexError("list index out of range")

    def good_bitmex(n4h=250):
        calls["bitmex"] += 1
        return _flat_bars()

    monkeypatch.setattr(rg, "_bybit_4h", bad_bybit)
    monkeypatch.setattr(rg, "_bitmex_4h", good_bitmex)
    r = rg.regime()
    assert calls["bybit"] == 3  # три попытки
    assert calls["bitmex"] == 1
    assert r["px"] == pytest.approx(60000.0)
    assert "FLAT" in r["zone"]


def test_both_sources_dead_raises_informative(monkeypatch):
    monkeypatch.setattr(rg.time, "sleep", lambda s: None)
    monkeypatch.setattr(rg, "_bybit_4h", lambda: (_ for _ in ()).throw(ValueError("bybit пуст")))
    monkeypatch.setattr(rg, "_bitmex_4h", lambda n4h=250: (_ for _ in ()).throw(ValueError("bitmex пуст")))
    with pytest.raises(RuntimeError, match="bybit.*bitmex"):
        rg.regime()


def test_bitmex_resample_shape(monkeypatch):
    """Ресемпл 1h→4h: бакеты по 4 часа, незакрытый хвост отброшен."""
    rows = []
    px = 50000.0
    for day in range(1, 45):  # 44 дня × 24ч = 1056 часов → 264 полных 4h
        for hour in range(24):
            ts = f"2026-04-{day:02d}T{hour:02d}:00:00.000Z" if day <= 30 else \
                 f"2026-05-{day-30:02d}T{hour:02d}:00:00.000Z"
            rows.append({"timestamp": ts, "high": px + 10, "low": px - 10, "close": px})
    rows.append({"timestamp": "2026-05-15T00:00:00.000Z", "high": px, "low": px, "close": px})

    class FakeResp:
        def __init__(self, data): self._d = data
        def read(self): return b""

    monkeypatch.setattr(rg.json, "load", lambda fh: rows)
    monkeypatch.setattr(rg.urllib.request, "urlopen", lambda req, timeout=20: object())
    h, lo, c = rg._bitmex_4h(250)
    assert len(c) >= rg.MIN_BARS
    assert all(x == px for x in c)
    assert all(x == px + 10 for x in h)
