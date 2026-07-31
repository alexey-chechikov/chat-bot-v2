"""Порог drift-лестницы: пропорционален позиции, реальный SL имеет приоритет.

2026-07-31. До этого база лестницы была зашита ($175) при любом размере бота:
по замеру 33 дней Stage 2 (−$96) означал 2.7% позиции у BCH и 124% у SOL —
для мелкого бота недостижимо физически. Формы данных здесь — реальные:
raw_params_json как его отдаёт GinArea (slt=false, tsl=null у ботов OKX).
"""
import json

from services.alt_guard import loop as ag

# реальный кусок raw_params_json бота OKX (стоп НЕ выставлен)
RAW_NO_SL = json.dumps({
    "gs": 0.4, "so": 0.7, "obap": True, "slt": False, "tsl": None, "lsl": None,
    "slp": {"m": 0, "pp": None, "tp": None},
    "q": {"maxQ": 5, "minQ": 1, "qr": 1.1}, "maxOp": 100,
})
RAW_WITH_SL = json.dumps({
    "gs": 0.4, "so": 0.7, "obap": True, "slt": True, "tsl": -250.0,
    "q": {"maxQ": 5, "minQ": 1, "qr": 1.1}, "maxOp": 100,
})


def test_real_sl_wins_over_proportional():
    """Если оператор выставил стоп в GinArea — считаем от него, не от позиции."""
    p = {"raw_params_json": RAW_WITH_SL}
    assert ag._sl_usd(p, notional=50_000) == 250.0


def test_proportional_when_no_sl():
    """Стопа нет → порог = 5.5% позиции."""
    p = {"raw_params_json": RAW_NO_SL}
    assert ag._sl_usd(p, notional=10_000) == 550.0


def test_floor_protects_tiny_position():
    """На копеечной позиции не дёргаемся: порог не опускается ниже $50."""
    p = {"raw_params_json": RAW_NO_SL}
    assert ag._sl_usd(p, notional=100) == ag.SL_FLOOR_USD


def test_no_position_keeps_old_default():
    """Позиции/цены нет → прежнее поведение, без деления на ноль."""
    p = {"raw_params_json": RAW_NO_SL}
    assert ag._sl_usd(p, notional=0) == ag.SL_DEFAULT_USD
    assert ag._sl_usd(p, notional=None) == ag.SL_DEFAULT_USD
    assert ag._sl_usd(p) == ag.SL_DEFAULT_USD


def test_same_rule_means_same_percent_for_any_size():
    """Суть правки: у бота на $3k и на $30k Stage 2 наступает на одной ГЛУБИНЕ.

    Раньше −$96 был 3.2% позиции у первого и 0.32% у второго.
    """
    p = {"raw_params_json": RAW_NO_SL}
    small = ag._sl_usd(p, notional=3_000) * 0.55
    big = ag._sl_usd(p, notional=30_000) * 0.55
    assert round(small / 3_000, 4) == round(big / 30_000, 4) == 0.0303


def test_notional_from_real_snapshot_shape():
    """_notional читает снимок трекера в его настоящем виде (DYN: поза в монетах)."""
    latest = {"bot_id": "5253063096", "status": 2, "position": 1.05,
              "profit": 7.6, "current_profit": 7.47, "average_price": 73.4595238095}
    assert round(ag._notional(latest)) == 77


def test_notional_survives_empty_and_broken_fields():
    assert ag._notional({"position": 0, "average_price": 73.4}) == 0.0
    assert ag._notional({"position": None, "average_price": None}) == 0.0
    assert ag._notional({"position": "нет", "average_price": "нет"}) == 0.0
    assert ag._notional({}) == 0.0


def test_short_position_counts_by_absolute_size():
    """Шорт-нога: нотионал по модулю, иначе порог ушёл бы в минус."""
    assert round(ag._notional({"position": -1.05, "average_price": 73.46})) == 77


def test_stage2_thresholds_for_live_bots():
    """Контрольные цифры для живых ботов — сверка с тем, что обещано оператору."""
    p = {"raw_params_json": RAW_NO_SL}
    # BTC на позиции $1481 → Stage 2 при мешке −$44.8 (было −$96, недостижимо)
    assert round(ag._sl_usd(p, 1481) * 0.55, 1) == 44.8
    # альт на позиции $77 → пол $50 → Stage 2 при −$27.5, но гейт $500 не пустит
    assert round(ag._sl_usd(p, 77) * 0.55, 1) == 27.5
