"""Сценарии перепроверки GPT по коду 3173dfb (docs/WEEX_GPT_REVIEW3_RECHECK_2026-10-10.md): неясный тейк не
мешает остановить вход, потерянная привязка тейка + новое исполнение до восстановления, расхождение часов
с биржей, живой курсор старше недели, плотная история сделок; гонка /weex start с настоящим проходом."""
import json
import threading
import time

import pytest

from services.weex_grid import engine as eg
from services.weex_grid import loop as lp
from tests.services.weex_grid.test_weex_grid_engine import Px, bot_open, make


# ---------- P1-1: неясный тейк не мешает /weex stop снять известный вход
def test_unknown_take_does_not_block_stop(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"], order_qty="0.0012")
    g.tick()
    oid = g.st["LONG"]["entry"]["id"]
    o = ex.orders[oid]
    o.update(executedQty="0.0004", avgPrice=o["price"])          # вход исполнен на треть

    def boom(*a, **k):
        raise TimeoutError("read timeout")                       # ответ на постановку тейка потерян
    real = ex.place_limit
    ex.place_limit = boom
    g.tick()
    ex.place_limit = real
    assert g.st["LONG"]["pending"]
    full = [{"orderId": f"m{i}", "clientOrderId": f"manual{i}"} for i in range(100)]
    ex.order_history = lambda symbol, limit=100, page=0, start_ms=None, end_ms=None: full   # поиск неполон
    g.cfg["enabled"] = False                                     # /weex stop
    g.tick()
    assert ex.orders[oid]["status"] == "CANCELED"                # известный вход снят несмотря на неясный тейк
    assert g.st["LONG"]["pending"]                               # неясный тейк по-прежнему не продублирован
    assert not [x for x in bot_open(ex) if x["reduceOnly"]]


# ---------- P1-2: потеря привязки тейка + новое исполнение до восстановления
def test_lost_take_mapping_then_new_partial_counted_once(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"], order_qty="0.0012")
    g.tick()
    px.mid = 99_790.0
    g.tick()
    lot = g.st["LONG"]["lots"][0]
    entry = lot["entry"]
    tp = ex.orders[lot["tp_order"]["id"]]
    tp.update(executedQty="0.0004", avgPrice=tp["price"])
    g.tick()                                                     # учтено 0.0004, лот 0.0008
    realized = g.st["LONG"]["realized"]
    lot["tp_order"] = None                                       # привязка потеряна
    g.save()
    tp.update(executedQty="0.0006")                              # до восстановления исполнилось ещё 0.0002
    g2 = eg.Grid(ex, g.cfg, state_path=tmp_path / "st.json", journal_path=tmp_path / "j.jsonl", now_fn=g.now)
    g2.tick()
    lots = g2.st["LONG"]["lots"]
    assert len(lots) == 1 and lots[0]["qty"] == "0.0006"         # на бирже остаток 0.0006
    assert g2.st["LONG"]["realized"] == pytest.approx(realized + 0.0002 * (float(tp["price"]) - entry), rel=1e-6)


# ---------- P2-3: часы биржи впереди на 3 минуты
class SkewedExchange(eg.DryExchange):
    """История ордеров фильтруется по времени БИРЖИ, которое впереди локального."""

    def __init__(self, *a, skew_s=180.0, **k):
        super().__init__(*a, **k)
        self.skew = skew_s
        self._offset_ms = skew_s * 1000                          # как у клиента после sync_time

    def place_limit(self, *a, **k):
        r = super().place_limit(*a, **k)
        if r.get("orderId"):
            self.orders[r["orderId"]]["time"] = int((self.now_fn() + self.skew) * 1000)
        return r

    def order_history(self, symbol, limit=100, page=0, start_ms=None, end_ms=None):
        rows = [{"orderId": k, **v} for k, v in self.orders.items()
                if (start_ms is None or v.get("time", 0) >= start_ms) and (end_ms is None or v.get("time", 0) <= end_ms)]
        return rows[page * limit:(page + 1) * limit]


def test_clock_skew_pending_still_found(tmp_path):
    px = Px()
    clock = {"t": 1_800_000_000.0}

    def now():
        clock["t"] += 10
        return clock["t"]
    ex = SkewedExchange(px, now_fn=lambda: clock["t"])
    cfg = {**eg.DEFAULT, "enabled": True, "dry_run": True, "sides": ["LONG"], "order_qty": "0.0012"}
    g = eg.Grid(ex, cfg, state_path=tmp_path / "st.json", journal_path=tmp_path / "j.jsonl", now_fn=now)
    real = ex.place_limit

    def place(*a, **k):
        r = real(*a, **k)
        o = ex.orders[r["orderId"]]
        o.update(status="FILLED", executedQty=o["origQty"], avgPrice=o["price"])
        ex.place_limit = real
        raise TimeoutError("read timeout")
    ex.place_limit = place
    g.tick()
    for _ in range(15):                                          # 150 с > TTL
        g.tick()
    assert sum(float(l["qty"]) for l in g.st["LONG"]["lots"]) == pytest.approx(0.0012)
    entries = [o for o in ex.orders.values() if not o["reduceOnly"]]
    assert len(entries) == 2                                     # найденный + следующий уровень, не дубль на том же


# ---------- P2-4/5: старый живой курсор и плотная история не мешают досверке
def test_late_fee_settled_with_week_old_live_cursor_and_dense_history(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"])
    g.tick()
    eid = g.st["LONG"]["entry"]["id"]                            # вход «висит» 8 суток — живой старый курсор
    g.st["LONG"]["fee_book"][eid] = {"done": 0.0, "t": g.now() - 8 * 86400, "t0": g.now() - 8 * 86400}
    real_trades = ex.user_trades
    ex.user_trades = lambda symbol, order_id=None, start_ms=None, end_ms=None: []
    px.mid = 99_790.0
    g.tick()                                                     # вход исполнен, комиссии не видно
    assert g.st["LONG"]["fees"] == 0
    t_fill = ex.trades[eid][0]["time"]
    for i in range(8000):                                        # плотная история
        ex.trades[f"z{i}"] = [{"id": f"z{i}", "orderId": f"z{i}", "commission": "0", "time": t_fill + i}]

    def weex_like(symbol, order_id=None, start_ms=None, end_ms=None):
        if start_ms is not None and end_ms is not None and end_ms - start_ms > 7 * 86_400_000:
            raise ValueError("HTTP 400: окно startTime..endTime больше 7 суток")   # как документирует WEEX
        return real_trades(symbol, order_id, start_ms, end_ms)
    ex.user_trades = weex_like
    for _ in range(8):
        g.tick()
    assert g.st["LONG"]["fees"] == pytest.approx(0.0001 * 99_800 * 0.00016, rel=1e-6)


# ---------- гонка: настоящий проход и настоящая команда /weex start
def test_start_command_waits_for_real_tick(tmp_path, monkeypatch):
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
    (tmp_path / "st.json").write_text(json.dumps({"symbol": "BTCUSDT", "halted": True, "halt_reason": "тест"}))
    r = lp.Runner()
    monkeypatch.setattr(r, "_client", lambda: ex)
    real_tick = eg.Grid.tick

    def slow_tick(self):
        time.sleep(0.3)                                          # проход загрузил halted=true и долго идёт
        real_tick(self)
    monkeypatch.setattr(eg.Grid, "tick", slow_tick)
    th = threading.Thread(target=r.tick)
    th.start()
    time.sleep(0.05)
    reply = lp.command("start")                                  # оператор жмёт /weex start во время прохода
    th.join(2)
    st = json.loads((tmp_path / "st.json").read_text())
    assert "включена" in reply and st["halted"] is False         # команда применилась ПОСЛЕ прохода
