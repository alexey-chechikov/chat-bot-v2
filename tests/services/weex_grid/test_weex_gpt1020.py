"""Разбор GPT ec48a3a (сравнение с igorauts, 20.10): (1) частично исполненная сирота-вход и общий потолок; (2) ответ
сделок на пределе 100 — комиссия неполная; (3) общая сверка позиции всех сеток символа/стороны."""
from __future__ import annotations

import json

from services.weex_grid import engine as eg
from services.weex_grid import loop

LIVE_STATUSES = eg.LIVE


class LiveLike(eg.DryExchange):
    """Как живая биржа: частично исполненный ордер виден в открытых (независимо от правки DryExchange)."""
    def open_orders(self, symbol):
        return [{"orderId": k, **v} for k, v in self.orders.items() if v["status"] in LIVE_STATUSES]


class Px:
    def __call__(self):
        return 99999.95, 100000.05


def make(tmp_path, ex_cls=LiveLike, **cfg):
    conf = {**eg.DEFAULT, "enabled": True, "dry_run": True, **cfg}
    clock = {"t": 1_800_000_000.0}
    ex = ex_cls(Px(), now_fn=lambda: clock["t"])

    def now():
        clock["t"] += 10
        return clock["t"]
    g = eg.Grid(ex, conf, state_path=tmp_path / "st.json", journal_path=tmp_path / "j.jsonl", now_fn=now)
    return g, ex


def add_partial_orphan(ex, status="PARTIALLY_FILLED"):
    ex.orders["orph"] = {"clientOrderId": "b7gBLe1799999999", "side": "BUY", "positionSide": "LONG", "price": "99800",
                         "origQty": "0.0012", "status": status, "executedQty": "0.0004", "avgPrice": "99800",
                         "reduceOnly": False}
    ex.trades["orph"] = [{"id": "torph", "orderId": "orph", "commission": str(0.0004 * 99800 * 0.00016),
                          "maker": True, "price": "99800", "qty": "0.0004", "time": 1_800_000_000_000}]


def short_entries(ex):
    return [o for k, o in ex.orders.items() if o["positionSide"] == "SHORT" and not o["reduceOnly"]
            and o["status"] in LIVE_STATUSES]


def long_qty(g):
    return sum(float(l["qty"]) for l in g.st["LONG"]["lots"])


# ---------------------------------------------------------------- (1) сирота и общий потолок
def test_partial_orphan_fill_reserved_before_opposite_entry(tmp_path):
    """Потолок $201: сирота ≈$119.76 целиком (исполнено $39.92 + остаток $79.84) — шорт $120.24 не помещается.
    На ec48a3a: резервировался только остаток → шорт ставился, занято $240."""
    g, ex = make(tmp_path, sides=["LONG", "SHORT"], order_qty="0.0012", portfolio_free_usd=201.0,
                 max_notional_usd=100000.0)
    add_partial_orphan(ex)
    g.tick()
    assert abs(long_qty(g) - 0.0004) < 1e-12                      # исполненное сироты — лот
    assert not short_entries(ex)
    assert "общий потолок" in g.st["SHORT"]["blocked"]


def test_partial_orphan_room_boundary(tmp_path):
    """Места хватает на сироту и шорт ($241 ≥ $119.76 + $120.24) — шорт ставится: резерв не завышен."""
    g, ex = make(tmp_path, sides=["LONG", "SHORT"], order_qty="0.0012", portfolio_free_usd=241.0,
                 max_notional_usd=100000.0)
    add_partial_orphan(ex)
    g.tick()
    assert len(short_entries(ex)) == 1


def test_orphan_with_known_cursor_not_double_reserved(tmp_path):
    """Исполненное уже учтено курсором (лот есть, «свободное» его включает) — резервируется только остаток $79.84:
    шорт $120.24 при свободных $201 помещается (201 − 79.84 = 121.16)."""
    g, ex = make(tmp_path, sides=["LONG", "SHORT"], order_qty="0.0012", portfolio_free_usd=201.0,
                 max_notional_usd=100000.0)
    add_partial_orphan(ex)
    g.st["LONG"]["order_fills"]["orph"] = {"filled": 0.0004, "val": 0.0004 * 99800, "t": 1_800_000_000.0}
    g.st["LONG"]["lots"].append({"entry": 99800.0, "qty": "0.0004", "tp": 101197.2, "tp_order": None,
                                 "t": 1_799_999_000.0, "parent": "orph"})
    g.tick()
    assert len(short_entries(ex)) == 1
    assert abs(long_qty(g) - 0.0004) < 1e-12                      # повторно не учтено


def test_partial_orphan_cancel_and_repeated_snapshot_no_double_lot(tmp_path):
    g, ex = make(tmp_path, sides=["LONG"], order_qty="0.0012", portfolio_free_usd=1000.0, max_notional_usd=100000.0)
    add_partial_orphan(ex)
    g.tick()
    g.tick()                                                      # тот же снимок — без второго лота
    assert abs(long_qty(g) - 0.0004) < 1e-12
    ex.orders["orph"]["status"] = "CANCELED"                      # остаток снят, исполненное то же
    g.tick()
    g.tick()
    assert abs(long_qty(g) - 0.0004) < 1e-12 and len(g.st["LONG"]["lots"]) == 1


def test_simulator_shows_partially_filled_as_open():
    ex = eg.DryExchange(Px())
    ex.orders["x"] = {"status": "PARTIALLY_FILLED", "origQty": "1", "executedQty": "0.5"}
    assert [o["orderId"] for o in ex.open_orders("BTCUSDT")] == ["x"]


# ---------------------------------------------------------------- (2) ответ сделок на пределе
class ManyTrades(LiveLike):
    def __init__(self, *a, rows=100, **kw):
        super().__init__(*a, **kw)
        self.rows, self.calls = rows, 0

    def user_trades(self, symbol, order_id=None, start_ms=None, end_ms=None):
        self.calls += 1
        return [{"id": f"t{i}", "orderId": order_id, "commission": "0.01", "maker": True, "price": "1", "qty": "1",
                 "time": 1} for i in range(self.rows)]


def test_saturated_trades_marked_incomplete_once_and_not_repolled(tmp_path):
    g, ex = make(tmp_path, ex_cls=ManyTrades)
    fee, _ = g._fee_delta("LONG", "o1")
    assert abs(fee - 1.0) < 1e-9                                  # 100 × 0.01 — нижняя оценка, не ноль
    g._fee_delta("LONG", "o1")
    assert list(g.st["fee_incomplete"]) == ["o1"]
    jr = [json.loads(x) for x in (tmp_path / "j.jsonl").read_text().splitlines()]
    assert sum(1 for r in jr if "комиссия неполная" in r.get("kind", "")) == 1
    n = ex.calls
    g.st["fee_checked"] = 0.0
    g._settle_fees()
    assert ex.calls == n                                          # поздняя дозапись его не перечитывает
    assert "комиссия неполная" in g.card(100000.0) and "итог завышен" in g.card(100000.0)   # 25.10 GPT: не «нижняя оценка итога»


def test_99_trades_complete(tmp_path):
    g, ex = make(tmp_path, ex_cls=lambda *a, **k: ManyTrades(*a, rows=99, **k))
    g._fee_delta("LONG", "o1")
    assert not g.st["fee_incomplete"]


# ---------------------------------------------------------------- (3) общая сверка позиции
def grid(symbol="BTCUSDT", lots=(), release=(), step=0.0001):
    return {"symbol": symbol, "release_sides": list(release), "qty_step": step,
            "state": {"LONG": {"lots": [{"qty": q} for q in lots]}, "SHORT": {"lots": []}}}


def test_position_gaps_sums_all_grids_of_symbol():
    grids = [grid(lots=["0.0012"] * 4, release=["SHORT"]), grid(lots=["0.0012"] * 3),
             grid(symbol="ETHUSDT", lots=["0.02"], step=0.001)]
    pos = [{"symbol": "BTCUSDT", "side": "LONG", "size": "0.0084"}, {"symbol": "ETHUSDT", "side": "LONG", "size": "0.02"}]
    gaps = loop.position_gaps(grids, set(), pos)
    assert gaps["BTCUSDT:LONG"] == {"lots": 0.0084, "exchange": 0.0084, "deficit": False}
    assert "BTCUSDT:SHORT" not in gaps                            # сторона оператора не сверяется
    assert gaps["ETHUSDT:LONG"]["deficit"] is False
    # каждой сетке по отдельности хватило бы 0.0060, но всем вместе — нет
    gaps = loop.position_gaps(grids, set(), [{"symbol": "BTCUSDT", "side": "LONG", "size": "0.0060"}])
    assert gaps["BTCUSDT:LONG"]["deficit"] is True
    # больше лотов на бирже (ручная позиция) — не нехватка
    gaps = loop.position_gaps(grids, set(), [{"symbol": "BTCUSDT", "side": "LONG", "size": "0.05"}])
    assert gaps["BTCUSDT:LONG"]["deficit"] is False
    # эпизод тренда на стороне — без сверки
    assert "ETHUSDT:LONG" not in loop.position_gaps(grids, {("ETHUSDT", "LONG")}, pos)


def test_audit_blocks_after_n_passes_and_restores(tmp_path, monkeypatch):
    sent = []
    r = loop.Runner(send_fn=lambda t: sent.append(t) or True)
    bad = {"BTCUSDT:LONG": {"lots": 0.0084, "exchange": 0.006, "deficit": True}}
    ok = {"BTCUSDT:LONG": {"lots": 0.0084, "exchange": 0.0084, "deficit": False}}
    for _ in range(loop.AUDIT_PASSES - 1):
        r._audit_apply(bad)
    assert not r._audit_blocks("BTCUSDT") and not sent              # мимолётное расхождение не блокирует
    r._audit_apply(ok)                                              # совпадение сбрасывает счётчик
    for _ in range(loop.AUDIT_PASSES):
        r._audit_apply(bad)
    assert "LONG" in r._audit_blocks("BTCUSDT") and len(sent) == 1
    r2 = loop.Runner()                                              # перезапуск: блок из файла
    assert "LONG" in r2._audit_blocks("BTCUSDT")
    for _ in range(loop.AUDIT_PASSES):
        r._audit_apply(ok)
    assert not r._audit_blocks("BTCUSDT") and len(sent) == 2 and "восстановлена" in sent[-1]


def test_audit_block_stops_new_entries_but_keeps_tps(tmp_path):
    g, ex = make(tmp_path, sides=["LONG"], order_qty="0.0012", portfolio_free_usd=1000.0, max_notional_usd=100000.0,
                 audit_block={"LONG": "на бирже 0.006, лотов сеток 0.0084"})
    g.tick()
    assert not [o for o in ex.orders.values() if not o["reduceOnly"] and o["status"] in LIVE_STATUSES]
    assert g.st["LONG"]["blocked"].startswith("сверка позиции")
    ok, why = g.may_add("LONG", 99800.0, 100000.0)
    assert not ok and "сверка позиции" in why


def test_audit_skipped_when_positions_unreadable(tmp_path, monkeypatch):
    r = loop.Runner()

    class Bad:
        def futures_positions(self):
            raise TimeoutError
    monkeypatch.setattr(r, "_client", lambda: Bad())
    monkeypatch.setattr(r, "_trend_busy", lambda: set())
    monkeypatch.setattr(loop.eg, "GRIDS", [])
    r._position_audit()                                             # не падает и ничего не меняет
    assert r.audit == {}
