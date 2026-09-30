"""Деньги ботов по реальным ордерам: арифметика пути и выходов.

Если тест упал — поменялась модель пути, перепроверь на живой книге.
"""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from services.grid_model import bot_money as bm
from services.grid_model import odds_journal as oj


def _short_book(**kw) -> bm.Book:
    base = dict(name="BTC шорт", coin="BTC", inverse=False, grid_side=2,
                step=0.01, target=0.0139, obap=False, order_qty=1.0,
                max_orders=200, border_top=103.0, border_bottom=None,
                orders=[bm.Order(2, 1.0, 100.0, 98.6), bm.Order(2, 1.0, 101.0, 99.59)])
    base.update(kw)
    return bm.Book(**base)


def test_short_down_closes_each_order_on_its_take():
    o = bm.simulate(_short_book(), px=100.5, target_px=98.5)
    assert o.realized == pytest.approx(1.4 + 1.41)
    assert o.unrealized == 0 and o.n_open == 0


def test_short_up_adds_by_step_until_border():
    o = bm.simulate(_short_book(), px=100.5, target_px=105.0)
    entries = [100.0, 101.0, 100.5 * 1.01, 100.5 * 1.01 ** 2]   # третий > 103
    assert o.n_open == 4
    assert o.unrealized == pytest.approx(sum(e - 105.0 for e in entries))
    assert "граница" in o.note


def test_auto_obap_closes_side_at_taps_and_adds_longs_on_the_way():
    """ETH Auto 30.09: шорты выходят целиком на taps, по пути вниз копятся лонги."""
    book = bm.Book(name="ETH", coin="ETH", inverse=False, grid_side=3, step=0.001,
                   target=0.02, obap=True, order_qty=0.01, max_orders=800,
                   border_top=None, border_bottom=None,
                   orders=[bm.Order(2, 1.0, 2595.2, None), bm.Order(1, 0.16, 2691.15, None)],
                   tapb=2744.97, taps=2543.30)
    down = bm.simulate(book, px=2682.0, target_px=2540.0)
    assert down.realized == pytest.approx((2595.2 - 2543.30) * 1.0)
    assert down.net_qty > 0.6, "шорты закрыты, остались лонги + добор по пути"
    up = bm.simulate(book, px=2682.0, target_px=2750.0)
    assert up.realized == pytest.approx((2744.97 - 2691.15) * 0.16)
    assert up.net_qty < -1.2


def test_inverse_long_pnl_in_usd():
    o = bm.Order(1, 1500.0, 85_924.0, None)
    usd = bm.pnl_usd(o, 83_698.0, inverse=True)
    assert usd == pytest.approx(1500 * (1 / 85_924 - 1 / 83_698) * 83_698)
    assert -45 < usd < -35


def _raw(side, qty, fill, take):
    return {"id": f"o{fill}", "side": side, "quantity": qty, "price": fill,
            "closedPrice": fill, "fee": 0.4, "feeExchangeCurrencyId": 11,
            "isOpen": True, "trigger": {"price": take}}


def test_book_ignores_stat_average_price():
    """30.09.2026: stat.averagePrice 84 357, средняя открытых ордеров 82 470.
    Средняя книги обязана браться из ордеров."""
    ext = SimpleNamespace(tapb=None, taps=None)
    stat = SimpleNamespace(balance=2648.0, currentProfit=55.16, profit=131.38,
                           averagePrice=84_356.94, extension=ext)
    bot = SimpleNamespace(name="BTC USDT DYNAMIC", stat=stat)
    fills = [80_814.7, 81_500.0, 82_300.0, 83_000.0, 83_170.0, 84_036.0]
    raw = [_raw(2, 0.01, f, f * (1 - 0.0139)) for f in fills]
    params = {"side": 2, "gs": 0.6, "gap": {"tog": 1.39}, "obap": False,
              "q": {"minQ": 0.01}, "maxOp": 200, "border": {"top": 86500}}
    book = bm.book_from_live(bot, params, raw, "BTC")
    assert book.side_avg(2) == pytest.approx(sum(fills) / 6)
    assert abs(book.side_avg(2) - 84_356.94) > 1_500
    assert book.bag_usd == pytest.approx(55.16 - 131.38)
    assert book.border_top == 86_500 and book.step == pytest.approx(0.006)


def test_block_renders_levels_and_probabilities():
    txt = bm.block(_short_book(bag_usd=-1.0), 100.5, lambda pct, h: 0.5)
    assert "первый тейк" in txt and "граница" in txt and "50% 50% 50%" in txt


def test_fetch_orders_pages_zero_based():
    calls = []

    class Api:
        def get_orders(self, bot_id, *, page_size, page_number, only_opened):
            calls.append(page_number)
            n = 100 if page_number == 0 else 30
            return {"orders": [{}] * n, "totalCount": 130}
    assert len(bm.fetch_orders(Api(), 1)) == 130
    assert calls == [0, 1]


def test_journal_outcomes_touch_and_corridor(tmp_path):
    ts = pd.date_range("2026-09-30", periods=6, freq="h", tz="UTC")
    d = pd.DataFrame({"high": [100, 101.5, 100.5, 100, 100, 100],
                      "low": [100, 99.5, 99.8, 99, 99, 99],
                      "close": [100.0] * 6}, index=ts)
    j = tmp_path / "j.jsonl"
    j.write_text(
        '{"sym": "BTCUSDT", "ts_ms": %d, "close": 100.0, "rows": ['
        '{"h": 1, "pct": 0.01, "p": 0.3}, {"h": 1, "pct": -0.01, "p": 0.2},'
        '{"h": 1, "corridor": 0.02}, {"h": 24, "pct": 0.01, "p": 0.5}]}\n'
        % (ts[0].value // 1_000_000), encoding="utf-8")
    t = oj.outcomes(j, candles={"BTCUSDT": d})
    touch = t[t["kind"] == "касание"].sort_values("p")
    assert list(touch["y"]) == [0.0, 1.0], "вниз −0.5% не коснулся, вверх +1.5% да"
    assert t[t["kind"] == "коридор"]["y"].iloc[0] == 1.0
    assert len(t) == 3, "суточный прогноз ещё не созрел"
    assert "КАСАНИЕ" in oj.verify_text(j, candles={"BTCUSDT": d})
