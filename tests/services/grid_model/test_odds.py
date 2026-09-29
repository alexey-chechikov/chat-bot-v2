"""Карточка шансов обязана воспроизводить замер 28.09.2026 на 867 днях."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from services.grid_model import odds as od

# Замер 28.09.2026 снят на окне frozen-1m + живые минутки (market_live —
# в .gitignore). Без живых данных окно другое и числа не воспроизводятся.
_LIVE = Path(__file__).resolve().parents[3] / "market_live" / "market_1m.csv"
needs_live = pytest.mark.skipif(
    not _LIVE.exists(), reason="нет market_live/market_1m.csv — окно замера другое")


def test_bucket_boundaries():
    assert od.bucket_of(-3.0) == "ниже SMA100"
    assert od.bucket_of(5.0) == "0…10%"
    assert od.bucket_of(18.6) == "10…20%"
    assert od.bucket_of(21.5) == "выше 20%"


def test_episodes_counts_independent_runs():
    """65 дней в зоне — это не 65 наблюдений, а 10 эпизодов."""
    m = np.array([1, 1, 1, 0, 0, 1, 0, 1, 1])
    assert od.episodes(m.astype(bool)) == [3, 1, 2]


@needs_live
def test_prob_reach_matches_measurement():
    """Воспроизводит замер 28.09.2026 на ОКНЕ 867 дней: 90д +20% 32% → 13%.

    ⚠️ Этот вывод ОПРОВЕРГНУТ 29.09.2026 на 9 годах (test_odds_z.py::
    test_after_rally_continuation_on_nine_years): там после ралли рост ЧАЩЕ,
    63% против 53%. Тест оставлен как фиксация того, что короткое окно дало
    обратный знак, — не как свойство рынка."""
    prices, dist, _ = od.load_daily()
    assert len(prices) > 800, "нужна полная история"
    o20 = od.prob_reach(prices, dist, 0.20, 90, "выше 20%")
    o32 = od.prob_reach(prices, dist, 0.32, 90, "выше 20%")
    assert abs(o20.base - 0.32) < 0.04, f"безусловная +20%/90д = {o20.base:.0%}"
    assert abs(o20.cond - 0.13) < 0.05, f"условная +20%/90д = {o20.cond:.0%}"
    assert abs(o32.base - 0.183) < 0.04
    assert abs(o32.cond - 0.09) < 0.05
    assert o20.cond < o20.base and o32.cond < o32.base


@needs_live
def test_sample_weakness_is_visible():
    """Зона >20% — 65 дней, но эпизодов около десяти и один доминирует."""
    prices, dist, _ = od.load_daily()
    mask = np.array([(not np.isnan(x)) and od.bucket_of(x) == "выше 20%"
                     for x in dist])
    eps = od.episodes(mask)
    assert 50 <= mask.sum() <= 80
    assert len(eps) <= 15
    assert max(eps) > mask.sum() * 0.5, "один эпизод должен доминировать"


def test_bot_levels_short_capped_by_border():
    """BTC-шорт 28.09: цена 82,966, средняя 84,220, позиция −0.05,
    шаг 0.8, ордер 0.01, граница 86,500 → потолок 0.10 BTC, средняя 84,599,
    залог 2,516.54 обнуляется около 109,765."""
    lv = od.bot_levels(price=82_966.0, avg=84_220.09, position=-0.05,
                       step_pct=0.8, order_size=0.01, deposit=2_516.54,
                       border=86_500.0, short=True)
    assert lv.max_position == pytest.approx(0.10, abs=0.011)
    assert abs(lv.capped_avg - 84_599) < 200
    assert abs(lv.zero_equity - 109_765) < 1_500
    assert 28 < lv.pct_to_zero < 36


def test_bot_levels_without_border_uses_measured_adverse_move():
    """У эфира верхней границы НЕТ. Без неё потолка не существует, поэтому
    набор моделируется по замеренному ходу против позиции (40% для Auto) —
    иначе точка обнуления считается по сегодняшней позиции и врёт в разы."""
    no_border = od.bot_levels(price=2_685.0, avg=2_684.8, position=-0.48,
                              step_pct=0.1, order_size=0.01, deposit=2_516.54,
                              border=None, short=True, max_orders=800,
                              adverse_pct=40.0)
    assert no_border.max_position > 3.0          # 0.48 + сотни уровней
    assert no_border.zero_equity < 4_500
    naive = od.bot_levels(price=2_685.0, avg=2_684.8, position=-0.48,
                          step_pct=0.1, order_size=0.01, deposit=2_516.54,
                          border=2_700.0, short=True, max_orders=800)
    assert naive.zero_equity > no_border.zero_equity


@needs_live
def test_card_renders_with_cancel_levels():
    prices, dist, dates = od.load_daily()
    lv = od.bot_levels(82_966.0, 84_220.09, -0.05, 0.8, 0.01, 2_516.54,
                       86_500.0, True)
    t = od.card(prices, dist, dates, lv, name="BTC шорт")
    assert "ШАНСЫ ПО РЕЖИМУ" in t
    assert "ОТМЕНА ЗОНЫ" in t
    assert "ЗАЛОГ ОБНУЛЯЕТСЯ" in t
    assert "эпизодов" in t                # честность выборки обязательна
