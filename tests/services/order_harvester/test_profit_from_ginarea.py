"""Прибыль ордера — по данным GinArea, с проверкой правдоподобия.

2026-08-02, оператор поймал закрытия в минус (третий раз). Разбор по полю
profit самой GinArea: харвестер закрыл 133 ордера, 63 из них УБЫТОЧНЫЕ
на −$24.63, а в журнал писал +$769.95.

Три причины, каждая закрыта тестом ниже:
  1) вход брался из `price` (лимитная заявка) вместо `closedPrice` (факт);
  2) комиссия `fee` не вычиталась вовсе, хотя биржа её списала;
  3) не было проверки правдоподобия — при неверной рыночной цене расчёт
     показывал +$22 там, где ордер на СВОЁМ тейке даёт максимум $1.49.

Формы ордеров — реальные, сняты с GinArea 2026-08-02.
"""
import pytest

from services.order_harvester.loop import (order_fields, order_profit_usd,
                                           profit_cap_usd)

# реальный открытый ордер AVAX-бота (шорт), снят 2026-08-02
OPEN_SHORT = {
    "id": "70cbdb0b-99ee-4a71-998d-599f1baa8de6",
    "side": 2, "price": 6.583, "quantity": 23.5,
    "closedPrice": 6.588, "closedQuantity": 23.5,
    "fee": 0.077409, "feeExchangeCurrencyId": 11, "stopCount": 1,
    "openedAt": "2026-08-02T05:20:53.148Z", "closedAt": "2026-08-02T05:20:53.15Z",
    "isOpen": True, "botId": 5900351455, "profit": None, "profitInDistance": None,
    "trigger": {"price": 6.5557188, "quantity": 23.5, "initPrice": 6.583,
                "lastPrice": 6.583, "isTrailing": False, "quantityPositions": [9]},
    "out": None, "closeReason": 0,
}


def test_entry_is_fill_price_not_limit():
    """Вход — цена исполнения, а не лимитная заявка."""
    f = order_fields(OPEN_SHORT)
    assert f["price_in"] == 6.588      # closedPrice
    assert f["limit_price"] == 6.583   # price — только для справки


def test_fee_is_read_and_subtracted_twice():
    """Комиссия входа известна; выход стоит столько же → вычитаем обе."""
    f = order_fields(OPEN_SHORT)
    assert f["fee"] == pytest.approx(0.077409)
    # шорт: рынок ниже входа на 0.1 → грязными 0.1×23.5 = 2.35
    got = order_profit_usd(6.488, f)
    assert got == pytest.approx(2.35 - 2 * 0.077409, abs=1e-6)


def test_no_fee_means_no_guessing():
    """Комиссии нет — не гадаем, ордер не трогаем."""
    o = dict(OPEN_SHORT, fee=None)
    assert order_profit_usd(6.488, order_fields(o)) is None


def test_no_fill_price_means_no_guessing():
    o = dict(OPEN_SHORT, closedPrice=None)
    assert order_profit_usd(6.488, order_fields(o)) is None


def test_cap_equals_profit_at_own_take_profit():
    """Потолок = сколько ордер даёт на своём тейке."""
    f = order_fields(OPEN_SHORT)
    assert profit_cap_usd(f) == pytest.approx(abs(6.588 - 6.5557188) * 23.5)
    assert profit_cap_usd(f) < 0.76      # реально это меньше доллара


def test_wrong_market_price_is_caught_by_cap():
    """Ровно тот отказ, что стоил денег: цена рынка неверна → расчёт выше потолка.

    Настоящий случай: записано +$22.58 при потолке $1.49, факт по GinArea −$0.52.
    """
    f = order_fields(OPEN_SHORT)
    absurd = order_profit_usd(5.6, f)     # «рынок» ниже входа на целый доллар
    cap = profit_cap_usd(f)
    assert absurd > cap                    # значит будет отброшен в _candidates
    assert cap < 1.0


def test_long_side_direction():
    """Лонг: прибыль при росте рынка."""
    o = dict(OPEN_SHORT, side=1, closedPrice=6.40, fee=0.05,
             trigger={"price": 6.45, "quantity": 23.5})
    f = order_fields(o)
    assert order_profit_usd(6.42, f) == pytest.approx(0.02 * 23.5 - 0.10, abs=1e-6)
    assert order_profit_usd(6.38, f) < 0   # рынок ниже входа = минус


def test_unknown_side_is_skipped():
    assert order_profit_usd(6.5, order_fields(dict(OPEN_SHORT, side=3))) is None
