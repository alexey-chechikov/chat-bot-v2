"""Разбор GPT aadc2a4 (12.11.2026): каждое воспроизведение дефекта на 239b426 — здесь как тест БЕЗОПАСНОГО поведения.
На 239b426 эти тесты падают (проверено переносом в worktree старого коммита), на исправленном коде проходят.
Плюс усиление входа системы сигналом 432 (поручение оператора 12.11): обычный вход, усиленный, ограничение потолком."""
from __future__ import annotations

import io
import json
from urllib.error import HTTPError

import numpy as np
import pytest

from services.sigexec import lines, run
from services.sigexec.exchange.base import LONG, SELL, SHORT, OrderReq, Unknown, Incomplete
from services.sigexec.exchange.bybit import parse_order
from services.sigexec.exchange.okx import OkxExchange
from services.sigexec.exchange.sim import SimExchange
from services.sigexec.exchange.weex import WeexExchange
from services.sigexec.executor import Executor, Halt
from services.sigexec.feed import H1, MIN_HOURS, HourFeed
from services.sigexec.strategy import Desired, q432_long_at

T = 1_800_000_000
OKX_INST = {"code": "0", "data": [{"ctVal": "0.01", "tickSz": "0.1", "lotSz": "0.01", "minSz": "0.01"}]}


def signal(slot="system", **kw):
    v = dict(slot=slot, entry_t=T, side=1, tag="над синей", w=1, sig_px=70000, main_frac=0.5, add_lv=72000, add_frac=0.5, add_done=False,
             target=None, exit_by_t=None, exit_text="")
    v.update(kw)
    return Desired(**v)


def build(path, exchange=None, **kw):
    exchange = exchange or SimExchange()
    exchange._t = T + 5
    cfg = {"enabled": True, "base_usd": 1000, "cap_usd": 5000}
    cfg.update(kw)
    return Executor(exchange, cfg, path / "state.json", path / "journal.jsonl"), exchange


def orders(e, role):
    return [r for r in e.st["orders"].values() if r["role"] == role]


# ---------------------------------------------------------------- P1-1: повтор заявки после потери процесса
def test_no_duplicate_market_exit_after_process_loss(tmp_path):
    e, ex = build(tmp_path, entry={"kind": "market"}, exit={"kind": "market"})
    d = {"system": signal(add_lv=None, add_frac=0)}
    e.step(d)
    e.step(d)
    ex.external_trade(LONG, 0.01)                         # чужой лонг на той же стороне
    ex.fail_next("place", "unknown_placed")
    jr = e._jr

    def lose(rec):
        if rec.get("role") == "exit":
            raise SystemExit("процесс потерян сразу после UNKNOWN на диске")
        jr(rec)

    e._jr = lose
    with pytest.raises(SystemExit):
        e.step({})
    e.close()                                              # смерть процесса снимает блокировку
    r = Executor(ex, e.cfg, e.state_path, e.journal_path)
    ex.fail_next("order", "incomplete")
    r.step({})
    assert [(x["kind"], x["status"]) for x in orders(r, "exit")] == [("MARKET", "UNKNOWN")]   # второго рыночного нет
    assert ex.pos[LONG] == pytest.approx(0.01)
    r.step({})                                             # поиск ответил — эпизод закрыт, чужое цело
    assert r.st["slots"]["system"]["ep"] is None and ex.pos[LONG] == pytest.approx(0.01)


def test_hidden_filled_market_becomes_unresolved_not_absent(tmp_path):
    said = []
    e, ex = build(tmp_path, entry={"kind": "market"}, exit={"kind": "market"})
    e.notify = said.append
    d = {"system": signal(add_lv=None, add_frac=0)}
    e.step(d)
    e.step(d)
    ex.external_trade(LONG, 0.01)
    ex.fail_next("place", "unknown_placed")
    e.step({})
    cid = orders(e, "exit")[0]["cid"]
    visible = ex.order
    ex.order = lambda symbol, key, *a: None if key == cid else visible(symbol, key, *a)
    ex.tick_clock(200)
    e.step({})
    e.step({})
    assert [x["status"] for x in orders(e, "exit")] == ["UNRESOLVED"]    # позиция изменилась — не «не встала»
    assert ex.pos[LONG] == pytest.approx(0.01)                           # чужой лонг не тронут вторым закрытием
    assert any("исход неизвестен" in s for s in said)
    e.resolve(cid, "filled", 0.0071, 70000.0)
    e.step({})
    assert e.st["slots"]["system"]["ep"] is None and ex.pos[LONG] == pytest.approx(0.01)


def test_lost_market_with_unchanged_position_is_absent_and_retried(tmp_path):
    e, ex = build(tmp_path, entry={"kind": "market"})
    ex.fail_next("place", "unknown_lost")
    e.step({"system": signal(add_lv=None, add_frac=0)})
    ex.tick_clock(200)
    e.step({"system": signal(add_lv=None, add_frac=0)})
    e.step({"system": signal(add_lv=None, add_frac=0)})
    assert [x["status"] for x in orders(e, "entry")] == ["ABSENT", "FILLED"]
    assert ex.pos[LONG] == pytest.approx(0.0071)


def test_okx_http400_50004_is_unknown():
    def http(method, url, headers, data):
        if "/public/instruments" in url:
            return OKX_INST
        raise HTTPError(url, 400, "Bad Request", {}, io.BytesIO(b'{"code":"50004","msg":"Endpoint request timeout","data":[]}'))

    with pytest.raises(Unknown):
        OkxExchange(http=http).place(OrderReq(cid="c", symbol="BTCUSDT", side=SELL, pos_side=LONG, kind="MARKET", qty=0.01, reduce_only=True))


def test_okx_http_error_without_body_is_unknown():
    def http(method, url, headers, data):
        if "/public/instruments" in url:
            return OKX_INST
        raise HTTPError(url, 502, "Bad Gateway", {}, io.BytesIO(b"<html>"))

    with pytest.raises(Unknown):
        OkxExchange(http=http).place(OrderReq(cid="c", symbol="BTCUSDT", side=SELL, pos_side=LONG, kind="MARKET", qty=0.01))


# ---------------------------------------------------------------- P1-3 / P1-4: аварийный стоп и выход
def test_add_cancelled_after_emergency_stop(tmp_path):
    e, ex = build(tmp_path, entry={"kind": "market"})
    d = {"system": signal()}
    e.step(d)
    e.step(d)
    ex.move(61000)                                         # аварийный стоп 61 600 сработал
    e.step(d)
    e.step(d)
    assert e.st["slots"]["system"]["ep"] is None
    assert [x["status"] for x in orders(e, "add")] == ["CANCELED"]
    ex.move(72100)
    e.step(d)
    assert ex.pos[LONG] == 0                               # старый добор позицию не открыл


def test_breached_emergency_level_exits_by_market(tmp_path):
    e, ex = build(tmp_path, entry={"kind": "market"})
    d = {"system": signal(add_lv=None, add_frac=0)}
    e.step(d)                                             # вход
    e.step(d)                                             # стоп на исполненный объём
    stop, = orders(e, "stop")
    ex.orders[stop["cid"]]["status"] = "CANCELED"         # стоп пропал на бирже
    ex.fail_next("place", "reject")                       # повторная постановка отклонена
    e.step(d)
    assert [x["status"] for x in orders(e, "stop")] == ["CANCELED", "REJECTED"]
    ex.px = 60000.0                                        # цена за аварийным уровнем 61 600, стопа нет
    e.step(d)
    assert [x["kind"] for x in orders(e, "exit")] == ["MARKET"]   # сразу рыночным, без догона
    assert ex.pos[LONG] == 0


def test_partial_entry_is_protected_by_stop(tmp_path):
    e, ex = build(tmp_path)
    d = {"system": signal(add_lv=None, add_frac=0)}
    e.step(d)
    ex.partial_next(0.4)
    ex.move(69990)
    e.step(d)
    assert e.st["slots"]["system"]["ep"]["phase"] == "entering"
    stops = [x for x in orders(e, "stop") if x["status"] == "UNTRIGGERED"]
    assert len(stops) == 1 and stops[0]["qty"] == pytest.approx(0.0028)


def test_dedicated_account_target_then_stop_does_not_overclose(tmp_path):
    e, ex = build(tmp_path, entry={"kind": "market"})
    d = {"system": signal(side=-1, tag="под жёлтой", main_frac=1, add_lv=None, add_frac=0, target=68000)}
    e.step(d)
    e.step(d)
    ex.move(67000)                                          # цель исполнилась
    ex.move(80000)                                          # стоп сработал до опроса — reduceOnly на пустой стороне
    e.step(d)
    e.step(d)
    assert ex.pos[SHORT] == 0 and e.st["slots"]["system"]["ep"] is None
    assert sum(x["filled"] for x in orders(e, "target") + orders(e, "stop")) == pytest.approx(0.0142)


def test_shared_account_refuses_target_plus_stop_episode(tmp_path):
    e, ex = build(tmp_path, entry={"kind": "market"}, shared_account=True)
    e.step({"system": signal(side=-1, tag="под жёлтой", main_frac=1, add_lv=None, add_frac=0, target=68000)})
    assert e.st["slots"]["system"]["ep"] is None and not e.st["orders"]


def test_stale_feed_keeps_confirmed_target(tmp_path):
    e, ex = build(tmp_path, entry={"kind": "market"})
    d = {"system": signal(side=-1, tag="под жёлтой", main_frac=1, add_lv=None, add_frac=0, target=68000)}
    e.step(d)
    e.step(d)
    e.step(None)                                            # данные несвежие
    assert [x["status"] for x in orders(e, "target")] == ["NEW"]
    ex.move(67000)
    e.step(None)
    assert ex.pos[SHORT] == 0


# ---------------------------------------------------------------- P1-5: потолок и добор
def test_partial_add_reissues_only_remainder_within_cap(tmp_path):
    e, ex = build(tmp_path, cap_usd=1000, entry={"kind": "market"})
    d = {"system": signal()}
    e.step(d)
    e.step(d)
    ex.partial_next(0.5)
    ex.move(72100)
    ex.move(71000)
    e.step(d)
    adds = orders(e, "add")
    assert [round(x["qty"], 4) for x in adds] == [0.0069, 0.0035]
    ex.move(72100)
    e.step(d)
    assert sum(x["filled"] for x in orders(e, "add")) == pytest.approx(0.0069)
    assert sum(x["filled"] * x["avg"] for x in orders(e, "entry") + orders(e, "add")) <= 1000 * 1.001


def test_cap_keeps_entry_reservation_through_cancel(tmp_path):
    e, ex = build(tmp_path, cap_usd=1000, entry={"kind": "chase", "wait_s": 10, "reprice_s": 300})
    d = {"system": signal(main_frac=1, add_lv=None, add_frac=0)}
    e.step(d)
    ex.tick_clock(11)
    both = dict(d, **{"432": signal(slot="432", tag="432", main_frac=1, add_lv=None, add_frac=0)})
    e.step(both)
    e.step(both)
    ex.move(69990)
    e.step(both)
    assert e.st["slots"]["432"]["ep"] is None               # места не было — бронь первого слота держится
    assert ex.pos[LONG] * 70000 <= 1000 * 1.001


def test_market_sized_at_execution_price(tmp_path):
    e, ex = build(tmp_path, SimExchange(price=77000), cap_usd=1000, entry={"kind": "market"})
    e.step({"432": signal(slot="432", tag="432", main_frac=1, add_lv=None, add_frac=0)})
    fill, = orders(e, "entry")
    assert fill["filled"] * fill["avg"] <= 1000 * 1.001


# ---------------------------------------------------------------- P1-6: изоляция учёта
def test_demo_and_live_state_are_separate():
    base = {"exchange": {"name": "okx", "paper": False}, "feed": {}, "executor": {}}
    demo = dict(base, exchange={"name": "okx", "paper": False, "testnet": True})
    assert run.state_tag(demo) != run.state_tag(base)
    assert run.state_tag(demo).startswith("okx-demo-") and run.state_tag(base).startswith("okx-live-")
    acc2 = dict(base, exchange={"name": "okx", "paper": False, "account": "sub2"})
    assert run.state_tag(acc2) != run.state_tag(base)


def test_unsupported_flag_combinations_halt(tmp_path):
    with pytest.raises(Halt):
        run.make_exchange({"name": "weex", "paper": False, "testnet": True}, tmp_path)
    with pytest.raises(Halt):
        run.env_of({"name": "okx", "paper": True, "testnet": True})
    with pytest.raises(Halt):
        run.check_executor_cfg({"exchange": {"name": "weex", "paper": False}, "executor": {"allowed_sides": ["LONG", "SHORT"]}})
    assert run.check_executor_cfg({"exchange": {"name": "weex", "paper": False}, "executor": {"allowed_sides": ["LONG"]}})["shared_account"] is True


def test_second_writer_halts(tmp_path):
    first, ex = build(tmp_path)
    with pytest.raises(Halt, match="другой процесс"):
        Executor(ex, first.cfg, first.state_path, first.journal_path)


# ---------------------------------------------------------------- адаптеры, сверка, команды, данные
def test_okx_effective_algo_uses_child_list():
    def http(method, url, headers, data):
        if "/public/instruments" in url:
            return OKX_INST
        if "/trade/order-algo" in url:
            return {"code": "0", "data": [{"state": "effective", "algoId": "a", "ordIdList": ["child"]}]}
        assert "ordId=child" in url
        return {"code": "0", "data": [{"state": "filled", "ordId": "child", "accFillSz": "1", "avgPx": "61600", "fee": "-0.03"}]}

    o = OkxExchange(http=http).order("BTCUSDT", "s1", "STOP")
    assert (o.status, o.filled) == ("FILLED", pytest.approx(0.01))


def test_okx_cancel_after_trigger_cancels_child():
    calls = []

    def http(method, url, headers, data):
        if "/public/instruments" in url:
            return OKX_INST
        if method == "POST":
            calls.append((url.rsplit("/", 1)[-1], json.loads(data)))
            return {"code": "0", "data": [{"sCode": "0"}]}
        if "/trade/order-algo" in url:
            return {"code": "0", "data": [{"state": "effective", "algoId": "parent", "ordId": "child"}]}
        return {"code": "0", "data": [{"state": "live", "ordId": "child", "accFillSz": "0"}]}

    OkxExchange(http=http).cancel("BTCUSDT", "s1", "STOP", "parent")
    assert calls == [("cancel-order", {"instId": "BTC-USDT-SWAP", "ordId": "child"})]


def test_weex_partial_algo_history_is_incomplete():
    class C:
        def open_algo_orders(self, symbol):
            return []

        def get(self, *a):
            return {"hasMore": True, "orders": [{"clientAlgoId": "another"}]}

    with pytest.raises(Incomplete):
        WeexExchange(C()).order("BTCUSDT", "missing", "STOP")


def test_bybit_reads_current_fee_field():
    o = parse_order({"orderStatus": "Filled", "cumExecQty": "0.01", "avgPrice": "70000", "cumFeeDetail": {"USDT": "0.42"}})
    assert (o.fee, o.fee_known) == (pytest.approx(0.42), True)
    o = parse_order({"orderStatus": "Filled", "cumExecQty": "0.01", "avgPrice": "70000"})
    assert o.fee_known is False


def test_audit_counts_deficit_per_side(tmp_path):
    e, ex = build(tmp_path, entry={"kind": "market"})
    d = {"system": signal(add_lv=None, add_frac=0), "432": signal(slot="432", tag="432", side=-1, add_lv=None, add_frac=0)}
    e.step(d)
    e.step(d)
    ex.external_trade(LONG, -0.005)
    e.step(d)
    ex.external_trade(LONG, 0.005)
    ex.external_trade(SHORT, -0.005)
    e.step(d)
    assert not orders(e, "external")                        # дефицит SHORT виден один проход — рано
    e.step(d)
    ext, = orders(e, "external")
    assert ext["ep"] == f"432:{T}" and ext["filled"] == pytest.approx(0.005)


def test_close_all_blocks_entries_and_confirms_flat(tmp_path):
    e, ex = build(tmp_path, entry={"kind": "market"})
    d = {"system": signal(add_lv=None, add_frac=0)}
    e.step(d)
    e.step(d)
    e.close_all()
    both = dict(d, **{"432": signal(slot="432", tag="432", add_lv=None, add_frac=0)})
    e.step(both)
    e.step(both)
    assert [x["kind"] for x in orders(e, "exit")] == ["MARKET"]
    assert len(orders(e, "entry")) == 1 and ex.pos[LONG] == 0 and e.flat()
    e.step(both)
    assert e.st["slots"]["432"]["ep"] is None               # до reopen входов нет


def test_gap_in_hourly_feed_is_not_fresh(tmp_path):
    class Source:
        name = "test"

        def fetch(self, start, now):
            return [(t, 100, 101, 99, 100) for t in range(H1, (MIN_HOURS + 2) * H1, H1) if t != (MIN_HOURS - 5) * H1]

    feed = HourFeed(tmp_path / "hours.csv", Source())
    now = (MIN_HOURS + 1) * H1
    feed.update(now)
    assert not feed.fresh(now)


def test_first_hours_without_closed_h4_not_used():
    t = np.arange(1, 6) * H1
    px = np.array([100.0, 110, 130, 140, 150])
    a, _ = lines.build(t, px, px, px, px, i0_t=0)
    assert a["i0"] >= 4                                     # первый час, где обе 4ч известны честно


# ---------------------------------------------------------------- усиление входа сигналом 432
def test_boost_flag_semantics():
    ev = [{"kind": "вход", "t": 100}, {"kind": "выход", "t": 200}, {"kind": "вход", "t": 300}]
    assert q432_long_at(ev, None, 100) and q432_long_at(ev, None, 150)
    assert not q432_long_at(ev, None, 200) and not q432_long_at(ev, None, 250) and q432_long_at(ev, None, 300)
    assert not q432_long_at(ev, None, 50)


def test_normal_entry_size(tmp_path):
    e, ex = build(tmp_path, entry={"kind": "market"})
    e.step({"system": signal()})
    ep = e.st["slots"]["system"]["ep"]
    assert (ep["goal_main"], ep["goal_add"], ep["boost"]) == (pytest.approx(0.0071), pytest.approx(0.0069), 1.0)


def test_boosted_entry_size(tmp_path):
    e, ex = build(tmp_path, entry={"kind": "market"})
    e.step({"system": signal(main_frac=0.5 * 1.5, add_frac=0.5 * 1.5, boost=1.5)})
    ep = e.st["slots"]["system"]["ep"]
    assert (ep["goal_main"], ep["goal_add"], ep["boost"]) == (pytest.approx(0.0107), pytest.approx(0.0104), 1.5)


def test_boosted_entry_limited_by_cap_with_add_reserve(tmp_path):
    e, ex = build(tmp_path, entry={"kind": "market"}, cap_usd=1200)
    e.step({"system": signal(main_frac=0.5 * 2, add_frac=0.5 * 2, boost=2.0)})   # хочет $1000 + $1000 добора
    ep = e.st["slots"]["system"]["ep"]
    assert ep["goal_add"] == 0.0                            # добор не помещается — снят первым
    assert ep["goal_main"] == pytest.approx(0.0142)         # первый лот $1000 ≤ $1200
    e.step({"system": signal(main_frac=0.5 * 2, add_frac=0.5 * 2, boost=2.0)})
    assert e._reserved(ep) <= 1200 * 1.001


def test_evaluate_rejects_bad_boost():
    from services.sigexec import strategy
    t = np.arange(1, 30) * H1
    px = np.full(len(t), 100.0)
    with pytest.raises(ValueError):
        strategy.evaluate(t, px, px, px, px, boost_432=0.5)
