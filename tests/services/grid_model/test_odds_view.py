"""Наглядная карточка: полоски, строки ботов словами, картинка."""
from __future__ import annotations

import pytest

from services.grid_model import bot_money as bm
from services.grid_model import odds_intraday as oi
from services.grid_model import odds_view as ov


def test_bar_has_five_cells_and_rounds():
    assert ov.bar(0.0) == "▱▱▱▱▱"
    assert ov.bar(0.57) == "▰▰▰▱▱"
    assert ov.bar(1.0) == "▰▰▰▰▰"
    assert ov.pct_txt(0.004) == "<1%" and ov.pct_txt(0.995) == ">99%"


def _short_book() -> bm.Book:
    return bm.Book(name="BTC USDT DYNAMIC", coin="BTC", inverse=False, grid_side=2,
                   step=0.006, target=0.0139, obap=False, order_qty=0.01,
                   max_orders=200, border_top=86_500.0, border_bottom=None,
                   orders=[bm.Order(2, 0.01, 82_000.0, 80_860.2),
                           bm.Order(2, 0.01, 83_000.0, 81_846.3)],
                   bag_usd=-30.0)


def test_bot_block_speaks_in_words_and_icons():
    txt = ov.bot_block(_short_book(), 83_500.0, lambda pct, h: 0.2)
    assert "💰 BTC шорт" in txt and "сейчас -30$" in txt
    assert "граница, набор стоп" in txt
    assert "закроются все" in txt and "✅" in txt, "все тейки — итог в плюсе"
    assert "🔴" in txt, "хвост +10% помечен красным"
    assert "неделя" in txt, "при малом шансе за сутки показывается неделя"


def test_chance_words():
    assert ov.chance_word(0.05) == "вряд ли"
    assert ov.chance_word(0.52) == "50 на 50"
    assert ov.chance_word(0.7) == "скорее да"
    assert ov.chance_word(0.9) == "почти наверняка"


def test_headline_names_nearest_plus_and_main_risk():
    """«Главное на сутки»: ближайший тейк с деньгами и граница с шансом на неделю."""
    lines = ov.headline([_short_book()], 83_500.0, lambda pct, h: 0.5)
    txt = "\n".join(lines)
    assert "первый тейк" in txt and "забирает" in txt
    assert "граница 86,500" in txt and "за неделю" in txt


def test_first_take_with_negative_total_is_not_green():
    """Первый тейк забирает деньги, но позиция в целом в минусе — не ✅.
    Как у живого BTC-шорта 30.09: глубокий вход 80 000 тянет итог вниз."""
    book = _short_book()
    book.orders = [bm.Order(2, 0.01, 80_000.0, 78_888.0),
                   bm.Order(2, 0.01, 84_000.0, 82_832.4)]
    txt = ov.bot_block(book, 83_500.0, lambda pct, h: 0.5)
    line = next(ln for ln in txt.splitlines() if "первый тейк" in ln)
    assert line.strip().startswith("↘️")


needs_hourly = pytest.mark.skipif(not (oi.DATA / "1h_BTCUSDT.csv").exists(),
                                  reason="нет часовой истории")


@needs_hourly
def test_chart_is_written(tmp_path, monkeypatch):
    d = oi.load_hourly("BTCUSDT", refresh=False)
    monkeypatch.setattr(oi, "load_hourly", lambda sym, refresh=True: d)
    monkeypatch.setattr(oi, "CACHE", tmp_path)
    px = float(d["close"].iloc[-1])
    out = ov.coin_chart("BTCUSDT", px, [_short_book()], path=tmp_path / "c.png")
    assert out is not None and out.stat().st_size > 10_000
