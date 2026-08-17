"""Прибыль ордера на инверсном и линейном контрактах.

Все формы ордеров сняты живьём 2026-08-17 с OKX (exchangeId=3):
BTC SHORT 5189290547 — монетно-маржинальный, комиссия в BTC (ccy=4);
BTC USDT DYNAMIC_c 5236613378 и AVAX 5900351455 — линейные, комиссия
в USDT (ccy=11).

Причина теста: до 2026-08-17 order_profit_usd считал только по линейной
формуле. На инверсном ордере она давала +$331 056 вместо +$4.01 — при
включении бота в харвестер это закрыло бы убыточные ордера как прибыльные.
"""
import pytest

from services.order_harvester.loop import (_is_inverse, order_fields,
                                           order_profit_usd)

# ─── сырые ответы GET /bots/{id}/orders, поля обрезаны до значимых ────────
INVERSE_ORDER = {
    "id": "a30a05be-1798-41fd-bfcb-0c2fc8e9f053",
    "side": 2, "price": 63622.7, "quantity": 1200,
    "closedPrice": 63622.7, "fee": 9.4305963123e-06,
    "feeExchangeCurrencyId": 4, "isOpen": True, "profit": None,
    "trigger": {"price": 63438.194169999995},
}
LINEAR_BTC_ORDER = {
    "id": "b1", "side": 1, "price": 63205.7, "quantity": 0.0107,
    "closedPrice": 63205.7, "fee": 0.338150495,
    "feeExchangeCurrencyId": 11, "isOpen": True, "profit": None,
    "trigger": {"price": 63000.0},
}
LINEAR_AVAX_ORDER = {
    "id": "c1", "side": 1, "price": 6.282, "quantity": 21.4,
    "closedPrice": 6.275, "fee": 0.0671425,
    "feeExchangeCurrencyId": 11, "isOpen": True, "profit": None,
    "trigger": {"price": 6.1},
}
MARK_BTC = 63346.8
MARK_AVAX = 6.30


def test_inverse_detected():
    assert _is_inverse(MARK_BTC, order_fields(INVERSE_ORDER)) is True


def test_linear_detected():
    assert _is_inverse(MARK_BTC, order_fields(LINEAR_BTC_ORDER)) is False
    assert _is_inverse(MARK_AVAX, order_fields(LINEAR_AVAX_ORDER)) is False


def test_inverse_profit_is_dollars_not_hundreds_of_thousands():
    """SHORT 1200 контрактов с 63622.7 при марке 63346.8.

    PnL = 1200·(1/63622.7 − 1/63346.8) в BTC, минус две комиссии,
    в долларах по марке ≈ +$4.01. Старая линейная формула давала +$331 056.
    """
    got = order_profit_usd(MARK_BTC, order_fields(INVERSE_ORDER))
    assert got == pytest.approx(4.01, abs=0.05)
    assert got < 100, "инверсный PnL не может быть трёхзначным на $1200 номинала"


def test_linear_profit_unchanged():
    """Линейные боты считаются как раньше — регрессии быть не должно."""
    got = order_profit_usd(MARK_BTC, order_fields(LINEAR_BTC_ORDER))
    expected = (MARK_BTC - 63205.7) * 0.0107 - 2 * 0.338150495
    assert got == pytest.approx(expected, abs=1e-9)

    got_avax = order_profit_usd(MARK_AVAX, order_fields(LINEAR_AVAX_ORDER))
    expected_avax = (MARK_AVAX - 6.275) * 21.4 - 2 * 0.0671425
    assert got_avax == pytest.approx(expected_avax, abs=1e-9)


def test_short_loser_stays_negative_on_inverse():
    """Ордер, вошедший НИЖЕ марки в шорт, обязан считаться убыточным.

    Живой пример: вход 63079.9, qty 1060 → −$5.55. Линейная формула
    показывала −$282 935, то есть знак совпадал случайно, а величина нет;
    на ордерах выше марки она врала и знаком тоже.
    """
    o = dict(INVERSE_ORDER, price=63079.9, closedPrice=63079.9,
             quantity=1060, fee=8.3e-06)
    got = order_profit_usd(MARK_BTC, order_fields(o))
    assert got < 0
    assert got == pytest.approx(-5.5, abs=0.6)


def test_conflicting_currency_and_rate_returns_none():
    """Валюта комиссии говорит «линейный», ставка — «инверсный»: не гадаем."""
    o = dict(INVERSE_ORDER, feeExchangeCurrencyId=11)
    assert _is_inverse(MARK_BTC, order_fields(o)) is None
    assert order_profit_usd(MARK_BTC, order_fields(o)) is None


def test_missing_fee_skipped():
    o = dict(INVERSE_ORDER)
    o["fee"] = None
    assert order_profit_usd(MARK_BTC, order_fields(o)) is None


def test_implausible_fee_rate_returns_none():
    """Комиссия, не бьющаяся ни с одной трактовкой, — повод пропустить ордер."""
    o = dict(INVERSE_ORDER, fee=5.0, feeExchangeCurrencyId=None)
    assert _is_inverse(MARK_BTC, order_fields(o)) is None


def test_zero_fee_falls_back_to_currency_then_linear():
    """Нулевая комиссия: ставку не проверить, регрессии быть не должно.

    Без валюты — линейный (поведение до 2026-08-17, на нём стоят старые
    тесты и мейкер-ребейт). С валютой BTC — всё равно инверсный.
    """
    o_lin = dict(LINEAR_BTC_ORDER, fee=0.0, feeExchangeCurrencyId=None)
    assert _is_inverse(MARK_BTC, order_fields(o_lin)) is False
    expected = (MARK_BTC - 63205.7) * 0.0107
    assert order_profit_usd(MARK_BTC, order_fields(o_lin)) == pytest.approx(
        expected, abs=1e-9)

    o_inv = dict(INVERSE_ORDER, fee=0.0)
    assert _is_inverse(MARK_BTC, order_fields(o_inv)) is True
