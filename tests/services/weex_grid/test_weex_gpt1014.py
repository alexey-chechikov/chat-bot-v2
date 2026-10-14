"""Разбор ревью 14.10 к 6cdb7a1 (пробы review_probes: lens1 stuck_unknown, lens1b entry_unknown, lens2b second_handover,
lens3 card_before_tick / probe_w_test):
F1/L2-1 — ордер, чья деталь неясна дольше 5 мин, поднимается сообщением (раз в час; закрытие по режиму / передача
стороны, которые он держит, — названы прямо); проглоченные сбои дольше 10 мин без чистого прохода — сообщение раз в
30 мин. L2-3 — повторная передача уже переданной стороны без лотов не пишет второе «передано оператору». L3-1 —
карточка /weex читает журнал своей сетки (миграция передач видна до первого прохода); нет журнала при истории
стороны — миграция не отмечается выполненной. L3-2 — конечный статус без executedQty и неясная сирота. Форма
реального ответа WEEX GET /capi/v3/order (14.10: orderId — число, executedQty — строка и у CANCELED).
Биржа — имитатор, это проверка логики, не замер реального WEEX."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.weex_api import client as wc
from services.weex_grid import engine as eg
from services.weex_grid import loop as lp
from tests.services.weex_grid.test_weex_gpt1013 import (HAND, _release_fixture, disk, handovers, hide, live_entries,
                                                        live_tps, ts_eq)
from tests.services.weex_grid.test_weex_regime_gpt import Px, bot_markets, fixture

BLOCK_CLOSE = "ЗАКРЫТИЕ ПО РЕЖИМУ ЗАБЛОКИРОВАНО"
BLOCK_HAND = "ПЕРЕДАЧА СТОРОНЫ ЖДЁТ"


# ---------- общий стенд: как loop.py — новый Grid с диска на каждый проход, сообщения собираются
def live_grid(p: Path, cls=eg.DryExchange, filled: bool = True, **extra) -> SimpleNamespace:
    px, clock, regime, sends = Px(), {"t": 1800000000.}, {"up": True}, []
    ex = cls(px, now_fn=lambda: clock["t"])
    cfg = {**eg.DEFAULT, "enabled": True, "dry_run": False, "sides": ["LONG"], "order_qty": "0.0012",
           "regime_sma": 100, "stress_budget_frac": 0., "daily_loss_stop_usd": 0., "max_notional_usd": 4000., **extra}

    def build():
        return eg.Grid(ex, cfg, state_path=p / "st.json", journal_path=p / "journal.jsonl", now_fn=lambda: clock["t"],
                       regime_fn=lambda *a: regime["up"], send_fn=sends.append)

    def tick():
        clock["t"] += 10
        g = build()
        g.tick()
        return g
    g = tick()
    if filled:
        px.mid = 99790.
        g = tick()
        assert sum(float(l["qty"]) for l in g.st["LONG"]["lots"]) == pytest.approx(.0012)
    return SimpleNamespace(g=g, ex=ex, px=px, clock=clock, regime=regime, sends=sends, cfg=cfg, build=build, tick=tick)


def stuck(ex, oid: str, mode: str) -> None:
    """Деталь ордера не читается: {} или HTTP 400 (как lens1_probe_stuck_unknown / lens1b_probe_entry_unknown)."""
    real = ex.order_info

    def info(x):
        if str(x) == oid:
            if mode == "http400":
                raise wc.WeexError('HTTP 400: {"code":"ORDER_NOT_FOUND","msg":"orderId not exist"}')
            return {}
        return real(x)
    ex.order_info = info


def run(t: SimpleNamespace, seconds: int, each=None) -> dict[int, int]:
    """Проходы по 10 с; {секунда от начала: число сообщений после прохода}."""
    t0, out = t.clock["t"], {}
    for _ in range(seconds // 10):
        t.g = t.tick()
        if each:
            each(t)
        out[int(t.clock["t"] - t0)] = len(t.sends)
    return out


# ---------- F1/L2-1: тейк с неясной деталью — 0 сообщений до 5 мин, 1 к 6 мин, повтор не чаще раза в час
@pytest.mark.parametrize("mode", ["empty", "http400"])
def test_stuck_tp_detail_escalates_once_per_hour(tmp_path, mode):
    t = live_grid(tmp_path)
    tp_id = t.g.st["LONG"]["lots"][0]["tp_order"]["id"]
    t.ex.orders[tp_id]["status"] = "CANCELED"          # снят вне бота (оператор / биржа), деталь не читается
    stuck(t.ex, tp_id, mode)
    t.sends.clear()
    tps = []
    n = run(t, 66 * 60, lambda t: tps.append(len(live_tps(t.ex))))
    assert n[240] == 0                                  # 4 мин — тихо
    assert n[360] == 1                                  # к 6 мин — ровно одно
    assert n[3600] == 1                                 # в течение часа повтора нет
    assert n[66 * 60] == 2                              # повтор — через час
    assert max(tps) <= 1                                # замены поверх неясного тейка нет
    m = t.sends[0]
    assert "BTCUSDT" in m and "LONG" in m and tp_id in m and "тейк" in m and "side:LONG" in m and "5 мин" in m
    assert "замену не ставлю" in m.lower()
    assert ("ORDER_NOT_FOUND" if mode == "http400" else "пустой ответ") in m
    assert BLOCK_CLOSE not in m and BLOCK_HAND not in m
    rec = disk(tmp_path)["unknown_orders"][tp_id]
    assert rec["side"] == "LONG" and rec["phase"] == "side:LONG" and rec["since"] == pytest.approx(t.clock["t"] - 3950)
    assert t.g.st["LONG"]["lots"][0]["tp_order"]["id"] == tp_id
    # биржа снова отвечает: конечный статус подтверждён → запись снята, тейк один
    t.ex.order_info = eg.DryExchange.order_info.__get__(t.ex)
    run(t, 30)
    assert not disk(tmp_path).get("unknown_orders")
    assert len(live_tps(t.ex)) == 1 and len(t.sends) == 2


# ---------- F1: кратковременная неясность (ордер снова в списке открытых) и чужая запись — без ложной тревоги
def test_brief_unknown_back_in_open_list_clears_without_message(tmp_path):
    t = live_grid(tmp_path)
    tp_id = t.g.st["LONG"]["lots"][0]["tp_order"]["id"]
    restore = hide(t.ex, tp_id, {})
    run(t, 20)
    assert tp_id in disk(tmp_path)["unknown_orders"]
    restore()                                          # тейк снова в списке открытых — он живой
    st = disk(tmp_path)
    st["unknown_orders"]["gone1"] = {"since": t.clock["t"] - 7200, "side": "LONG", "why": "x", "phase": "side:LONG"}
    (tmp_path / "st.json").write_text(json.dumps(st), encoding="utf-8")   # учёт этот ордер больше не ведёт
    t.sends.clear()
    run(t, 10 * 60)
    assert t.sends == [] and not disk(tmp_path)["unknown_orders"]
    assert live_tps(t.ex) == [tp_id]


# ---------- F1: вход исполнился на бирже, деталь неясна — то же сообщение, второго входа нет
@pytest.mark.parametrize("mode", ["empty", "http400"])
def test_stuck_entry_detail_escalates(tmp_path, mode):
    t = live_grid(tmp_path, filled=False)
    e_id = t.g.st["LONG"]["entry"]["id"]
    stuck(t.ex, e_id, mode)
    t.px.mid = 99700.                                  # вход ≈99 800 исполняется на бирже
    t.sends.clear()
    ents = []
    n = run(t, 60 * 60, lambda t: ents.append(len(live_entries(t.ex))))
    assert n[240] == 0 and n[360] == 1 and n[3600] == 1
    assert max(ents) <= 1 and t.g.st["LONG"]["entry"]["id"] == e_id
    m = t.sends[0]
    assert e_id in m and "вход" in m and "LONG" in m and "замену не ставлю" in m.lower()


# ---------- F1: режим выключил сторону, неясный тейк держит закрытие — сказано прямо, рыночного нет
def test_stuck_tp_blocks_regime_close_and_says_so(tmp_path):
    t = live_grid(tmp_path)
    tp_id = t.g.st["LONG"]["lots"][0]["tp_order"]["id"]
    t.ex.orders[tp_id]["status"] = "CANCELED"
    stuck(t.ex, tp_id, "empty")
    t.regime["up"] = False
    t.sends.clear()
    n = run(t, 6 * 60)
    assert n[240] == 0 and n[360] == 1
    assert BLOCK_CLOSE in t.sends[0] and tp_id in t.sends[0] and "flatten:LONG" in t.sends[0]
    assert not bot_markets(t.ex) and t.g.st["LONG"]["lots"]


def test_stuck_tp_escalates_again_when_it_starts_blocking_regime_close(tmp_path):
    """Сообщение о неясном тейке уже было; режим выключил сторону — новое сообщение сразу (теперь держит закрытие),
    дальше снова не чаще раза в час."""
    t = live_grid(tmp_path)
    tp_id = t.g.st["LONG"]["lots"][0]["tp_order"]["id"]
    t.ex.orders[tp_id]["status"] = "CANCELED"
    stuck(t.ex, tp_id, "empty")
    t.sends.clear()
    run(t, 30 * 60)
    assert len(t.sends) == 1 and BLOCK_CLOSE not in t.sends[0]
    t.regime["up"] = False
    n = run(t, 40 * 60)
    assert n[10] == 2 and BLOCK_CLOSE in t.sends[1]
    assert n[40 * 60] == 2 and not bot_markets(t.ex)


# ---------- F1: передача стороны ждёт неясную сироту — сказано прямо
def test_stuck_stray_on_release_says_handover_waits(tmp_path):
    px, clock, sends = Px(100000.), {"t": 1800000000.}, []
    ex = eg.DryExchange(px, now_fn=lambda: clock["t"])
    cfg = {**eg.DEFAULT, "enabled": True, "dry_run": False, "sides": ["LONG"], "release_sides": ["SHORT"],
           "order_qty": "0.0012", "daily_loss_stop_usd": 0., "stress_budget_frac": 0.}

    def build():
        return eg.Grid(ex, cfg, state_path=tmp_path / "st.json", journal_path=tmp_path / "journal.jsonl",
                       now_fn=lambda: clock["t"], send_fn=sends.append)
    g = build()
    ex.orders["stray"] = {"clientOrderId": "b7gBSt_old", "side": "BUY", "positionSide": "SHORT", "price": "99000",
                          "origQty": "0.0001", "status": "NEW", "executedQty": "0", "avgPrice": "0", "reduceOnly": True}
    g.st["SHORT"]["lots"] = [{"entry": 100000.0, "qty": "0.0001", "tp": 99000.0, "tp_order": None, "t": clock["t"]}]
    g.st["SHORT"]["strays"] = [{"id": "stray", "cid": "b7gBSt_old", "price": 99000.0, "qty": "0.0001", "kind": "t"}]
    g.save()
    real_info, real_cancel = ex.order_info, ex.cancel
    ex.order_info = lambda oid: {} if str(oid) == "stray" else real_info(oid)
    ex.cancel = lambda oid: {"success": False} if str(oid) == "stray" else real_cancel(oid)
    for i in range(36):
        clock["t"] += 10
        build().tick()
        if i == 23:
            assert sends == []
    assert len(sends) == 1
    assert BLOCK_HAND in sends[0] and "stray" in sends[0] and "SHORT" in sends[0] and "release:SHORT" in sends[0]
    assert not handovers(tmp_path)


# ---------- проглоченные сбои дольше 10 мин без чистого прохода — сообщение раз в 30 мин
def test_persistent_swallowed_failure_alerts_after_10_min_then_every_30(tmp_path):
    t = live_grid(tmp_path, stress_budget_frac=.25)

    def boom():
        raise TimeoutError("synthetic balance failure")
    t.ex.futures_balance = boom
    t.sends.clear()
    n = run(t, 41 * 60)
    assert n[9 * 60] == 0 and n[11 * 60] == 1 and n[40 * 60] == 1 and n[41 * 60] == 2
    m = t.sends[0]
    assert "BTCUSDT" in m and "10 мин без чистого прохода" in m and "баланс не прочитан" in m
    t.ex.futures_balance = eg.DryExchange.futures_balance.__get__(t.ex)
    run(t, 20)
    st = disk(tmp_path)
    assert "issues_since" not in st and st["last_tick_ok_ts"] == ts_eq(t.clock["t"])


# ---------- L2-3: сирота на уже переданной стороне снимается, второго «передано оператору» нет
def test_orphan_on_already_released_side_writes_no_second_handover(tmp_path):
    g, ex, px, clock, build, tick, cfg = _release_fixture(tmp_path)
    cfg["sides"], cfg["release_sides"] = ["LONG", "SHORT"], []
    tick(g)
    assert live_entries(ex, "SHORT")
    cfg["sides"], cfg["release_sides"] = ["LONG"], ["SHORT"]
    tick(g)
    assert len(handovers(tmp_path)) == 1
    # свой SHORT-вход всплыл позже (потерянный ответ / откат учёта) — как в lens2b/probe_second_handover.py
    oid = "999000111"
    ex.orders[oid] = {"clientOrderId": "b7gBSe17919000001", "side": "SELL", "positionSide": "SHORT", "price": "100500",
                      "origQty": "0.0036", "status": "NEW", "executedQty": "0", "avgPrice": "0", "reduceOnly": False}
    for _ in range(2):
        tick(g)
    g = build()
    tick(g)
    assert ex.orders[oid]["status"] == "CANCELED"
    h = handovers(tmp_path)
    assert len(h) == 1 and float(h[0]["qty"]) == 0.0
    tr = g.st["SHORT"]["transfers"]
    assert len(tr) == 2 and tr[-1]["mtm"] == 0.0 and tr[-1]["lots"] == 0
    assert g.st["SHORT"]["transferred_mtm"] == 0.0 and not g.st["SHORT"].get("entry")


# ---------- L3-1: карточка /weex до первого прохода видит передачу из журнала своей сетки
def _old_format_state(p: Path, cfg: dict) -> tuple[Path, Path, Path]:
    cfg_p, st_p, jr_p = p / "weex_grid_config.json", p / "weex_grid_state.json", p / "weex_grid_journal.jsonl"
    cfg_p.write_text(json.dumps(cfg), encoding="utf-8")
    st = {"symbol": "BTCUSDT", "LONG": eg.new_side_state(), "SHORT": eg.new_side_state(), "halted": False,
          "halt_reason": "", "day": None, "day_start_pnl": 0.0}
    st["SHORT"]["realized"], st["SHORT"]["fees"] = 2.0, .5
    for s in ("LONG", "SHORT"):                          # учёт в формате до 13.10
        st[s].pop("transferred_mtm")
        st[s].pop("transfers")
    st_p.write_text(json.dumps(st), encoding="utf-8")
    rec = {"ts": "2026-10-12T10:00:00+00:00", "dry": False, "side": "SHORT", "kind": HAND, "qty": "0.0012",
           "avg": 100200.0, "mark": 100350.0, "bag": -5.0, "lots": 1}
    jr_p.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
    return cfg_p, st_p, jr_p


class _CardClient:
    def __init__(self, *a, **kw):
        pass

    def sync_time(self):
        return 0

    def book(self, symbol):
        return 100000. - .05, 100000. + .05


def test_card_before_first_tick_shows_migrated_transfer(tmp_path, monkeypatch):
    cfg = {**eg.DEFAULT, "enabled": True, "dry_run": False, "sides": ["LONG"], "release_sides": ["SHORT"]}
    cfg_p, st_p, jr_p = _old_format_state(tmp_path, cfg)
    monkeypatch.setattr(eg, "CONFIG", cfg_p)
    monkeypatch.setattr(eg, "STATE", st_p)
    monkeypatch.setattr(eg, "JOURNAL", jr_p)
    monkeypatch.setattr(eg.load_config, "__defaults__", (cfg_p, None))
    monkeypatch.setattr(eg, "GRIDS", ("BTC",))
    monkeypatch.setattr(wc, "WeexClient", _CardClient)
    before = st_p.read_bytes()
    out = lp.card("BTC")
    assert "🤝 ШОРТ передан оператору 2026-10-12 10:00" in out and "мешок при передаче $-5.00" in out
    assert "итог сетки с мешком $-3.50" in out           # 2.0 − 0.5 − 5.0, а не +1.50 без переданного мешка
    assert st_p.read_bytes() == before                   # карточка учёт не пишет


def test_missing_journal_does_not_mark_transfer_migration_done(tmp_path):
    cfg = {**eg.DEFAULT, "enabled": True, "dry_run": False, "sides": ["LONG"], "release_sides": ["SHORT"]}
    _, st_p, jr_p = _old_format_state(tmp_path, cfg)
    g = eg.Grid(eg.DryExchange(Px()), cfg, state_path=st_p, journal_path=tmp_path / "нет.jsonl")
    assert "transferred_mtm" not in g.st["SHORT"]        # история стороны есть, журнала нет — не «перенесено 0»
    assert "transferred_mtm" in g.st["LONG"]             # у пустой стороны переносить нечего
    g.save()
    g = eg.Grid(eg.DryExchange(Px()), cfg, state_path=st_p, journal_path=jr_p)
    assert g.bot_pnl(100000.) == pytest.approx(2.0 - .5 - 5.0)
    assert len(g.st["SHORT"]["transfers"]) == 1


# ---------- L3-2: конечный статус без executedQty — не конец тейка (probe_w_test)
@pytest.mark.parametrize("status", ["FILLED", "CANCELED"])
def test_terminal_without_executed_qty_keeps_single_tp(tmp_path, status):
    g, ex, px, clock, regime, build, tick, cfg = fixture(tmp_path)
    tp_id = g.st["LONG"]["lots"][0]["tp_order"]["id"]
    restore = hide(ex, tp_id, {"orderId": tp_id, "status": status})      # нет executedQty
    for _ in range(3):
        tick(g)
    assert live_tps(ex) == [tp_id]
    assert g.st["LONG"]["lots"][0]["tp_order"]["id"] == tp_id
    assert "конечный статус без executedQty" in disk(tmp_path)["last_tick_error"]["err"]
    restore()
    tick(g)
    assert live_tps(ex) == [tp_id]


# ---------- L3-2: неясная сирота снимается снова на следующем проходе и остаётся в учёте
@pytest.mark.parametrize("path", ["side", "release"])
def test_unknown_stray_is_cancelled_again_and_kept(tmp_path, path):
    if path == "release":
        g, ex, px, clock, build, tick, cfg = _release_fixture(tmp_path)
        side, ps, bs, kind = "SHORT", "SHORT", "BUY", "t"
        g.st["SHORT"]["lots"] = [{"entry": 100000.0, "qty": "0.0001", "tp": 99000.0, "tp_order": None, "t": clock["t"]}]
    else:
        g, ex, px, clock, regime, build, tick, cfg = fixture(tmp_path)
        side, ps, bs, kind = "LONG", "LONG", "BUY", "e"
    ex.orders["stray"] = {"clientOrderId": f"b7gB{side[0]}{kind}_old", "side": bs, "positionSide": ps,
                          "price": "99000", "origQty": "0.0001", "status": "NEW", "executedQty": "0", "avgPrice": "0",
                          "reduceOnly": kind == "t"}
    g.st[side]["strays"] = [{"id": "stray", "cid": f"b7gB{side[0]}{kind}_old", "price": 99000.0, "qty": "0.0001",
                             "kind": kind}]
    g.save()
    real_info, real_cancel = ex.order_info, ex.cancel
    calls = []

    def cancel(oid):
        if str(oid) == "stray":
            calls.append(oid)
            if len(calls) == 1:
                return {"success": False}              # первое снятие не прошло
        return real_cancel(oid)
    ex.cancel = cancel
    ex.order_info = lambda oid: {} if str(oid) == "stray" else real_info(oid)
    tick(g)
    assert len(calls) >= 1 and ex.orders["stray"]["status"] == "NEW"
    assert [x["id"] for x in disk(tmp_path)[side]["strays"]] == ["stray"]
    n1 = len(calls)
    tick(g)
    assert len(calls) > n1 and ex.orders["stray"]["status"] == "CANCELED"   # снова снята на следующем проходе
    assert [x["id"] for x in disk(tmp_path)[side]["strays"]] == ["stray"]  # деталь неясна — из учёта не убрана
    ex.order_info = real_info
    tick(g)
    assert not disk(tmp_path)[side]["strays"]


# ---------- форма реального ответа WEEX GET /capi/v3/order (14.10, живой счёт; номера синтетические)
REAL_KEYS = {"avgPrice", "clientOrderId", "cumQuote", "executedQty", "orderId", "origQty", "positionSide", "price",
             "reduceOnly", "side", "status", "stopPrice", "symbol", "time", "timeInForce", "type", "updateTime",
             "workingType"}


def real_order(oid: int, status: str, exq: str, side: str, reduce: bool, symbol: str = "BTCUSDT",
               orig: str = "0.0012", price: str = "100100.0") -> dict:
    avg = price if float(exq) > 0 else "0"
    return {"avgPrice": avg, "clientOrderId": "b7gBLt17999999991", "cumQuote": f"{float(exq) * float(price):.4f}",
            "executedQty": exq, "orderId": oid, "origQty": orig, "positionSide": "LONG", "price": price,
            "reduceOnly": reduce, "side": side, "status": status, "stopPrice": "0", "symbol": symbol,
            "time": 1797000000000, "timeInForce": "GTC", "type": "LIMIT", "updateTime": 1797000060000,
            "workingType": "CONTRACT_PRICE"}


class _OneOrder:
    def __init__(self, d):
        self.d = d

    def order_info(self, oid):
        return dict(self.d)


@pytest.mark.parametrize("name,detail,kind,fill", [
    ("live_tp", real_order(804234146900000011, "NEW", "0", "SELL", True), "live", 0.0),
    ("filled_tp", real_order(804234146900000012, "FILLED", "0.0012", "SELL", True), "terminal", .0012),
    ("filled_entry", real_order(804234146900000013, "FILLED", "0.0036", "BUY", False, orig="0.0036"), "terminal",
     .0036),
    ("cancelled_entry", real_order(804234146900000014, "CANCELED", "0", "BUY", False), "terminal", 0.0),
    ("cancelled_entry_part", real_order(804234146900000015, "CANCELED", "0.0004", "BUY", False), "terminal", .0004),
    ("eth_filled_entry", real_order(804234146900000016, "FILLED", "0.020", "BUY", False, symbol="ETHUSDT",
                                    orig="0.020", price="4100.00"), "terminal", .02),
])
def test_real_weex_detail_shape_is_classified(tmp_path, name, detail, kind, fill):
    assert set(detail) == REAL_KEYS and isinstance(detail["orderId"], int)
    sym = detail["symbol"]
    cfg = {**eg.DEFAULT, "symbol": sym, "qty_step": .001 if sym == "ETHUSDT" else .0001}
    g = eg.Grid(_OneOrder(detail), cfg, state_path=tmp_path / "st.json", journal_path=tmp_path / "j.jsonl")
    oid = str(detail["orderId"])                          # учёт хранит номер строкой
    got, info = g._detail(oid, "LONG", {"id": oid, "filled": 0.0})
    assert got == kind and float(info["executedQty"]) == pytest.approx(fill)
    assert not g._issues


class RealShapeExchange(eg.DryExchange):
    """Имитатор, отвечающий в форме реального WEEX: orderId — ЧИСЛО (учёт хранит строку), executedQty — строка и у
    CANCELED, полный набор ключей GET /capi/v3/order."""
    BASE = 804234146900000000

    def _renumber(self, r):
        if r.get("success") and r.get("orderId"):
            old, new = r["orderId"], str(self.BASE + self.n)
            self.orders[new] = self.orders.pop(old)
            if old in self.trades:
                self.trades[new] = [{**x, "orderId": int(new)} for x in self.trades.pop(old)]
            r = {**r, "orderId": int(new)}
        return r

    def place_limit(self, *a, **kw):
        return self._renumber(super().place_limit(*a, **kw))

    def place_market(self, *a, **kw):
        return self._renumber(super().place_market(*a, **kw))

    def shape(self, oid: str, o: dict) -> dict:
        exq = o.get("executedQty") or "0"
        avg = o.get("avgPrice") if float(exq) > 0 else "0"
        return {"avgPrice": avg, "clientOrderId": o["clientOrderId"],
                "cumQuote": f"{float(exq) * float(avg or 0):.4f}", "executedQty": exq, "orderId": int(oid),
                "origQty": o["origQty"], "positionSide": o["positionSide"], "price": o["price"],
                "reduceOnly": bool(o["reduceOnly"]), "side": o["side"], "status": o["status"], "stopPrice": "0",
                "symbol": self.symbol, "time": 1797000000000, "timeInForce": "GTC", "type": o.get("type", "LIMIT"),
                "updateTime": 1797000060000, "workingType": "CONTRACT_PRICE"}

    def order_info(self, oid):
        return self.shape(str(oid), self.orders[str(oid)])

    def open_orders(self, symbol):
        return [self.shape(k, v) for k, v in self.orders.items() if v["status"] == "NEW"]

    def order_history(self, symbol, limit=100, page=0, start_ms=None, end_ms=None):
        rows = [self.shape(k, v) for k, v in list(self.orders.items())[::-1]]
        return rows[page * limit:(page + 1) * limit]


def _journal(p: Path) -> list[dict]:
    return [json.loads(x) for x in (p / "journal.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]


def test_real_weex_shape_through_ticks(tmp_path):
    """Вход исполнен → лот; живой тейк вне списка → живой (второго нет); тейк исполнен → прибыль один раз;
    вход снят с частичным исполнением (CANCELED, executedQty строкой) → лот на исполненное, вход забыт."""
    t = live_grid(tmp_path, RealShapeExchange)
    assert set(t.ex.order_info(next(iter(t.ex.orders)))) == REAL_KEYS
    s = t.g.st["LONG"]
    lot = s["lots"][0]
    tp_id = lot["tp_order"]["id"]
    assert isinstance(tp_id, str) and tp_id.startswith("8042341469") and s["entry"]["id"].startswith("8042341469")
    entries = [r for r in _journal(tmp_path) if r["kind"] == "вход"]
    assert len(entries) == 1 and float(entries[0]["qty"]) == pytest.approx(.0012)
    # живой тейк пропал из одного ответа списка: деталь NEW (orderId числом) → живой, второго тейка нет
    restore = hide(t.ex, tp_id, t.ex.order_info(tp_id))
    for _ in range(3):
        t.g = t.tick()
    restore()
    assert live_tps(t.ex) == [tp_id] and not t.g.st.get("unknown_orders")
    # тейк исполнен
    entry, tp = lot["entry"], lot["tp"]
    t.px.mid = tp + 1.
    for _ in range(2):
        t.g = t.tick()
    s = t.g.st["LONG"]
    assert s["realized"] == pytest.approx(.0012 * (tp - entry)) and s["n_tps"] == 1
    assert len([r for r in _journal(tmp_path) if r["kind"] == "тейк"]) == 1
    # стоящий вход частично исполнился и снят (выключение): лот на 0.0004, вход забыт
    e_id = s["entry"]["id"]
    o = t.ex.orders[e_id]
    o.update(executedQty="0.0004", avgPrice=o["price"])
    t.cfg["enabled"] = False
    t.g = t.tick()
    s = t.g.st["LONG"]
    assert t.ex.orders[e_id]["status"] == "CANCELED" and s["entry"] is None
    assert [float(l["qty"]) for l in s["lots"]] == [pytest.approx(.0004)]
    assert not t.g.st.get("unknown_orders") and disk(tmp_path)["last_tick_ok_ts"] == ts_eq(t.clock["t"])
