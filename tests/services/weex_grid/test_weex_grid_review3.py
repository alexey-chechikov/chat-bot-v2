"""Сценарии перепроверки GPT 10.10 (docs/WEEX_GPT_REVIEW2_RECHECK_2026-10-10.md): сирота пишется до
отмены, live→dry ведёт сирот, неполный поиск pending не истекает, смена sides не бросает сторону,
курсор комиссии долговечен и мигрирует, досверка видит больше 100 сделок, потерянная привязка тейка
после учтённой части, старый вход и сниженный потолок, команды не пересекаются с проходом."""
import json
import threading
import time

import pytest

from services.weex_grid import engine as eg
from services.weex_grid import loop as lp
from tests.services.weex_grid.test_weex_grid_engine import Px, bot_open, make


class Crash(BaseException):
    """Падение процесса посреди прохода (не перехватывается обработчиками Exception)."""


def stray_order(oid="x9", qty="0.0012", status="NEW", exq="0"):
    return {"clientOrderId": f"b7gBLe{oid}", "side": "BUY", "positionSide": "LONG", "price": "99000.0",
            "origQty": qty, "status": status, "executedQty": exq, "avgPrice": "99000.0", "reduceOnly": False}


# ---------- P1-1: сирота записана на диск ДО отмены
def test_stray_persisted_before_cancel(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"])
    g.tick()                                            # свой вход есть → сирота пойдёт в strays
    ex.orders["x9"] = stray_order()

    def crash(oid):
        if oid == "x9":
            ex.orders["x9"].update(status="FILLED", executedQty="0.0012")   # исполнился во время отмены
            raise Crash()
        return {}
    ex.cancel = crash
    with pytest.raises(Crash):
        g.tick()
    g2 = eg.Grid(ex, g.cfg, state_path=tmp_path / "st.json", journal_path=tmp_path / "j.jsonl", now_fn=g.now)
    assert any(x["id"] == "x9" for x in g2.st["LONG"]["strays"])           # пережила падение
    ex.cancel = lambda oid: {}
    g2.tick()
    assert sum(float(l["qty"]) for l in g2.st["LONG"]["lots"]) == pytest.approx(0.0012)
    assert not g2.st["LONG"]["strays"]


# ---------- P1-2: live→dry ведёт сирот
def test_live_to_dry_keeps_tracking_strays(tmp_path, monkeypatch):
    px = Px()
    clock = {"t": 1_800_000_000.0}
    ex = eg.DryExchange(px, now_fn=lambda: clock["t"])
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps({**eg.DEFAULT, "enabled": False, "dry_run": True, "sides": ["LONG"]}))
    monkeypatch.setattr(eg, "CONFIG", cfg_path)
    monkeypatch.setattr(eg, "STATE", tmp_path / "st.json")
    monkeypatch.setattr(eg, "JOURNAL", tmp_path / "j.jsonl")
    monkeypatch.setattr(eg.load_config, "__defaults__", (cfg_path, None))
    monkeypatch.setattr(eg.save_config, "__defaults__", (cfg_path,))
    monkeypatch.setattr(eg, "GRIDS", ("BTC",))
    ex.orders["x9"] = stray_order(status="CANCELING")
    st = {"symbol": "BTCUSDT", "LONG": {**eg.new_side_state(),
                                        "strays": [{"id": "x9", "cid": "b7gBLex9", "price": 99000.0, "kind": "e"}]}}
    (tmp_path / "st.json").write_text(json.dumps(st))
    r = lp.Runner()
    monkeypatch.setattr(r, "_client", lambda: ex)
    ex.orders["x9"].update(status="FILLED", executedQty="0.0012")             # поздно исполнился
    r.tick_one("BTC")
    live = json.loads((tmp_path / "st.json").read_text())
    assert sum(float(l["qty"]) for l in live["LONG"]["lots"]) == pytest.approx(0.0012)
    assert not live["LONG"]["strays"]


# ---------- P1-3: неполный поиск pending не истекает
def test_incomplete_pending_search_never_expires(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"])
    sent = []
    g.send = sent.append

    def boom(*a, **k):
        raise TimeoutError("read timeout")
    real = ex.place_limit
    ex.place_limit = boom
    g.tick()
    ex.place_limit = real
    full = [{"orderId": f"m{i}", "clientOrderId": f"manual{i}"} for i in range(100)]
    ex.order_history = lambda symbol, limit=100, page=0, start_ms=None, end_ms=None: full   # всегда полная страница
    for _ in range(20):                                 # 200 с > TTL
        g.tick()
    assert g.st["LONG"]["pending"] and not bot_open(ex)                    # входа нет, намерение живо
    assert len(sent) == 1 and "не найден" in sent[0]


# ---------- P1-4: смена sides не бросает старую сторону
def test_side_removed_from_config_still_tracked(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px)                          # LONG + SHORT
    g.tick()
    long_id = g.st["LONG"]["entry"]["id"]
    g.cfg["sides"] = ["SHORT"]                          # оператор убрал LONG
    o = ex.orders[long_id]
    o.update(status="CANCELING")                         # отмена идёт, и тут исполнение
    real_cancel = ex.cancel
    ex.cancel = lambda oid: {} if oid == long_id else real_cancel(oid)
    g.tick()
    o.update(status="FILLED", executedQty=o["origQty"], avgPrice=o["price"])
    g.tick()
    g.tick()
    lots = g.st["LONG"]["lots"]
    assert len(lots) == 1 and lots[0]["tp_order"]                         # учтён и защищён тейком
    assert not [x for x in bot_open(ex) if x["positionSide"] == "LONG" and not x["reduceOnly"]]   # новых входов нет
    assert "ЛОНГ" in g.card(100_000.0)


# ---------- P2: курсор комиссии живого частичного ордера не истекает
def test_fee_cursor_of_live_partial_order_does_not_expire(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"], order_qty="0.0012")
    g.tick()
    oid = g.st["LONG"]["entry"]["id"]
    o = ex.orders[oid]
    o.update(executedQty="0.0004", avgPrice=o["price"])
    ex.trades[oid] = [{"id": "f1", "orderId": oid, "commission": "0.0063872", "maker": True, "time": 0}]
    g.tick()
    fees1 = g.st["LONG"]["fees"]
    assert fees1 == pytest.approx(0.0063872)
    for _ in range(400):                                # > часа, ордер всё ещё висит
        g.tick()
    o.update(executedQty="0.0012")
    ex.trades[oid].append({"id": "f2", "orderId": oid, "commission": "0.0127744", "maker": True, "time": 0})
    g.tick()
    assert g.st["LONG"]["fees"] == pytest.approx(0.0063872 + 0.0127744)   # не 0.0191616 сверху


def test_legacy_fee_done_migrated(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"], order_qty="0.0012")
    g.tick()
    oid = g.st["LONG"]["entry"]["id"]
    o = ex.orders[oid]
    o.update(executedQty="0.0004", avgPrice=o["price"])
    ex.trades[oid] = [{"id": "f1", "orderId": oid, "commission": "0.0063872", "maker": True, "time": 0}]
    g.tick()
    st = json.loads((tmp_path / "st.json").read_text())        # учёт как у кода до 10.10: fee_done, без fee_book
    st["LONG"]["entry"]["fee_done"] = 0.0063872
    st["LONG"]["fee_book"] = {}
    (tmp_path / "st.json").write_text(json.dumps(st))
    g2 = eg.Grid(ex, g.cfg, state_path=tmp_path / "st.json", journal_path=tmp_path / "j.jsonl", now_fn=g.now)
    o.update(executedQty="0.0012")
    ex.trades[oid].append({"id": "f2", "orderId": oid, "commission": "0.0127744", "maker": True, "time": 0})
    g2.tick()
    assert g2.st["LONG"]["fees"] == pytest.approx(0.0063872 + 0.0127744)


# ---------- P2: досверка комиссий видит больше 100 сделок окна
def test_late_fee_found_behind_100_newer_trades(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"])
    g.tick()
    real_trades = ex.user_trades
    ex.user_trades = lambda symbol, order_id=None, start_ms=None, end_ms=None: []   # сделки ещё не видны
    px.mid = 99_790.0
    g.tick()                                            # вход исполнен, комиссии в момент исполнения не видно
    assert g.st["LONG"]["fees"] == 0
    oid = next(iter(g.st["LONG"]["fee_book"]))
    t_fill = ex.trades[oid][0]["time"]
    for i in range(150):                                # 150 более новых сделок (ручных)
        ex.trades[f"z{i}"] = [{"id": f"z{i}", "orderId": f"z{i}", "commission": "0", "time": t_fill + 1000 + i}]
    ex.user_trades = real_trades                        # сделки появились; наша — за сотней более новых
    for _ in range(8):
        g.tick()
    assert g.st["LONG"]["fees"] == pytest.approx(0.0001 * 99_800 * 0.00016, rel=1e-6)


# ---------- граница: потерянная привязка тейка ПОСЛЕ учтённой части
def test_lost_take_mapping_after_recorded_partial_not_double(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"], order_qty="0.0012")
    g.tick()
    px.mid = 99_790.0
    g.tick()
    lot = g.st["LONG"]["lots"][0]
    tp = ex.orders[lot["tp_order"]["id"]]
    tp.update(executedQty="0.0004", avgPrice=tp["price"])
    g.tick()                                            # часть учтена, лот 0.0008
    realized = g.st["LONG"]["realized"]
    lot["tp_order"] = None                              # привязка потеряна
    g.save()
    g.tick()
    assert g.st["LONG"]["lots"][0]["qty"] == "0.0008"
    assert g.st["LONG"]["realized"] == pytest.approx(realized)            # не удвоено
    assert tp["status"] == "NEW"                                           # тот же тейк принят обратно


# ---------- граница: старый вход не остаётся сверх сниженного потолка
def test_standing_entry_dropped_when_cap_lowered_below_it(tmp_path):
    """Точный сценарий GPT: новый уровень чуть ниже стоящей заявки (в пределах допуска 0.05%) проходит
    потолок, а сама стоящая заявка — нет; раньше заявка оставалась сверх потолка."""
    px = Px(100_000.0)
    g, ex = make(tmp_path, px, sides=["SHORT"], order_qty="0.0012", max_notional_usd=1000.0)
    g.tick()
    e = g.st["SHORT"]["entry"]                          # шорт на 100 200
    px.mid = 99_980.0                                   # цена чуть ниже → желаемый уровень 100 180 (−0.02%)
    desired = 99_979.95 * 1.002
    g.cfg["max_notional_usd"] = (desired * 0.0012 + e["price"] * 0.0012) / 2   # между новым уровнем и стоящей
    g.tick()
    assert ex.orders[e["id"]]["status"] == "CANCELED"


# ---------- команды и проход не пересекаются
def test_command_waits_for_running_tick():
    order = []
    lp.STATE_LOCK.acquire()
    t = threading.Thread(target=lambda: (lp.STATE_LOCK.acquire(), order.append("command"), lp.STATE_LOCK.release()))
    t.start()
    time.sleep(0.05)
    order.append("tick done")
    lp.STATE_LOCK.release()
    t.join(1)
    assert order == ["tick done", "command"]
