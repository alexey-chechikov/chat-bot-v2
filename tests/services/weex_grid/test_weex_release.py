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
