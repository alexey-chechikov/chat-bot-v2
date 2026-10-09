"""Сценарии из разбора GPT 10.10: потерянный ответ биржи, частичные исполнения, внешнее закрытие,
потолок по себестоимости, сироты, переключение live→dry."""
import json

import pytest

from services.weex_grid import engine as eg
from services.weex_grid import loop as lp
from tests.services.weex_grid.test_weex_grid_engine import Px, bot_open, make


def lose_response(ex, fill=False):
    """Ордер на бирже создаётся, а ответ теряется (исключение)."""
    real = ex.place_limit

    def place(*a, **k):
        r = real(*a, **k)
        if fill and r.get("orderId"):
            o = ex.orders[r["orderId"]]
            o.update(status="FILLED", executedQty=o["origQty"], avgPrice=o["price"])
        ex.place_limit = real                       # теряется только первый ответ
        raise TimeoutError("read timeout")
    ex.place_limit = place


def test_lost_response_does_not_duplicate_entry(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"])
    lose_response(ex)
    g.tick()                                        # ордер на бирже есть, учёт о нём не знает
    assert g.st["LONG"]["entry"] is None and g.st["LONG"]["pending"]
    g.tick()                                        # найден по clientOrderId — привязан, второй не ставится
    assert len(bot_open(ex)) == 1 and g.st["LONG"]["entry"] is not None and not g.st["LONG"]["pending"]
    g.tick()
    assert len(bot_open(ex)) == 1


def test_lost_response_filled_order_recorded_once(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"])
    lose_response(ex, fill=True)                    # ордер дошёл и сразу исполнился
    g.tick()
    g.tick()                                        # найден в истории → лот записан
    g.tick()
    lots = g.st["LONG"]["lots"]
    assert len(lots) == 1 and lots[0]["qty"] == "0.0001"
    entries = [o for o in ex.orders.values() if not o["reduceOnly"] and o["status"] == "FILLED"]
    assert len(entries) == 1


def test_lost_response_not_placed_expires(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"])

    def boom(*a, **k):
        ex.place_limit = real
        raise TimeoutError("read timeout")
    real = ex.place_limit
    ex.place_limit = boom                           # не дошёл до биржи
    g.tick()
    assert g.st["LONG"]["pending"]
    for _ in range(14):                             # 10 с на проход → 140 с > PENDING_TTL
        g.tick()
    assert not g.st["LONG"]["pending"] and len(bot_open(ex)) == 1


def test_orphan_entry_adopted_when_side_has_none(tmp_path):
    """Сирота-вход при пустой стороне становится входом стороны: исполненное — лот, второй вход не ставится."""
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"])
    ex.orders["x1"] = {"clientOrderId": "b7gBLe1", "side": "BUY", "positionSide": "LONG", "price": "99000.0",
                       "origQty": "0.0002", "status": "NEW", "executedQty": "0.0001", "avgPrice": "99000.0",
                       "reduceOnly": False}
    g.tick()
    assert g.st["LONG"]["entry"]["id"] == "x1"
    assert [l["qty"] for l in g.st["LONG"]["lots"]] == ["0.0001"]
    assert len([o for o in bot_open(ex) if not o["reduceOnly"]]) == 1


def test_orphan_entry_tracked_until_terminal_when_cancel_lags(tmp_path):
    """Разбор GPT P1-2: отмена сироты не прошла (CANCELING), исполнения во время отмены не теряются
    и не удваиваются, второй вход на стороне не ставится, пока сирота не в конечном статусе."""
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"])
    g.tick()                                          # свой вход стоит
    ex.orders["x2"] = {"clientOrderId": "b7gBLe9", "side": "BUY", "positionSide": "LONG", "price": "99000.0",
                       "origQty": "0.0012", "status": "NEW", "executedQty": "0.0004", "avgPrice": "99000.0",
                       "reduceOnly": False}
    real_cancel = ex.cancel
    ex.cancel = lambda oid: (ex.orders[oid].update(status="CANCELING") if oid == "x2" else real_cancel(oid)) or {}
    g.tick()
    g.tick()                                          # повтор снимка — учёт не растёт
    sum_q = sum(float(l["qty"]) for l in g.st["LONG"]["lots"])
    assert sum_q == pytest.approx(0.0004)
    assert g.st["LONG"]["strays"] and "лишний" in g.st["LONG"]["blocked"] or g.st["LONG"]["entry"]
    ex.orders["x2"].update(status="FILLED", executedQty="0.0012")   # поздно исполнился и ушёл из открытых
    g.tick()
    assert sum(float(l["qty"]) for l in g.st["LONG"]["lots"]) == pytest.approx(0.0012)
    assert not g.st["LONG"]["strays"]
    assert all(l.get("tp_order") for l in g.st["LONG"]["lots"])


def test_partial_entry_gets_take_while_order_live(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"], order_qty="0.0012")
    g.tick()
    oid = g.st["LONG"]["entry"]["id"]
    ex.orders[oid].update(executedQty="0.0004", avgPrice=ex.orders[oid]["price"])   # частично, ещё NEW
    g.tick()
    lots = g.st["LONG"]["lots"]
    assert len(lots) == 1 and lots[0]["qty"] == "0.0004" and lots[0]["tp_order"]
    takes = [o for o in bot_open(ex) if o["reduceOnly"]]
    assert takes and takes[0]["origQty"] == "0.0004"
    g.tick()                                        # повтор того же снимка — ничего нового
    assert len(g.st["LONG"]["lots"]) == 1
    o = ex.orders[oid]
    o.update(status="FILLED", executedQty="0.0012")
    g.tick()
    assert sorted(l["qty"] for l in g.st["LONG"]["lots"]) == ["0.0004", "0.0008"]   # прирост, не 0.0012


def test_partial_take_then_cancel_closes_only_rest(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"], order_qty="0.0012")
    g.tick()
    px.mid = 99_790.0
    g.tick()
    lot = g.st["LONG"]["lots"][0]
    tp = ex.orders[lot["tp_order"]["id"]]
    tp.update(status="CANCELED", executedQty="0.0004", avgPrice=tp["price"])       # частично и снят
    g.tick()
    lots = g.st["LONG"]["lots"]
    assert len(lots) == 1 and lots[0]["qty"] == "0.0008"
    takes = [o for o in bot_open(ex) if o["reduceOnly"]]
    assert len(takes) == 1 and takes[0]["origQty"] == "0.0008"
    assert g.st["LONG"]["realized"] == pytest.approx(0.0004 * (float(tp["price"]) - lot["entry"]), rel=1e-6)


def test_external_close_is_not_free(tmp_path):
    """Лот закрыт вручную по низкой цене: снимаем из учёта, но убыток записываем (оценка по цене)."""
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"])
    sent = []
    g.send = sent.append
    g.tick()
    px.mid = 99_790.0
    g.tick()
    g.cfg["enabled"] = False                         # новых входов не будет — проверяем только внешнее закрытие
    g.tick()
    lot = g.st["LONG"]["lots"][0]
    ex.orders[lot["tp_order"]["id"]]["status"] = "CANCELED"   # тейк снят, позиции на бирже нет
    for o in ex.orders.values():
        if not o["reduceOnly"] and o["status"] == "FILLED":
            o.update(status="CANCELED", executedQty="0")   # имитатор: позиции стороны 0

    def reject(*a, **k):
        return {"success": False, "orderId": None}
    real = ex.place_limit
    ex.place_limit = lambda symbol, side, ps, qty, price, cid, reduce_only=False, post_only=True: (
        reject() if reduce_only else real(symbol, side, ps, qty, price, cid, reduce_only, post_only))
    px.mid = 90_000.0
    g.tick()
    assert not g.st["LONG"]["lots"]
    assert g.st["LONG"]["realized"] == pytest.approx(0.0001 * (90_000.0 - lot["entry"]), rel=1e-3)
    assert sent and "закрыто не сеткой" in sent[0]


def test_cap_counts_cost_not_only_value(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"], order_qty="0.01", max_notional_usd=2_100.0, max_lots_per_side=50)
    g.st["LONG"]["lots"] = [{"entry": 100_000.0, "qty": "0.01", "tp": 100_300.0, "tp_order": None, "t": 1.0},
                            {"entry": 100_000.0, "qty": "0.01", "tp": 100_300.0, "tp_order": None, "t": 2.0}]
    ok, why = g.may_add("LONG", 59_000.0, 60_000.0)  # стоимость 2×$600 = $1 200, себестоимость $2 000
    assert not ok and "потолок" in why


def test_live_to_dry_cancels_live_entries(tmp_path, monkeypatch):
    px = Px()
    ex = eg.DryExchange(px)
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps({**eg.DEFAULT, "enabled": True, "dry_run": False, "sides": ["LONG"]}))
    monkeypatch.setattr(eg, "CONFIG", cfg_path)
    monkeypatch.setattr(eg, "STATE", tmp_path / "st.json")
    monkeypatch.setattr(eg, "JOURNAL", tmp_path / "j.jsonl")
    monkeypatch.setattr(eg.load_config, "__defaults__", (cfg_path, None))
    monkeypatch.setattr(eg.save_config, "__defaults__", (cfg_path,))
    monkeypatch.setattr(eg, "GRIDS", ("BTC",))
    r = lp.Runner()
    monkeypatch.setattr(r, "_client", lambda: ex)
    r.tick_one("BTC")                                 # живой проход: стоит вход
    assert len(bot_open(ex)) == 1
    lp.command("dry")                                 # оператор переключил в холостой
    r.tick_one("BTC")
    assert not [o for o in bot_open(ex) if not o["reduceOnly"]]   # живой вход снят
