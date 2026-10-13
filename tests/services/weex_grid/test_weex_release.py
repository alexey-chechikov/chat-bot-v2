"""Передача стороны оператору (11.10: «шорт-сетку оставляю за собой»): бот снимает свои ордера стороны, учитывает
исполненное до снятия и забывает лоты; другая сторона работает дальше; переданная сторона больше не оживает."""
import json

import pytest

from tests.services.weex_grid.test_weex_grid_engine import Px, bot_open, make


def test_release_short_keeps_long(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG", "SHORT"], order_qty="0.0012")
    g.tick()
    px.mid = 100_260.0                                     # шорт-вход исполнился
    g.tick()
    lot = g.st["SHORT"]["lots"][0]
    tp = ex.orders[lot["tp_order"]["id"]]
    tp.update(executedQty="0.0004", avgPrice=tp["price"])  # тейк успел исполниться на треть
    realized0 = g.st["SHORT"]["realized"]
    g.cfg["sides"], g.cfg["release_sides"] = ["LONG"], ["SHORT"]
    g.tick()
    s = g.st["SHORT"]
    assert s["lots"] == [] and s["entry"] is None and not s["strays"]
    assert tp["status"] == "CANCELED"
    assert s["realized"] > realized0                       # часть тейка учтена до передачи
    assert not [o for o in bot_open(ex) if o["positionSide"] == "SHORT"]
    j = [json.loads(x) for x in (tmp_path / "j.jsonl").read_text().splitlines()]
    hand = [x for x in j if x.get("kind") == "передано оператору"]
    assert len(hand) == 1 and float(hand[0]["qty"]) == pytest.approx(0.0008)
    assert g.st["LONG"]["entry"] is not None               # лонг работает
    px.mid = 100_600.0
    g.tick()
    g.tick()
    assert not [o for o in bot_open(ex) if o["positionSide"] == "SHORT"]   # переданная сторона не оживает
    assert len([x for x in (tmp_path / "j.jsonl").read_text().splitlines() if "передано" in x]) == 1


def _short_size(ex):
    return next(float(p["size"]) for p in ex.futures_positions() if p["side"] == "SHORT")


@pytest.mark.parametrize("regime_after", [False, None, True])
def test_manual_short_untouched_by_regime_close(tmp_path, regime_after):
    """Живая схема 12.10: бот ведёт только LONG по SMA100, SHORT передан оператору. Ручной шорт оператора (cid не b7g)
    и его ручной тейк на той же стороне переживают закрытие лонгов по режиму, неизвестный режим и возврат режима:
    ни одного ордера бота на SHORT, рыночное закрытие — только LONG и ровно на лоты бота (ревью скилов 12.10, [16])."""
    regime = {"up": True}
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"], release_sides=["SHORT"], regime_sma=100, order_qty="0.0012")
    g.regime_fn = lambda sym, n: regime["up"]
    ex.orders["op_short"] = {"clientOrderId": "manual-short-uuid", "side": "SELL", "positionSide": "SHORT",
                             "price": "100000", "origQty": "0.0500", "status": "FILLED", "executedQty": "0.0500",
                             "avgPrice": "100000", "reduceOnly": False}
    ex.orders["op_tp"] = {"clientOrderId": "manual-tp-uuid", "side": "BUY", "positionSide": "SHORT",
                          "price": "90000", "origQty": "0.0500", "status": "NEW", "executedQty": "0",
                          "avgPrice": "0", "reduceOnly": True}
    # ручной ЛОНГ оператора на той же стороне, что и лоты бота: биржа владельца не различает — закрытие по режиму
    # обязано снять ровно лоты бота, а не всю LONG-позицию (раунд 2 ревью, T1)
    ex.orders["op_long"] = {"clientOrderId": "manual-long-uuid", "side": "BUY", "positionSide": "LONG",
                            "price": "100000", "origQty": "0.0050", "status": "FILLED", "executedQty": "0.0050",
                            "avgPrice": "100000", "reduceOnly": False}
    g.tick()
    px.mid = 99_790.0                                      # лонг-вход бота исполнился
    g.tick()
    lots_q = sum(float(l["qty"]) for l in g.st["LONG"]["lots"])
    assert lots_q > 0
    regime["up"] = regime_after
    for _ in range(4):
        g.tick()
    if regime_after is True:
        regime["up"] = False                               # и всё же закрытие по режиму позже
        for _ in range(3):
            g.tick()
    assert _short_size(ex) == pytest.approx(0.0500)        # ручной шорт цел
    assert ex.orders["op_tp"]["status"] == "NEW"           # ручной тейк оператора не снят
    bot_short = [o for o in ex.orders.values()
                 if o["positionSide"] == "SHORT" and o["clientOrderId"].startswith("b7g")]
    assert bot_short == []                                 # ни одного ордера бота на переданной стороне
    mk = [o for o in ex.orders.values() if o.get("type") == "MARKET"]
    long_size = next(float(p["size"]) for p in ex.futures_positions() if p["side"] == "LONG")
    if regime_after is None:
        assert mk == [] and g.st["LONG"]["lots"]           # режим неизвестен — ничего не закрыто
        assert long_size == pytest.approx(0.005 + lots_q)
    else:
        assert len(mk) == 1 and mk[0]["positionSide"] == "LONG"
        assert float(mk[0]["origQty"]) == pytest.approx(lots_q)
        assert g.st["LONG"]["lots"] == []
        assert long_size == pytest.approx(0.005)           # ручной лонг оператора цел
