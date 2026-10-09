"""Стресс-бюджет: доливы по пути, безопасная граница, «вход выкл», пинг только при 🔴."""
from dataclasses import replace

import pytest

from services.grid_model import bot_money as bm
from services.grid_model import stress_budget as sb

CFG = {**sb.DEFAULT}


def short_book(n_orders=5, border=None, max_orders=200):
    orders = [bm.Order(bm.SHORT, 0.01, 80_000 * (1 + 0.006 * i), 80_000 * (1 + 0.006 * i) * (1 - 0.0139))
              for i in range(n_orders)]
    return bm.Book(name="BTC USDT DYNAMIC", coin="BTC", inverse=False, grid_side=bm.SHORT, step=0.006,
                   target=0.0139, obap=False, order_qty=0.01, max_orders=max_orders,
                   border_top=border, border_bottom=None, orders=orders)


def test_stress_move_floor_and_sigma():
    assert sb.stress_move(None, CFG) == pytest.approx(0.10)
    assert sb.stress_move(0.01, CFG) == pytest.approx(0.10)            # 3·1%·√3 = 5.2% < пола
    assert sb.stress_move(0.03, CFG) == pytest.approx(3 * 0.03 * 3 ** 0.5)


def test_grid_adds_orders_on_the_way_and_border_stops_it():
    px = 82_400.0
    free = sb.assess(short_book(), px, 0.10, 3000.0, CFG)
    capped = sb.assess(short_book(border=85_000), px, 0.10, 3000.0, CFG)
    assert free.direction == 1 and free.new_orders > capped.new_orders >= 0
    assert free.loss > capped.loss > 0


def test_safe_border_keeps_loss_within_budget():
    px, eq = 82_400.0, 3000.0            # своя позиция в бюджет влезает, доливы — нет
    v = sb.assess(short_book(), px, 0.10, eq, CFG)
    assert v.status != "ok" and v.safe_border is not None
    b = sb._with_border(short_book(), 1, v.safe_border)
    loss, _, _ = sb._loss(b, px, v.stress_px)
    assert loss <= CFG["budget_frac"] * eq + 1e-6


def test_entries_off_means_reduce_position():
    px = 82_400.0
    book = replace(short_book(n_orders=30), max_orders=30, name="BTC USDT DYNAMIC [вход выкл]")
    v = sb.assess(book, px, 0.10, 1000.0, CFG)
    assert v.new_orders == 0 and v.safe_border is None
    assert "сократи" in v.note and "вход выкл" in v.bot


def test_ping_only_on_red_and_once(tmp_path, monkeypatch):
    monkeypatch.setattr(sb, "STATE", tmp_path / "st.json")
    monkeypatch.setattr(sb, "JOURNAL", tmp_path / "j.jsonl")
    monkeypatch.setattr(sb, "CONFIG", tmp_path / "cfg.json")
    books = {"BTC": [short_book(n_orders=30)]}
    sent = []
    kw = dict(books=books, prices={"BTC": 82_400.0}, sigmas={"BTC": None})
    sb.tick(sent.append, now=1_000.0, equity=10_000.0, **kw)          # мало риска → тишина
    assert sent == []
    sb.tick(sent.append, now=2_000.0, equity=400.0, **kw)             # 🔴 → один пинг
    sb.tick(sent.append, now=3_000.0, equity=400.0, **kw)             # тот же статус → тишина
    assert len(sent) == 1 and sent[0].startswith("🛡 🔴")
