"""Карта плотности: круглые уровни, конфлюенс-склейка, формат карты."""
from __future__ import annotations

from services.scalp_levels import levels as lv


def test_round_levels():
    r = lv._round_levels(66065, 1000.0, n=2)
    assert 66000.0 in r and 67000.0 in r and 65000.0 in r
    assert all(x > 0 for x in r)


def _bars(px_path):
    """OHLCV-бары из списка цен (volume=1)."""
    return [{"ts": i, "open": p, "high": p * 1.001, "low": p * 0.999,
             "close": p, "volume": 1.0} for i, p in enumerate(px_path)]


def test_collect_confluence_and_distance(monkeypatch):
    # цена 100, бары вокруг; VPVR даст POC~100. круглый шаг 100 → уровень 100.
    bars = _bars([100.0] * 288)
    monkeypatch.setattr(lv, "_fetch", lambda s, i, l: bars if i == "5" else _bars([100, 101, 99]))
    monkeypatch.setattr(lv, "_bot_borders", lambda: [(100.05, "бот X")])  # близко к POC/круглому
    monkeypatch.setattr(lv, "_liq_clusters", lambda now, px: [])
    monkeypatch.setattr(lv, "ROUND_STEP", {"TESTUSDT": 100.0})
    d = lv.collect("TESTUSDT")
    assert d["px"] == 100.0
    # POC ~100, круглый 100, бот 100.05 → должны склеиться в конфлюенс
    conf = [x for x in d["levels"] if x["confluence"]]
    assert conf, "ожидался конфлюенс у 100"
    # дистанции считаются от цены
    for x in d["levels"]:
        assert abs(x["dist_pct"] - (x["price"] / 100.0 - 1) * 100) < 1e-6


def test_build_card_structure(monkeypatch):
    bars = _bars([100.0 + (i % 5) for i in range(288)])  # колебания 100-104
    monkeypatch.setattr(lv, "_fetch", lambda s, i, l: bars if i == "5" else _bars([100, 106, 98]))
    monkeypatch.setattr(lv, "_bot_borders", lambda: [])
    monkeypatch.setattr(lv, "_liq_clusters", lambda now, px: [(101.5, 50.0)])
    monkeypatch.setattr(lv, "ROUND_STEP", {"TESTUSDT": 5.0})
    card = lv.build_card("TESTUSDT")
    assert "КАРТА ПЛОТНОСТИ TEST" in card
    assert "СВЕРХУ" in card and "СНИЗУ" in card
    assert "CScalp" in card
