"""Безопасность закрытия по режиму и передачи стороны — сценарии разбора GPT 12.10
(docs/WEEX_GPT_LIVE_REGIME_REVIEW_2026-10-11.md, тесты из WEEX_GPT_LIVE_REGIME_REPRO_2026-10-11.zip перенесены как
есть + L3/L4/L5/L6/R5). Биржа — имитатор, это проверка логики, не замер реального WEEX."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from services.weex_grid import engine as eg


class Px:
    def __init__(self, mid=100000.):
        self.mid = mid

    def __call__(self):
        return self.mid - .05, self.mid + .05


class PartialLiveExchange(eg.DryExchange):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.first_market_partial = True

    def place_market(self, symbol, side, position_side, qty, cid, reduce_only=False):
        r = super().place_market(symbol, side, position_side, qty, cid, reduce_only)
        if r.get("success") and reduce_only and self.first_market_partial:
            self.first_market_partial = False
            oid = r["orderId"]
            half = float(self.orders[oid]["origQty"]) / 2
            self.orders[oid].update(status="PARTIALLY_FILLED", executedQty=f"{half:.4f}")
            self.trades[oid][0].update(qty=f"{half:.4f}", commission=str(half * float(self.orders[oid]["price"]) * .00048))
        return r

    def open_orders(self, symbol):
        return [{"orderId": k, **v} for k, v in self.orders.items() if v["status"] in eg.LIVE]

    def cancel(self, oid):
        o = self.orders.get(str(oid))
        if o and o["status"] in ("NEW", "PARTIALLY_FILLED"):
            o["status"] = "CANCELED"
        return {"success": True, "orderId": oid}


def fixture(p: Path, cls=eg.DryExchange, **extra):
    px = Px()
    clock = {"t": 1800000000.}
    regime = {"up": True}
    ex = cls(px, now_fn=lambda: clock["t"])
    cfg = {**eg.DEFAULT, "enabled": True, "dry_run": True, "sides": ["LONG"], "order_qty": ".0012",
           "regime_sma": 100, "stress_budget_frac": 0., "daily_loss_stop_usd": 0., "max_notional_usd": 4000., **extra}

    def build():
        return eg.Grid(ex, cfg, state_path=p / "st.json", journal_path=p / "journal.jsonl",
                       now_fn=lambda: clock["t"], regime_fn=lambda *a: regime["up"])
    g = build()

    def tick(g):
        clock["t"] += 10
        g.tick()
    tick(g)
    px.mid = 99790.
    tick(g)
    assert sum(float(l["qty"]) for l in g.st["LONG"]["lots"]) == pytest.approx(.0012)
    return g, ex, px, clock, regime, build, tick, cfg


def bot_markets(ex):
    return [dict(orderId=oid, **o) for oid, o in ex.orders.items()
            if o.get("type") == "MARKET" and str(o.get("clientOrderId", "")).startswith(eg.PREFIX)]


def actual(ex, side="LONG"):
    return next(float(p["size"]) for p in ex.futures_positions() if p["side"] == side)


def book(g, side="LONG"):
    return sum(float(l["qty"]) for l in g.st[side]["lots"])


# ---------- GPT L1: частичный market не учитывается дважды через «сироту»
def test_partial_live_flatten_is_not_double_counted_as_orphan(tmp_path):
    g, ex, px, clock, regime, build, tick, cfg = fixture(tmp_path, PartialLiveExchange)
    regime["up"] = False
    for _ in range(3):
        tick(g)
    assert actual(ex) == pytest.approx(book(g))


# ---------- GPT L2: потерянный ответ + пустая история + TTL → второго market нет, ручной LONG цел
def test_unknown_filled_market_is_not_retried_against_manual_position(tmp_path):
    g, ex, px, clock, regime, build, tick, cfg = fixture(tmp_path)
    ex.place_market("BTCUSDT", "BUY", "LONG", ".0020", "manual_open", reduce_only=False)
    real = ex.place_market

    def lost(*a, **kw):
        real(*a, **kw)
        raise TimeoutError("accepted and filled, response lost")
    ex.place_market = lost
    regime["up"] = False
    tick(g)
    ex.order_history = lambda *a, **kw: []
    ex.place_market = real
    g = build()
    clock["t"] += eg.PENDING_TTL + 1
    tick(g)
    tick(g)
    tick(g)
    assert len(bot_markets(ex)) == 1
    assert actual(ex) == pytest.approx(.002)


def test_unknown_filled_market_is_not_rewritten_as_estimated_manual_close(tmp_path):
    g, ex, px, clock, regime, build, tick, cfg = fixture(tmp_path)
    real = ex.place_market
    first = {}

    def lost(*a, **kw):
        r = real(*a, **kw)
        first.update(ex.orders[r["orderId"]])
        raise TimeoutError("accepted and filled, response lost")
    ex.place_market = lost
    regime["up"] = False
    tick(g)
    ex.order_history = lambda *a, **kw: []
    ex.place_market = real
    g = build()
    clock["t"] += eg.PENDING_TTL + 1
    tick(g)
    px.mid = 99000.
    tick(g)
    q, entry, exit_px = .0012, 99800., float(first["avgPrice"])
    assert g.st["LONG"]["realized"] == pytest.approx(q * (exit_px - entry))
    assert g.st["LONG"]["fees"] == pytest.approx(q * entry * .00016 + q * exit_px * .00048)


# ---------- GPT L7: курсор комиссии живого закрытия не удаляется
def test_active_flatten_keeps_fee_cursor(tmp_path):
    g, ex, px, clock, regime, build, tick, cfg = fixture(tmp_path, PartialLiveExchange)
    regime["up"] = False
    b, a = px()
    g._flatten_side("LONG", b, a, px.mid)
    oid = g.st["LONG"]["flatten"]["id"]
    g._flatten_side("LONG", b, a, px.mid)
    clock["t"] += eg.FEE_WINDOW + 10
    g._settle_fees()
    assert oid in g.st["LONG"]["fee_book"]
    o = ex.orders[oid]
    o.update(status="FILLED", executedQty=o["origQty"])
    market_fee = float(o["origQty"]) * float(o["price"]) * .00048
    ex.trades[oid][0].update(qty=o["origQty"], commission=str(market_fee))
    g._flatten_side("LONG", b, a, px.mid)
    assert g.st["LONG"]["fees"] == pytest.approx(.0012 * 99800. * .00016 + market_fee)


def test_normal_full_flatten_survives_restart(tmp_path):
    g, ex, px, clock, regime, build, tick, cfg = fixture(tmp_path)
    regime["up"] = False
    tick(g)
    g = build()
    tick(g)
    tick(g)
    assert actual(ex) == 0. and not g.st["LONG"]["lots"]
    assert len(bot_markets(ex)) == 1


def test_known_partial_cumulative_fill_is_idempotent_without_orphan_handler(tmp_path):
    g, ex, px, clock, regime, build, tick, cfg = fixture(tmp_path, PartialLiveExchange)
    regime["up"] = False
    b, a = px()
    g._flatten_side("LONG", b, a, px.mid)
    oid = g.st["LONG"]["flatten"]["id"]
    g._flatten_side("LONG", b, a, px.mid)
    first = (book(g), g.st["LONG"]["realized"], g.st["LONG"]["fees"])
    g._flatten_side("LONG", b, a, px.mid)
    assert (book(g), g.st["LONG"]["realized"], g.st["LONG"]["fees"]) == first
    o = ex.orders[oid]
    o.update(status="FILLED", executedQty=o["origQty"])
    full_fee = float(o["origQty"]) * float(o["price"]) * .00048
    ex.trades[oid][0].update(qty=o["origQty"], commission=str(full_fee))
    g._flatten_side("LONG", b, a, px.mid)
    assert actual(ex) == 0. and not g.st["LONG"]["lots"]
    assert g.st["LONG"]["fees"] == pytest.approx(.0012 * 99800 * .00016 + full_fee)
    assert len(bot_markets(ex)) == 1


# ---------- GPT L8: сбой при записи журнала не удваивает учёт
def test_crash_before_accounting_save_replays_known_exit_once(tmp_path):
    g, ex, px, clock, regime, build, tick, cfg = fixture(tmp_path)
    regime["up"] = False
    tick(g)
    original_journal = g._journal

    def crash(rec):
        if rec.get("kind") == "закрытие по режиму":
            raise RuntimeError("simulated crash")
        return original_journal(rec)
    g._journal = crash
    with pytest.raises(RuntimeError, match="simulated crash"):
        tick(g)
    g = build()
    tick(g)
    assert actual(ex) == 0. and not g.st["LONG"]["lots"]
    assert len(bot_markets(ex)) == 1
    assert g.st["LONG"]["realized"] == pytest.approx(.0012 * (99789.95 - 99800))
    assert g.st["LONG"]["fees"] == pytest.approx(.0012 * (99800 * .00016 + 99789.95 * .00048))


# ---------- L3: передача стороны сначала доводит уже отправленное закрытие
def test_release_after_sent_flatten_hands_only_real_remainder(tmp_path):
    g, ex, px, clock, regime, build, tick, cfg = fixture(tmp_path)
    regime["up"] = False
    tick(g)                                            # market отправлен и исполнен, учёт — на следующем проходе
    assert g.st["LONG"]["flatten"]
    cfg["sides"], cfg["release_sides"] = [], ["LONG"]
    tick(g)
    assert g.st["LONG"].get("flatten") is None and not g.st["LONG"]["lots"]
    j = (tmp_path / "journal.jsonl").read_text()
    assert "закрытие по режиму" in j and "передано оператору" not in j    # передавать нечего — всё закрыто


def test_release_waits_for_live_market(tmp_path):
    g, ex, px, clock, regime, build, tick, cfg = fixture(tmp_path)
    real = ex.place_market

    def slow(*a, **kw):
        r = real(*a, **kw)
        o = ex.orders[r["orderId"]]
        slow.px = o["avgPrice"]
        o.update(status="NEW", executedQty="0", price="999999")         # принят, ещё не исполнен
        return r
    ex.place_market = slow
    regime["up"] = False
    tick(g)
    cfg["sides"], cfg["release_sides"] = [], ["LONG"]
    tick(g)
    assert g.st["LONG"]["flatten"] and g.st["LONG"]["lots"]            # передача ждёт исход market
    oid = g.st["LONG"]["flatten"]["id"]
    ex.orders[oid].update(status="FILLED", executedQty=ex.orders[oid]["origQty"], avgPrice=slow.px)
    tick(g)
    assert not g.st["LONG"]["lots"] and "передано оператору" not in (tmp_path / "journal.jsonl").read_text()


# ---------- L4: пустой ответ детали ордера не считается конечным — старый тейк не забывается
def test_release_with_unknown_tp_detail_keeps_ownership(tmp_path):
    g, ex, px, clock, regime, build, tick, cfg = fixture(tmp_path)
    tp_id = g.st["LONG"]["lots"][0]["tp_order"]["id"]
    real_info, real_cancel = ex.order_info, ex.cancel
    ex.cancel = lambda oid: {"success": False} if str(oid) == tp_id else real_cancel(oid)   # только тейк
    ex.order_info = lambda oid: {} if str(oid) == tp_id else real_info(oid)
    cfg["sides"], cfg["release_sides"] = [], ["LONG"]
    tick(g)
    assert g.st["LONG"]["lots"] and g.st["LONG"]["lots"][0].get("tp_order")
    assert "передано оператору" not in (tmp_path / "journal.jsonl").read_text()
    ex.order_info, ex.cancel = real_info, real_cancel
    tick(g)
    assert ex.orders[tp_id]["status"] == "CANCELED" and not g.st["LONG"]["lots"]
    assert "передано оператору" in (tmp_path / "journal.jsonl").read_text()


# ---------- L5: принятый, но отклонённый market считается отказом — повторы ограничены
def test_terminal_reject_after_ack_is_bounded(tmp_path):
    g, ex, px, clock, regime, build, tick, cfg = fixture(tmp_path)
    real = ex.place_market

    def rejected(*a, **kw):
        r = real(*a, **kw)
        ex.orders[r["orderId"]].update(status="REJECTED", executedQty="0")
        ex.trades.pop(r["orderId"], None)
        return r
    ex.place_market = rejected
    regime["up"] = False
    for _ in range(12):
        tick(g)
    assert len(bot_markets(ex)) <= 3 and g.st["halted"]
    assert g.st["LONG"]["lots"]                                        # остаток не забыт


# ---------- L6: источник режима
DAY = 86_400_000


def rows(today, n=105, closes=None):
    out = []
    for i in range(n):
        day = today - n + i                            # последняя — вчера
        c = closes[i] if closes else 100.0 + i
        out.append([day * DAY, 0, 0, 0, str(c), 0, day * DAY + DAY - 1])
    return out


def test_regime_day_bound_and_validated():
    eg._REGIME_CACHE.clear()
    now = 20_000 * 86400 + 300                         # 00:05 UTC дня 20000
    today = 20_000
    assert eg.regime_up("X", 100, now=now, fetch=lambda s, n: rows(today)) is True
    calls = []

    def fetch_next(s, n):
        calls.append(1)
        return rows(today + 1, closes=[200.0] * 104 + [1.0])
    assert eg.regime_up("X", 100, now=now + 86400, fetch=fetch_next) is False and calls   # новые сутки — новый запрос
    eg._REGIME_CACHE.clear()
    assert eg.regime_up("X", 100, now=now, fetch=lambda s, n: rows(today - 2)) is None     # данные устарели
    eg._REGIME_CACHE.clear()
    assert eg.regime_up("X", 100, now=now, fetch=lambda s, n: rows(today)[::-1]) is True   # порядок не важен
    eg._REGIME_CACHE.clear()
    bad = rows(today)
    bad[-1][4] = "NaN"
    assert eg.regime_up("X", 100, now=now, fetch=lambda s, n: bad) is None                 # не «шорт»
    eg._REGIME_CACHE.clear()
    gap = rows(today)
    del gap[50]
    assert eg.regime_up("X", 100, now=now, fetch=lambda s, n: gap[-100:]) is None          # пропуск дня
    eg._REGIME_CACHE.clear()

    def boom(s, n):
        raise TimeoutError
    assert eg.regime_up("X", 100, now=now, fetch=boom) is None
    assert not math.isnan(0.0)


# ---------- R5: усыновлённая сирота не даёт кредит новому входу сверх общего потолка
def test_adopted_orphan_entry_consumes_room(tmp_path):
    from tests.services.weex_grid.test_weex_grid_engine import make
    g, ex = make(tmp_path, Px(), sides=["LONG"], order_qty="0.0002", portfolio_free_usd=15.0)
    ex.orders["orph"] = {"clientOrderId": "b7gBLe1799999999", "side": "BUY", "positionSide": "LONG", "price": "99800",
                         "origQty": "0.0001", "status": "NEW", "executedQty": "0", "avgPrice": "0", "reduceOnly": False}
    g.tick()
    new = [o for o in ex.orders.values() if o["status"] == "NEW" and not o["reduceOnly"] and o["origQty"] == "0.0002"]
    assert not new                                     # $19.96 при свободных $15 — нельзя
