"""Разбор GPT 18.10 (docs/WEEX_GPT_SECTION2_REVIEW_2026-10-18.md; harness research/weex_review_20261018 прочитан, не
запускался): контрпримеры, которые должны падать на f450490.
P1 — ответ null/{} на постановку снимал намерение и резерв как «явный отказ» → при принятом, но не видимом ордере
     вставал второй вход.
P1 — сделка без orderId в поиске по сделкам пропускалась, а поиск считался ПОЛНЫМ → ложное «не дошёл».
P1 — параллельный проход: найденная сирота не уменьшала долю соседей, ask×1.01 не ограничивал итог → откат к очереди
     (свободное заново перед каждой сеткой; проверенная схема 11.10).
P2 — комиссия ордера бралась из любых строк ответа сделок, в т.ч. чужого ордера.
P2 — cid_tag L/S совпадает со старым форматом BTC b7gL…/b7gS….
P2 — граница окна истории: при не включённом endTime ордер ровно в m терялся при делении [a,m] ∪ [m+1,b]."""
from __future__ import annotations

import pytest

from services.weex_grid import engine as eg
from services.weex_grid import loop as lp
from tests.services.weex_grid.test_weex_gpt1013 import live_entries
from tests.services.weex_grid.test_weex_gpt1014 import live_grid
from tests.services.weex_grid.test_weex_gpt1015 import hide_from_open


class BadReplyExchange(eg.DryExchange):
    """Биржа ордер ПРИНЯЛА, но ответ на POST — reply (None или {})."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.reply = "ok"

    def place_limit(self, *a, **kw):
        r = super().place_limit(*a, **kw)
        mode, self.reply = self.reply, "ok"
        return r if mode == "ok" else mode


@pytest.mark.parametrize("bad", [None, {}], ids=["null", "empty_object"])
def test_p1_null_place_reply_keeps_pending_and_single_entry(tmp_path, bad):
    t = live_grid(tmp_path, BadReplyExchange, filled=False)
    assert len(live_entries(t.ex)) == 1
    t.ex.reply = bad
    t.px.mid = 100300.                                   # вход отстал — снять и поставить новый; ответ на новый — bad
    t.g = t.tick()
    s = t.g.st["LONG"]
    assert s["pending"] is not None, "неизвестный ответ — намерение остаётся"
    accepted = live_entries(t.ex)
    assert len(accepted) == 1
    hide_from_open(t, accepted[0])                       # принятый ордер не виден в списке открытых
    for _ in range(6):                                   # минута проходов в пределах TTL
        t.g = t.tick()
    assert len(live_entries(t.ex)) == 1, "второй вход поставлен при неизвестном исходе первого"


def test_p1_trade_without_order_id_makes_search_incomplete(tmp_path):
    t = live_grid(tmp_path, filled=False)
    g = t.g
    g.c.user_trades = lambda *a, **kw: [{"id": "t1", "side": "BUY", "positionSide": "LONG", "price": "100",
                                         "qty": "0.001", "time": int(t.clock["t"] * 1000)}]
    o, complete = g._find_by_trades("b7gBLe1", t.clock["t"], side="LONG", want="BUY", book={})
    assert o is None and complete is False


def test_p2_fee_only_from_own_order_rows(tmp_path):
    t = live_grid(tmp_path, filled=False)
    g = t.g
    g.c.user_trades = lambda sym, oid=None, **kw: [
        {"orderId": oid, "symbol": "BTCUSDT", "commission": "0.01", "maker": True},
        {"orderId": "999999", "symbol": "BTCUSDT", "commission": "7", "maker": True},   # чужой ордер в ответе
        {"symbol": "BTCUSDT", "commission": "3", "maker": True},                        # без номера ордера
    ]
    delta, maker = g._fee_delta("LONG", "555")
    assert delta == pytest.approx(0.01) and maker is True


def test_p2_fee_non_list_reply_is_issue_not_zero_done(tmp_path):
    t = live_grid(tmp_path, filled=False)
    g = t.g
    g.c.user_trades = lambda *a, **kw: {"code": -1}
    delta, _ = g._fee_delta("LONG", "556")
    assert delta == 0.0
    assert any("комиссия" in w for _, w in g._other_issues)


@pytest.mark.parametrize("tag", ["L", "S", "l", "s"])
def test_p2_legacy_letters_forbidden_as_cid_tag(tag):
    with pytest.raises(eg.ConfigError):
        eg.cid_tag({"symbol": "BTCUSDT", "cid_tag": tag})


def test_p2_history_window_end_exclusive_boundary(tmp_path):
    """endTime не включён: [a,m] ∪ [m+1,b] теряет ордер ровно в m; перекрытие [a,m] ∪ [m,b] — находит."""
    t = live_grid(tmp_path, filled=False)
    g = t.g
    a, b = 1_000_000, 1_000_000 + 600_000
    m = (a + b) // 2
    rows = [{"orderId": str(i), "clientOrderId": f"x{i}", "time": a + i * 4000} for i in range(150)]
    rows.append({"orderId": "own", "clientOrderId": "b7gBLe9", "time": m})

    def history(symbol, limit=100, page=0, start_ms=None, end_ms=None):
        got = [r for r in rows if start_ms <= r["time"] < end_ms]          # end exclusive
        return sorted(got, key=lambda r: -r["time"])[:limit]

    g.c.order_history = history
    o, _complete = g._history_window("b7gBLe9", a, b, m, [8], split=True)
    assert o is not None and o["orderId"] == "own"


def test_p1_runner_sequential_fresh_free_before_each_grid(monkeypatch):
    """Откат параллельного прохода: свободное считается заново перед каждой сеткой, сетки идут по очереди."""
    from types import SimpleNamespace
    monkeypatch.setattr(eg, "GRIDS", ("A", "B", "C"))
    r = lp.Runner()
    frees = iter([300.0, 200.0, 100.0])
    monkeypatch.setattr(r, "_portfolio_free", lambda: next(frees))
    r.trend = SimpleNamespace(tick=lambda portfolio_free=None: None)
    seen = []
    monkeypatch.setattr(r, "tick_one", lambda name, free=None, **kw: seen.append((name, free)))   # 25.10: + acct/debts
    r.tick()
    assert seen == [("A", 300.0), ("B", 200.0), ("C", 100.0)]
    assert not hasattr(lp, "ThreadPoolExecutor") or not hasattr(r, "_room_shares")
