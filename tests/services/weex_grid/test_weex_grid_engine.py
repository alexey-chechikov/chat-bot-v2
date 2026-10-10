"""Сетка WEEX на имитаторе биржи: решения, исполнения, защиты, чужие ордера, перезапуск."""
import pytest

from services.weex_grid import engine as eg


class Px:
    def __init__(self, mid=100_000.0):
        self.mid = mid

    def __call__(self):
        return self.mid - 0.05, self.mid + 0.05


def make(tmp_path, px, **cfg):
    conf = {**eg.DEFAULT, "enabled": True, "dry_run": True, **cfg}
    clock = {"t": 1_800_000_000.0}
    ex = eg.DryExchange(px, now_fn=lambda: clock["t"])

    def now():
        clock["t"] += 10
        return clock["t"]

    g = eg.Grid(ex, conf, state_path=tmp_path / "st.json", journal_path=tmp_path / "j.jsonl", now_fn=now)
    return g, ex


def bot_open(ex):
    return [o for o in ex.open_orders("BTCUSDT") if o["clientOrderId"].startswith(eg.PREFIX)]


def test_first_tick_places_both_entries(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px)
    g.tick()
    o = {x["positionSide"]: x for x in bot_open(ex)}
    assert float(o["LONG"]["price"]) == pytest.approx(99_800.0, abs=0.2) and o["LONG"]["side"] == "BUY"
    assert float(o["SHORT"]["price"]) == pytest.approx(100_200.0, abs=0.2) and o["SHORT"]["side"] == "SELL"


def test_fill_then_take_profit(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"])
    g.tick()
    px.mid = 99_790.0                       # пересекли вход
    g.tick()
    s = g.st["LONG"]
    assert len(s["lots"]) == 1 and s["lots"][0]["tp_order"] is not None
    assert float(s["entry"]["price"]) == pytest.approx(99_800 * 0.998, abs=0.2)   # следующий шаг ниже входа
    px.mid = 100_200.0                      # дошли до тейка 99 800·1.003 = 100 099.4
    g.tick()
    g.tick()
    assert s["n_tps"] == 1 and not s["lots"] and s["realized"] > 0.029


def test_refill_after_take_like_ginarea(tmp_path):
    """После тейка нижнего лонга следующий вход — на шаг ниже нижнего ОТКРЫТОГО лота, а не
    ниже последнего исполненного (как у GinArea, журнал 5021652508)."""
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"])
    g.tick()
    for m in (99_790, 99_590):                # два входа: 99 800 и 99 600.4
        px.mid = m
        g.tick()
    lots = g.st["LONG"]["lots"]
    assert len(lots) == 2
    px.mid = 99_950.0                         # тейк нижнего (99 600.4 × 1.003 = 99 899.2)
    g.tick()
    g.tick()
    assert len(lots) == 1 and lots[0]["entry"] == pytest.approx(99_800.0, abs=0.2)
    assert g.st["LONG"]["entry"]["price"] == pytest.approx(99_800 * 0.998, abs=0.2)


def test_trailing_when_flat(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"])
    g.tick()
    first = g.st["LONG"]["entry"]["price"]
    px.mid = 101_000.0
    g.tick()
    assert g.st["LONG"]["entry"]["price"] > first + 900
    assert len(bot_open(ex)) == 1          # старый вход снят


def test_max_lots_and_notional(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"], max_lots_per_side=2)
    g.tick()
    for m in (99_790, 99_590, 99_390, 99_190, 98_990):
        px.mid = m
        g.tick()
    assert len(g.st["LONG"]["lots"]) == 2 and g.st["LONG"]["entry"] is None
    assert "максимум" in g.st["LONG"]["blocked"]


def test_daily_loss_stop_halts_and_cancels(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"], daily_loss_stop_usd=0.05)
    g.tick()
    for m in (99_790, 99_590, 99_390, 98_000):
        px.mid = m
        g.tick()
    assert g.st["halted"] and g.st["LONG"]["entry"] is None
    assert all(o["reduceOnly"] for o in bot_open(ex))          # остались только тейки


def test_disable_removes_entries_keeps_takes(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"])
    g.tick()
    px.mid = 99_790.0
    g.tick()
    g.cfg["enabled"] = False
    g.tick()
    opens = bot_open(ex)
    assert opens and all(o["reduceOnly"] for o in opens)


def test_foreign_orders_untouched(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px)
    ex.orders["manual1"] = {"clientOrderId": "4f1540ad-manual", "side": "BUY", "positionSide": "LONG",
                            "price": "77793.7", "origQty": "0.0062", "status": "NEW", "executedQty": "0",
                            "avgPrice": "0", "reduceOnly": False}
    for m in (100_000, 101_000, 99_000, 100_500):
        px.mid = m
        g.tick()
    g.cfg["enabled"] = False
    g.tick()
    assert ex.orders["manual1"]["status"] == "NEW"


def test_restart_no_duplicates(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px)
    g.tick()
    g2 = eg.Grid(ex, g.cfg, state_path=tmp_path / "st.json", journal_path=tmp_path / "j.jsonl",
                 now_fn=g.now)
    g2.tick()
    assert len(bot_open(ex)) == 2


def test_fill_during_trailing_cancel_is_recorded(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"])
    g.tick()
    oid = g.st["LONG"]["entry"]["id"]
    ex.orders[oid].update(status="FILLED", executedQty=ex.orders[oid]["origQty"], avgPrice=ex.orders[oid]["price"])
    ex.trades[oid] = [{"commission": "0.0016", "maker": True}]
    px.mid = 101_000.0                      # бот хочет переставить вход выше, а он уже исполнен
    g._side("LONG", 100_999.95, 101_000.05, 101_000.0, {oid}, enabled=True)   # список ещё «видит» ордер открытым
    assert len(g.st["LONG"]["lots"]) == 1


def test_take_uses_lot_qty_after_size_change(tmp_path):
    """09.10: размер сменили 0.0001 → 0.0012, тейк старого лота должен быть 0.0001."""
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"])
    g.tick()
    px.mid = 99_790.0
    g.cfg["order_qty"] = "0.0012"           # оператор сменил размер, пока вход стоял
    g.tick()
    takes = [o for o in bot_open(ex) if o["reduceOnly"]]
    assert takes and all(o["origQty"] == "0.0001" for o in takes)
    entries = [o for o in bot_open(ex) if not o["reduceOnly"]]
    assert entries and entries[0]["origQty"] == "0.0012"


def test_wrong_size_take_is_replaced(tmp_path):
    """Тейк на бирже не того объёма (биржа урезала reduceOnly) → снять и поставить объёмом лота."""
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"])
    g.tick()
    px.mid = 99_790.0
    g.tick()
    lot = g.st["LONG"]["lots"][0]
    ex.orders[lot["tp_order"]["id"]]["origQty"] = "0.0002"       # как на WEEX 09.10
    old = lot["tp_order"]["id"]
    g.tick()
    assert ex.orders[old]["status"] == "CANCELED"
    takes = [o for o in bot_open(ex) if o["reduceOnly"]]
    assert len(takes) == 1 and takes[0]["origQty"] == "0.0001"


def test_phantom_lot_dropped_when_position_gone(tmp_path):
    """09.10: урезанный тейк закрыл два лота, в учёте остался лишний — снимаем по позиции биржи."""
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"])
    g.tick()
    px.mid = 99_790.0
    g.tick()
    lot = dict(g.st["LONG"]["lots"][0])
    ghost = {**lot, "entry": 99_700.0, "tp_order": None, "t": lot["t"] + 1}
    g.st["LONG"]["lots"].append(ghost)                         # на бирже его нет

    def reject(*a, **k):
        return {"success": False, "orderId": None}
    real_place = ex.place_limit
    ex.place_limit = lambda symbol, side, ps, qty, price, cid, reduce_only=False, post_only=True: (
        reject() if reduce_only else real_place(symbol, side, ps, qty, price, cid, reduce_only, post_only))
    g.tick()
    assert ghost not in g.st["LONG"]["lots"] and len(g.st["LONG"]["lots"]) == 1


def test_entry_replaced_after_size_change(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"])
    g.tick()
    g.cfg["order_qty"] = "0.0012"
    g.tick()
    entries = [o for o in bot_open(ex) if not o["reduceOnly"]]
    assert len(entries) == 1 and entries[0]["origQty"] == "0.0012"


def test_exchange_error_does_not_break_tick(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px)

    def boom(*a, **k):
        raise RuntimeError("HTTP 400: Business precondition not satisfied")
    ex.place_limit = boom
    g.tick()                                # не должно падать
    assert g.st["LONG"]["entry"] is None and g.st["SHORT"]["entry"] is None


def test_stress_budget_blocks_entry(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"], order_qty="0.01")
    ex.balance = 50.0                       # крошечный баланс → стресс-ход не влезает в 25%
    g.tick()
    assert g.st["LONG"]["entry"] is None and "стресс" in g.st["LONG"]["blocked"]
