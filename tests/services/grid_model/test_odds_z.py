"""z-модель шансов обязана держать замеры 29.09.2026 на 9 годах дневных свечей.

Если тест упал — правили модель, не перепроверив её вне выборки.
"""
from __future__ import annotations

import numpy as np
import pytest

from services.grid_model import odds_z as oz


@pytest.fixture(scope="module")
def btc():
    d = oz.load_daily("BTCUSDT", refresh=False)
    assert len(d) > 3000, "нужна полная история с 2017 (tools/fetch_daily_history.py)"
    return d, oz.build_table(d)


@pytest.fixture(scope="module")
def eth():
    d = oz.load_daily("ETHUSDT", refresh=False)
    return d, oz.build_table(d)


def test_out_of_sample_skill_btc(btc):
    """Замер: +10.4% к базовой частоте, обучение на одной половине, тест на другой."""
    d, t = btc
    assert oz.oos_skill(d, t) > 0.07


def test_out_of_sample_skill_eth(eth):
    d, t = eth
    assert oz.oos_skill(d, t) > 0.05


@pytest.mark.parametrize("fixture", ["btc", "eth"])
def test_calibration_on_held_out_half(fixture, request):
    """Модель говорит 36% — на невиданной половине сбывается ~36%.
    Замер первой версии: максимальное расхождение 4 п.п."""
    d, t = request.getfixturevalue(fixture)
    cal = oz.calibration(d, t)
    big = cal[cal["n"] >= 1000]
    worst = float((big["pred"] - big["fact"]).abs().max())
    assert worst < 0.06, f"расхождение калибровки {worst:.1%}"


def test_monotone_in_level_and_horizon(btc):
    d, _ = btc
    m, _ = oz.get_model("BTCUSDT", refresh=False)
    s = 0.017
    for h in (1, 7, 30, 90):
        ups = [m.touch(p, h, s) for p in (0.03, 0.05, 0.10, 0.20)]
        assert ups == sorted(ups, reverse=True), f"вверх не убывает с уровнем, {h}д"
    for p in (0.05, -0.05, 0.10):
        hs = [m.touch(p, h, s) for h in (1, 3, 7, 14, 30, 90)]
        assert hs == sorted(hs), f"шанс {p:+.0%} не растёт с горизонтом"


def test_no_saturation_at_small_levels(btc):
    """Первая версия застывала: +3% за 14/30/90 дней = 80/80/80%."""
    m, _ = oz.get_model("BTCUSDT", refresh=False)
    s = 0.017
    assert m.touch(0.03, 90, s) > m.touch(0.03, 14, s) + 0.10


def test_race_reflects_drift_not_forecast(btc):
    """Кто первый: около половины, с лёгким перекосом вверх от многолетнего дрейфа."""
    m, _ = oz.get_model("BTCUSDT", refresh=False)
    for p in (0.03, 0.05, 0.10):
        assert 0.40 < m.up_first(p, 0.017) < 0.65


@pytest.mark.parametrize("sym", ["BTCUSDT", "ETHUSDT"])
def test_after_rally_continuation_on_nine_years(sym):
    """Тезис «после ралли повтор реже» на 9 годах ОПРОВЕРГНУТ: после >20% над
    SMA100 рост +20% за 90д шёл ЧАЩЕ (BTC 63% против 53%, ETH 72% против 62%).
    На 867 днях 2024–2026 было наоборот — один эпизод."""
    d = oz.load_daily(sym, refresh=False)
    base, cond, n = oz.after_rally_context(d)
    assert n > 300
    assert cond > base


def test_option_spot_is_index_not_expiry_future(monkeypatch):
    """29.09.2026: спот брался из underlying_price первого опциона — это цена
    фьючерса его экспирации. ETH июнь-2027 давал 2 771 при индексе 2 682."""
    import io
    import json
    import urllib.request

    rows = [
        {"instrument_name": "ETH-25JUN27-2200-P", "underlying_price": 2770.89,
         "estimated_delivery_price": 2682.09, "open_interest": 10, "mark_iv": 60},
        {"instrument_name": "ETH-2OCT26-2700-C", "underlying_price": 2683.5,
         "estimated_delivery_price": 2682.09, "open_interest": 500, "mark_iv": 45},
        {"instrument_name": "ETH-2OCT26-2600-P", "underlying_price": 2683.5,
         "estimated_delivery_price": 2682.09, "open_interest": 400, "mark_iv": 45},
    ]
    body = json.dumps({"result": rows}).encode()
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=15: io.BytesIO(body))
    out = oz.option_levels("ETH")
    assert out["spot"] == pytest.approx(2682.09)
    assert out["call_wall"] == 2700 and out["put_wall"] == 2600


def test_card_renders(btc):
    t = oz.card("BTCUSDT", levels=[("граница", 86_500.0)], price=83_828.0)
    for part in ("ШАНСЫ", "ВЕРОЯТНОСТЬ КОСНУТЬСЯ", "КТО ПЕРВЫЙ", "КОРИДОРЕ",
                 "УРОВНИ", "вне выборки", "КОНТЕКСТ"):
        assert part in t
