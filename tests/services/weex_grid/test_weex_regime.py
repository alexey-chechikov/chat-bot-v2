"""Сетка по режиму SMA (11.10): лонг только выше SMA; смена режима — тейки и вход сняты, лоты бота закрыты ОДНИМ
рыночным reduceOnly; потерянный ответ не даёт второго ордера; частичное — остаток следующим; нет данных — новых
входов нет и ничего не закрывается."""
import json

import pytest

from tests.services.weex_grid.test_weex_grid_engine import Px, bot_open, make


def long_with_lot(tmp_path, regime):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"], order_qty="0.0012", regime_sma=100)
    g.regime_fn = lambda sym, n: regime["up"]
    g.tick()
    px.mid = 99_790.0                                      # вход исполнился
    g.tick()
    assert g.st["LONG"]["lots"] and g.st["LONG"]["lots"][0].get("tp_order")
    return g, ex, px


def markets(ex):
    return [o for o in ex.orders.values() if o.get("type") == "MARKET"]


def test_regime_flip_closes_long_by_market_and_blocks_entries(tmp_path):
    regime = {"up": True}
    g, ex, px = long_with_lot(tmp_path, regime)
    q = sum(float(l["qty"]) for l in g.st["LONG"]["lots"])
    tp_id = g.st["LONG"]["lots"][0]["tp_order"]["id"]
    regime["up"] = False
    g.tick()                                               # снять, отправить рыночный
    g.tick()                                               # разобрать исполнение
    m = markets(ex)
    assert len(m) == 1 and m[0]["reduceOnly"] and m[0]["side"] == "SELL" and float(m[0]["origQty"]) == pytest.approx(q)
    assert ex.orders[tp_id]["status"] == "CANCELED"
    assert g.st["LONG"]["lots"] == [] and g.st["LONG"].get("flatten") is None
    assert not [o for o in bot_open(ex)]                   # входа нет, пока режим вниз
    j = (tmp_path / "j.jsonl").read_text()
    assert "закрытие по режиму" in j
    g.tick()
    assert len(markets(ex)) == 1 and not bot_open(ex)
    regime["up"] = True
    g.tick()
    assert [o for o in bot_open(ex) if not o["reduceOnly"]]   # режим вверх — вход снова стоит


def test_lost_response_no_second_market(tmp_path):
    regime = {"up": True}
    g, ex, px = long_with_lot(tmp_path, regime)
    real = ex.place_market

    def lost(*a, **k):
        real(*a, **k)                                      # ордер дошёл и исполнился, ответ потерян
        raise TimeoutError("read timeout")
    ex.place_market = lost
    regime["up"] = False
    g.tick()
    ex.place_market = real
    assert g.st["LONG"]["flatten"] and not g.st["LONG"]["flatten"].get("id")
    for _ in range(3):
        g.tick()
    assert len(markets(ex)) == 1                           # второго рыночного нет
    assert g.st["LONG"]["lots"] == [] and g.st["LONG"].get("flatten") is None


def test_partial_market_rest_closed_next(tmp_path):
    regime = {"up": True}
    g, ex, px = long_with_lot(tmp_path, regime)
    q = sum(float(l["qty"]) for l in g.st["LONG"]["lots"])
    real = ex.place_market
    calls = []

    def half(symbol, side, position_side, qty, cid, reduce_only=False):
        calls.append(qty)
        r = real(symbol, side, position_side, qty, cid, reduce_only=reduce_only)
        if len(calls) == 1:                                # первый исполнен наполовину
            o = ex.orders[r["orderId"]]
            o["executedQty"] = f"{float(qty) / 2:.4f}"
        return r
    ex.place_market = half
    regime["up"] = False
    for _ in range(4):
        g.tick()
    assert len(calls) == 2 and float(calls[1]) == pytest.approx(q / 2)
    assert g.st["LONG"]["lots"] == []


def test_manual_partial_close_then_flip_no_endless_retries(tmp_path):
    """Оператор руками закрыл половину лонгов бота; смена режима: рыночное закрывает остаток, следующий отказ
    (позиции нет) — учёт приводится к бирже, без повторов каждые 10 с и без стопа сетки."""
    regime = {"up": True}
    g, ex, px = long_with_lot(tmp_path, regime)
    q = sum(float(l["qty"]) for l in g.st["LONG"]["lots"])
    ex.orders["manual1"] = {"clientOrderId": "manual1", "side": "SELL", "positionSide": "LONG", "price": "99790",
                            "origQty": f"{q / 2:.4f}", "status": "FILLED", "executedQty": f"{q / 2:.4f}",
                            "avgPrice": "99790", "reduceOnly": True}
    regime["up"] = False
    for _ in range(6):
        g.tick()
    m = markets(ex)
    assert len(m) == 1 and float(m[0]["executedQty"]) == pytest.approx(q / 2)   # закрыто ровно, что было
    assert g.st["LONG"]["lots"] == [] and not g.st["halted"]
    assert "внешнее закрытие" in (tmp_path / "j.jsonl").read_text()


def test_unknown_regime_no_entries_no_close(tmp_path):
    regime = {"up": True}
    g, ex, px = long_with_lot(tmp_path, regime)
    entry_before = [o for o in bot_open(ex) if not o["reduceOnly"]]
    regime["up"] = None
    g.tick()
    assert not markets(ex) and g.st["LONG"]["lots"]        # ничего не закрыто
    assert [o for o in bot_open(ex) if o["reduceOnly"]]    # тейк стоит
    assert not [o for o in bot_open(ex) if not o["reduceOnly"]] or not entry_before   # новых входов нет
    assert json.loads((tmp_path / "st.json").read_text())["regime"] is None
