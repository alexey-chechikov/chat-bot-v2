"""Типичные сценарии суток: порядок кластеров, текст, график не падает."""
from __future__ import annotations

import numpy as np
import pytest

from services.grid_model import odds_intraday as oi
from services.grid_model import odds_scenarios as osc


def test_kmeans_orders_down_flat_up():
    rng = np.random.default_rng(1)
    up = np.linspace(0.1, 1.6, 24) + rng.normal(0, 0.05, (300, 24))
    flat = rng.normal(0, 0.1, (900, 24))
    down = -np.linspace(0.1, 1.4, 24) + rng.normal(0, 0.05, (300, 24))
    lab, cent = osc._kmeans(np.vstack([up, flat, down]))
    ends = sorted(cent[:, -1])
    assert ends[0] < -1.0 < ends[1] < 1.0 < ends[2]


def test_text_scales_by_sigma_and_says_side_unknown():
    sc = [osc.Scenario("вниз", 0.18, [0.0] * 23 + [-1.34], -1.34, 0.05, -1.74),
          osc.Scenario("боковик", 0.66, [0.0] * 24, 0.08, 0.5, -0.42),
          osc.Scenario("вверх", 0.15, [0.0] * 23 + [1.66], 1.66, 2.0, -0.03)]
    txt = "\n".join(osc.text(sc, 0.0155))
    assert "≈66% — боковик" in txt and "±0.8%" in txt
    assert "уход вниз: к концу суток около -2.1%" in txt
    assert "уход вверх: к концу суток около +2.6%" in txt
    assert "заранее не известно" in txt


@pytest.mark.skipif(not (oi.DATA / "1h_BTCUSDT.csv").exists(), reason="нет часовой истории")
def test_chart_with_scenarios_renders(tmp_path, monkeypatch):
    """05.10: переменная сценария затёрла путь к файлу — график падал целиком."""
    from services.grid_model import odds_view as ov

    d = oi.load_hourly("BTCUSDT", refresh=False)
    monkeypatch.setattr(oi, "load_hourly", lambda sym, refresh=True: d)
    monkeypatch.setattr(osc, "CACHE", tmp_path)
    monkeypatch.setattr(oi, "CACHE", tmp_path)
    out = ov.coin_chart("BTCUSDT", float(d["close"].iloc[-1]), [], path=tmp_path / "c.png")
    assert out is not None and out.stat().st_size > 10_000
