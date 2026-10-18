"""Утренняя сводка рынка: условия дня, статистика следующего дня, «отличие» только вне 95% интервала."""
from __future__ import annotations

import random

from services.market_brief import brief as mb

TH = {"tak": (0.95, 1.05), "fun": (0.0001, 0.0006), "dls": (-0.05, 0.05)}


def test_conditions_quadrants_and_buckets():
    c = mb.conditions(0.02, 1.5, 0.0009, 1.10, 0.10, TH)
    assert c == {"oi_price": "OI↑ цена↑", "funding": "фандинг высокий", "taker": "агрессор — покупатели",
                 "top_ls": "топ-трейдеры добавили лонгов"}
    c = mb.conditions(-0.02, -1.0, 0.00005, 0.90, -0.10, TH)
    assert c["oi_price"] == "OI↓ цена↓" and c["funding"] == "фандинг низкий" and c["taker"] == "агрессор — продавцы"
    assert mb.conditions(0.001, 0.1, 0.0003, 1.0, 0.0, TH)["oi_price"] == "OI≈ цена≈"


def test_wilson_bounds():
    lo, hi = mb.wilson(50, 100)
    assert 0.40 < lo < 0.5 < hi < 0.60
    assert mb.wilson(0, 0) == (0.0, 1.0)


def _rows(n, up_after=None):
    random.seed(1)
    rows, close, oi = [], 100.0, 1000.0
    for i in range(n):
        ret = random.uniform(-0.03, 0.03)
        close *= 1 + ret
        oi_chg = random.uniform(-2, 2)
        oi *= 1 + oi_chg / 100
        rows.append({"day": f"d{i}", "close": close, "ret_1d": ret, "oi": oi, "oi_chg_pct": oi_chg,
                     "top_ls": 1.5 + random.uniform(-0.2, 0.2), "global_ls": 1.2, "taker_ratio": random.uniform(0.9, 1.1),
                     "funding_day": random.uniform(0, 0.0009)})
    if up_after:                                    # после «OI↑ цена↑» следующий день всегда растёт
        for i in range(n - 1):
            if rows[i]["oi_chg_pct"] > 0.5 and rows[i]["ret_1d"] > 0.005:
                rows[i + 1]["ret_1d"] = abs(rows[i + 1]["ret_1d"]) + 0.001
    return rows


def test_stat_noise_is_not_reported_as_difference():
    labeled, _ = mb.label_days(_rows(700))
    s = mb.stat(labeled, "oi_price", "OI↑ цена↑")
    assert s["n"] >= 30 and s["up_diff"] is False


def test_stat_real_effect_is_reported():
    labeled, _ = mb.label_days(_rows(700, up_after=True))
    s = mb.stat(labeled, "oi_price", "OI↑ цена↑")
    assert s["up"] == 1.0 and s["up_diff"] is True


def test_small_sample_never_difference():
    labeled, _ = mb.label_days(_rows(40, up_after=True))
    s = mb.stat(labeled, "oi_price", "OI↑ цена↑")
    assert s["n"] < 30 and s["up_diff"] is False
