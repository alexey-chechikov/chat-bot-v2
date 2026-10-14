"""Разбор GPT 13.10 (docs/WEEX_GPT_GOLD_AND_BOTS_REVIEW_2026-10-13.md §2 W1/W2, дополнение §3): неизвестная деталь
ордера не считается завершением ни в одном пути (вход, тейк, несовпавший тейк, сирота, передача стороны); передача
пишет событие и при нуле лотов и не двигает заработанный итог; метка живости прохода; неполный список открытых
ордеров — ошибка, а не тихо обрезанный список. Сценарии — из weex_monitor_probes.py (прочитаны, не запускались).
Биржа — имитатор, это проверка логики, не замер реального WEEX."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.weex_api import client as wc
from services.weex_grid import engine as eg
from tests.services.weex_grid.test_weex_regime_gpt import PartialLiveExchange, Px, bot_markets, book, fixture

HAND = "передано оператору"


def live_tps(ex, side="LONG"):
    return [oid for oid, o in ex.orders.items() if o.get("reduceOnly") and o.get("type") != "MARKET"
            and o["status"] in eg.LIVE and o["positionSide"] == side
            and str(o.get("clientOrderId", "")).startswith(eg.PREFIX)]


def live_entries(ex, side="LONG"):
    return [oid for oid, o in ex.orders.items() if not o.get("reduceOnly") and o["status"] in eg.LIVE
            and o["positionSide"] == side and str(o.get("clientOrderId", "")).startswith(eg.PREFIX)]


def handovers(p: Path) -> list[dict]:
    j = p / "journal.jsonl"
    if not j.exists():
        return []
    return [r for r in (json.loads(x) for x in j.read_text(encoding="utf-8").splitlines() if x.strip())
            if r.get("kind") == HAND]


def disk(p: Path) -> dict:
    return json.loads((p / "st.json").read_text(encoding="utf-8"))


def ts_eq(t: float):
    """Сравнение меток времени (эпоха ~1.8e9 с): pytest.approx по умолчанию допускает 1e-6 относительно — это
    ±1800 с, и проход 10 с спустя считался бы «тем же». Допуск — миллисекунда."""
    return pytest.approx(t, rel=0, abs=1e-3)


def hide(ex, oid, detail):
    """Ордер пропал из одного ответа списка открытых, а деталь ордера — пустая/чужая/неизвестная."""
    real_open, real_info = ex.open_orders, ex.order_info
    ex.open_orders = lambda sym: [o for o in real_open(sym) if str(o["orderId"]) != oid]
    ex.order_info = lambda x: dict(detail) if str(x) == oid else real_info(x)

    def restore():
        ex.open_orders, ex.order_info = real_open, real_info
    return restore


def bad_details(oid: str) -> dict:
    return {
        "empty": {},
        "foreign_id": {"orderId": "OTHER", "status": "FILLED", "executedQty": "0"},
        "foreign_id_canceled": {"orderId": "OTHER", "status": "CANCELED", "executedQty": "0"},
        "unknown_status": {"orderId": oid, "status": "WEIRD", "executedQty": "0"},
        "no_status": {"orderId": oid, "executedQty": "0"},
        "filled_without_fill": {"orderId": oid, "status": "FILLED", "executedQty": "0", "origQty": "0.0012"},
        "other_position_side": {"orderId": oid, "status": "CANCELED", "executedQty": "0", "positionSide": "SHORT"},
        "other_symbol": {"orderId": oid, "status": "CANCELED", "executedQty": "0", "symbol": "ETHUSDT"},
    }


# ---------- W1: пропавший из списка живой тейк + неизвестная деталь → ровно один тейк, и после рестарта
@pytest.mark.parametrize("case", list(bad_details("x")))
def test_w1_missing_tp_with_unknown_detail_keeps_single_tp(tmp_path, case):
    g, ex, px, clock, regime, build, tick, cfg = fixture(tmp_path)
    tp_id = g.st["LONG"]["lots"][0]["tp_order"]["id"]
    restore = hide(ex, tp_id, bad_details(tp_id)[case])
    for _ in range(3):
        tick(g)
    g = build()                                        # рестарт: учёт с диска
    tick(g)
    tick(g)
    assert live_tps(ex) == [tp_id]
    assert g.st["LONG"]["lots"][0]["tp_order"]["id"] == tp_id
    restore()
    tick(g)
    tick(g)
    assert live_tps(ex) == [tp_id]


# ---------- W1: вход пропал из списка + {} → второго входа нет
def test_w1_missing_entry_with_unknown_detail_places_no_second_entry(tmp_path):
    g, ex, px, clock, regime, build, tick, cfg = fixture(tmp_path)
    e_id = g.st["LONG"]["entry"]["id"]
    restore = hide(ex, e_id, {})
    for _ in range(3):
        tick(g)
    g = build()
    tick(g)
    assert live_entries(ex) == [e_id] and g.st["LONG"]["entry"]["id"] == e_id
    restore()
    tick(g)
    assert live_entries(ex) == [e_id]


# ---------- W1: тейк не того объёма, снятие не подтвердилось, деталь {} → замены нет, пока исход неясен
def test_w1_tp_mismatch_unconfirmed_cancel_places_no_replacement(tmp_path):
    g, ex, px, clock, regime, build, tick, cfg = fixture(tmp_path)
    tp_id = g.st["LONG"]["lots"][0]["tp_order"]["id"]
    ex.orders[tp_id]["origQty"] = "0.0013"            # на бирже другой объём, чем у лота
    real_cancel, real_info = ex.cancel, ex.order_info
    ex.cancel = lambda oid: {"success": False} if str(oid) == tp_id else real_cancel(oid)
    ex.order_info = lambda oid: {} if str(oid) == tp_id else real_info(oid)
    for _ in range(3):
        tick(g)
    g = build()
    tick(g)
    assert live_tps(ex) == [tp_id]
    ex.cancel, ex.order_info = real_cancel, real_info
    tick(g)
    tps = live_tps(ex)
    assert len(tps) == 1 and tps[0] != tp_id and ex.orders[tp_id]["status"] == "CANCELED"
    assert float(ex.orders[tps[0]]["origQty"]) == pytest.approx(.0012)


# ---------- W1: настоящий конечный статус после неясного — исполнение учтено один раз, замена только на остаток
def test_w1_terminal_after_unknown_books_partial_once_and_replaces_remainder(tmp_path):
    g, ex, px, clock, regime, build, tick, cfg = fixture(tmp_path)
    lot = g.st["LONG"]["lots"][0]
    tp_id, entry, tp_px = lot["tp_order"]["id"], lot["entry"], float(lot["tp_order"]["price"])
    fee0 = g.st["LONG"]["fees"]
    o = ex.orders[tp_id]
    o.update(status="CANCELED", executedQty="0.0004", avgPrice=str(tp_px))      # исполнился на треть и снят
    tp_fee = .0004 * tp_px * .00016
    ex.trades[tp_id] = [{"id": "t" + tp_id, "orderId": tp_id, "commission": str(tp_fee), "maker": True,
                         "price": str(tp_px), "qty": "0.0004", "time": int(clock["t"] * 1000)}]
    restore = hide(ex, tp_id, {})
    tick(g)
    tick(g)
    assert g.st["LONG"]["lots"][0]["tp_order"]["id"] == tp_id and not live_tps(ex)   # неясно — ничего не ставим
    restore()
    tick(g)
    want = .0004 * (tp_px - entry)
    assert g.st["LONG"]["realized"] == pytest.approx(want)
    for _ in range(2):
        tick(g)
    g = build()
    tick(g)
    tick(g)
    s = g.st["LONG"]
    assert s["realized"] == pytest.approx(want)                                  # один раз
    assert s["fees"] == pytest.approx(fee0 + tp_fee)
    assert sum(float(x["qty"]) for x in s["lots"]) == pytest.approx(.0008)
    tps = live_tps(ex)
    assert len(tps) == 1 and float(ex.orders[tps[0]]["origQty"]) == pytest.approx(.0008)


# ---------- W1 (рыночное закрытие): деталь, противоречащая курсору или чужой стороны, — не конец market
def _stale_market_details(oid: str) -> dict:
    return {
        "below_cursor": {"orderId": oid, "status": "CANCELED", "executedQty": "0", "positionSide": "LONG"},
        "other_side_filled": {"orderId": oid, "status": "FILLED", "executedQty": "0.0012", "positionSide": "SHORT"},
        "empty": {},
    }


@pytest.mark.parametrize("case", list(_stale_market_details("x")))
def test_w1_flatten_unknown_detail_sends_no_second_market_and_books_once(tmp_path, case):
    g, ex, px, clock, regime, build, tick, cfg = fixture(tmp_path, PartialLiveExchange)
    regime["up"] = False
    tick(g)                                            # тейк снят, market отправлен — исполнился наполовину
    tick(g)                                            # половина учтена курсором
    fl = g.st["LONG"]["flatten"]
    oid = fl["id"]
    assert float(fl["filled"]) == pytest.approx(.0006) and book(g) == pytest.approx(.0006)
    real_info = ex.order_info
    ex.order_info = lambda x: dict(_stale_market_details(oid)[case]) if str(x) == oid else real_info(x)
    for _ in range(3):
        tick(g)
    g = build()
    tick(g)
    assert len(bot_markets(ex)) == 1                   # второго рыночного нет
    fl = g.st["LONG"].get("flatten")
    assert fl is not None and fl["id"] == oid               # market не забыт по противоречивой детали
    assert book(g) == pytest.approx(.0006)                  # остаток не «закрыт» фантомным исполнением
    ex.order_info = real_info
    o = ex.orders[oid]
    o.update(status="FILLED", executedQty=o["origQty"])    # настоящий конец: исполнился остаток
    tick(g)
    tick(g)
    assert len(bot_markets(ex)) == 1 and not g.st["LONG"]["lots"] and g.st["LONG"].get("flatten") is None
    closes = [json.loads(x) for x in (tmp_path / "journal.jsonl").read_text(encoding="utf-8").splitlines()
              if "закрытие по режиму" in x]
    assert sum(float(r["qty"]) for r in closes) == pytest.approx(.0012)   # каждое исполнение — один раз


# ---------- W2: живой stray с неизвестной деталью не исчезает; передача — только после подтверждения, один раз
def _release_fixture(p: Path):
    px = Px(100000.)
    clock = {"t": 1800000000.}
    ex = eg.DryExchange(px, now_fn=lambda: clock["t"])
    cfg = {**eg.DEFAULT, "enabled": True, "dry_run": True, "sides": ["LONG"], "release_sides": ["SHORT"],
           "order_qty": "0.0012", "daily_loss_stop_usd": 0., "stress_budget_frac": 0.}

    def build():
        return eg.Grid(ex, cfg, state_path=p / "st.json", journal_path=p / "journal.jsonl", now_fn=lambda: clock["t"])

    def tick(g):
        clock["t"] += 10
        g.tick()
    return build(), ex, px, clock, build, tick, cfg


def test_w2_unknown_stray_survives_ticks_and_restart_then_release_once(tmp_path):
    g, ex, px, clock, build, tick, cfg = _release_fixture(tmp_path)
    ex.orders["stray"] = {"clientOrderId": "b7gBSt_old", "side": "BUY", "positionSide": "SHORT", "price": "99000",
                          "origQty": "0.0001", "status": "NEW", "executedQty": "0", "avgPrice": "0", "reduceOnly": True}
    g.st["SHORT"]["lots"] = [{"entry": 100000.0, "qty": "0.0001", "tp": 99000.0, "tp_order": None, "t": clock["t"]}]
    g.st["SHORT"]["strays"] = [{"id": "stray", "cid": "b7gBSt_old", "price": 99000.0, "qty": "0.0001", "kind": "t"}]
    g.save()
    real_info, real_cancel = ex.order_info, ex.cancel
    ex.order_info = lambda oid: {} if str(oid) == "stray" else real_info(oid)
    ex.cancel = lambda oid: {"success": False} if str(oid) == "stray" else real_cancel(oid)
    for _ in range(3):
        tick(g)
    g = build()
    tick(g)
    tick(g)
    assert ex.orders["stray"]["status"] == "NEW"
    assert [x["id"] for x in g.st["SHORT"]["strays"]] == ["stray"]
    assert g.st["SHORT"]["lots"] and not handovers(tmp_path)
    ex.order_info, ex.cancel = real_info, real_cancel
    for _ in range(4):
        tick(g)
    assert ex.orders["stray"]["status"] == "CANCELED"
    assert not g.st["SHORT"]["strays"] and not g.st["SHORT"]["lots"]
    h = handovers(tmp_path)
    assert len(h) == 1 and float(h[0]["qty"]) == pytest.approx(.0001)


# ---------- W2: передача без лотов тоже оставляет событие (граница для мониторинга) — ровно одно
def test_w2_release_with_zero_lots_writes_handover_once(tmp_path):
    g, ex, px, clock, build, tick, cfg = _release_fixture(tmp_path)
    cfg["sides"], cfg["release_sides"] = ["LONG", "SHORT"], []
    tick(g)
    assert live_entries(ex, "SHORT")
    cfg["sides"], cfg["release_sides"] = ["LONG"], ["SHORT"]
    tick(g)
    assert not live_entries(ex, "SHORT")
    assert len(handovers(tmp_path)) == 1                # в том же проходе, где передача завершена
    for _ in range(2):
        tick(g)
    g = build()
    tick(g)
    h = handovers(tmp_path)
    assert len(h) == 1 and h[0]["side"] == "SHORT" and float(h[0]["qty"]) == 0.0
    assert len(g.st["SHORT"]["transfers"]) == 1 and g.st["SHORT"]["transfers"][0]["mtm"] == 0.0


# ---------- Граница владения: передача мешка не меняет заработанный итог (дополнение §3)
def _short_bag(tmp_path, mark):
    g, ex, px, clock, build, tick, cfg = _release_fixture(tmp_path)
    cfg["sides"], cfg["release_sides"] = ["SHORT"], []
    tick(g)
    px.mid = 100260.                                   # шорт-вход 100 200 исполнился
    tick(g)
    assert sum(float(x["qty"]) for x in g.st["SHORT"]["lots"]) == pytest.approx(.0012)
    px.mid = mark
    tick(g)
    return g, ex, px, clock, build, tick, cfg


@pytest.mark.parametrize("mark", [100350., 100000.])      # мешок в минусе / в плюсе
def test_transfer_does_not_change_earned_result(tmp_path, mark):
    g, ex, px, clock, build, tick, cfg = _short_bag(tmp_path, mark)
    entry = g.st["SHORT"]["lots"][0]["entry"]
    bag = -.0012 * (mark - entry)
    before = g.bot_pnl(px.mid)
    cfg["sides"], cfg["release_sides"] = [], ["SHORT"]
    tick(g)
    assert not g.st["SHORT"]["lots"]
    assert g.bot_pnl(px.mid) == pytest.approx(before, abs=1e-9)
    tr = g.st["SHORT"]["transfers"]
    assert len(tr) == 1 and tr[0]["mtm"] == pytest.approx(bag) and float(tr[0]["qty"]) == pytest.approx(.0012)
    assert tr[0]["avg"] == pytest.approx(entry) and tr[0]["mark"] == pytest.approx(mark)
    assert f"${before:+.2f}" in g.card(px.mid)
    g = build()                                        # рестарт и повторные проходы — итог тот же
    tick(g)
    px.mid = mark + 500.                               # дальше мешок оператора, не бота
    tick(g)
    assert g.bot_pnl(px.mid) == pytest.approx(before, abs=1e-9)
    assert len(handovers(tmp_path)) == 1 and len(g.st["SHORT"]["transfers"]) == 1


def test_transfer_of_winning_bag_does_not_trip_daily_stop(tmp_path):
    """Дневной стоп считает тот же bot_pnl: передача мешка в плюсе не выглядит дневным убытком (стоп в живом конфиге
    выключен — здесь включён только в тестовом конфиге)."""
    g, ex, px, clock, build, tick, cfg = _short_bag(tmp_path, 100000.)
    cfg["daily_loss_stop_usd"] = .1
    clock["t"] += 86400                                 # новые сутки: начало дня — уже с мешком в плюсе
    cfg["sides"], cfg["release_sides"] = [], ["SHORT"]
    tick(g)
    assert not g.st["SHORT"]["lots"] and not g.st["halted"]


def test_transfer_crash_before_journal_is_not_repeated(tmp_path):
    g, ex, px, clock, build, tick, cfg = _short_bag(tmp_path, 100350.)
    before = g.bot_pnl(px.mid)
    original = g._journal

    def crash(rec):
        if rec.get("kind") == HAND:
            raise RuntimeError("simulated crash")
        return original(rec)
    g._journal = crash
    cfg["sides"], cfg["release_sides"] = [], ["SHORT"]
    with pytest.raises(RuntimeError, match="simulated crash"):
        tick(g)
    g = build()
    tick(g)
    tick(g)
    assert g.bot_pnl(px.mid) == pytest.approx(before, abs=1e-9)
    assert len(g.st["SHORT"]["transfers"]) == 1 and len(handovers(tmp_path)) == 1


def test_transfer_crash_on_state_save_is_not_double_journaled(tmp_path):
    """Сбой записи учёта сразу после очистки лотов: передача не должна попасть в журнал дважды (учёт — до журнала)."""
    g, ex, px, clock, build, tick, cfg = _short_bag(tmp_path, 100350.)
    before = g.bot_pnl(px.mid)
    real_save = g.save
    fired = []

    def crash_save():
        if not g.st["SHORT"]["lots"] and not fired:
            fired.append(1)
            raise OSError("simulated disk failure")
        return real_save()
    g.save = crash_save
    cfg["sides"], cfg["release_sides"] = [], ["SHORT"]
    with pytest.raises(OSError, match="simulated disk failure"):
        tick(g)
    g = build()
    tick(g)
    tick(g)
    assert len(handovers(tmp_path)) == 1 and len(g.st["SHORT"]["transfers"]) == 1
    assert g.bot_pnl(px.mid) == pytest.approx(before, abs=1e-9)


def test_transfer_from_old_journal_is_migrated_once(tmp_path):
    g, ex, px, clock, build, tick, cfg = _release_fixture(tmp_path)
    g.st["SHORT"]["realized"], g.st["SHORT"]["fees"] = 2.0, .5
    g.st["day"] = eg.datetime.fromtimestamp(clock["t"], eg.timezone.utc).strftime("%Y-%m-%d")
    g.st["day_start_pnl"] = 1.0
    g.save()
    day_result_before = (2.0 - .5) - 1.0                     # итог старой формулы минус начало дня
    st = disk(tmp_path)
    for k in ("transferred_mtm", "transfers"):                # учёт в формате до 13.10
        st["SHORT"].pop(k, None)
    (tmp_path / "st.json").write_text(json.dumps(st), encoding="utf-8")
    rec = {"ts": "2026-10-12T10:00:00+00:00", "dry": False, "side": "SHORT", "kind": HAND, "qty": "0.0012",
           "avg": 100200.0, "mark": 100350.0, "bag": -5.0, "lots": 1}
    (tmp_path / "journal.jsonl").write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
    g = build()
    assert g.bot_pnl(px.mid) == pytest.approx(2.0 - .5 - 5.0)
    # дневной стоп считает тот же итог: миграция сдвигает начало дня на тот же мешок — дневной результат не прыгает
    assert g.bot_pnl(px.mid) - g.st["day_start_pnl"] == pytest.approx(day_result_before)
    tick(g)
    g = build()
    tick(g)
    assert g.bot_pnl(px.mid) == pytest.approx(2.0 - .5 - 5.0)              # не удвоено
    assert len(g.st["SHORT"]["transfers"]) == 1


def test_fresh_state_does_not_import_old_journal_transfers(tmp_path):
    g, ex, px, clock, build, tick, cfg = _release_fixture(tmp_path)
    rec = {"ts": "2026-10-12T10:00:00+00:00", "side": "SHORT", "kind": HAND, "qty": "0.0012", "bag": -5.0}
    (tmp_path / "journal.jsonl").write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
    g = build()                                        # холостой учёт удаляется при старте — журнал старый
    assert g.bot_pnl(px.mid) == pytest.approx(0.0)


# ---------- Метка живости прохода для мониторинга
def test_liveness_marks_success_only_after_full_tick(tmp_path):
    g, ex, px, clock, regime, build, tick, cfg = fixture(tmp_path)
    assert disk(tmp_path)["last_tick_ok_ts"] == ts_eq(clock["t"])
    ok0 = clock["t"]

    def fail_side(*a, **kw):
        raise TimeoutError("synthetic later-in-tick failure")
    g._side = fail_side
    for _ in range(3):
        with pytest.raises(TimeoutError):
            tick(g)
    st = disk(tmp_path)
    assert st["last_tick_ok_ts"] == ts_eq(ok0)                    # падения успех не освежают
    err = st["last_tick_error"]
    assert err["ts"] == ts_eq(clock["t"]) and err["phase"] == "side:LONG" and "synthetic" in err["err"]
    g = build()
    tick(g)
    assert disk(tmp_path)["last_tick_ok_ts"] == ts_eq(clock["t"])


def test_liveness_unknown_detail_is_not_success(tmp_path):
    g, ex, px, clock, regime, build, tick, cfg = fixture(tmp_path)
    ok0 = clock["t"]
    tp_id = g.st["LONG"]["lots"][0]["tp_order"]["id"]
    restore = hide(ex, tp_id, {})
    tick(g)
    tick(g)
    st = disk(tmp_path)
    assert st["last_tick_ok_ts"] == ts_eq(ok0)                    # сопровождение неясно — не «ок»
    assert st["last_tick_error"]["phase"] == "side:LONG" and tp_id in st["last_tick_error"]["err"]
    restore()
    tick(g)
    assert disk(tmp_path)["last_tick_ok_ts"] == ts_eq(clock["t"])


@pytest.mark.parametrize("broken", ["user_trades", "place_limit"])
def test_liveness_swallowed_exchange_failure_is_not_success(tmp_path, broken):
    """Сбой запроса, который проход глотает (комиссия не прочитана, исход постановки неизвестен), — не «успешный
    проход»: метка успеха не освежается, причина — в last_tick_error; без сбоя успех возвращается."""
    g, ex, px, clock, regime, build, tick, cfg = fixture(tmp_path)
    ok0 = disk(tmp_path)["last_tick_ok_ts"]
    real = getattr(ex, broken)

    def boom(*a, **kw):
        raise TimeoutError(f"synthetic {broken} failure")
    setattr(ex, broken, boom)
    px.mid = g.st["LONG"]["lots"][0]["tp"] + 1.      # тейк исполняется → комиссия и перестановка входа
    tick(g)
    st = disk(tmp_path)
    assert st["last_tick_ok_ts"] == ts_eq(ok0)
    assert st["last_tick_error"]["ts"] == ts_eq(clock["t"]) and broken in st["last_tick_error"]["err"]
    setattr(ex, broken, real)
    clock["t"] += eg.PENDING_TTL
    for _ in range(3):
        tick(g)
    assert disk(tmp_path)["last_tick_ok_ts"] == ts_eq(clock["t"])


def test_truncated_open_orders_fails_tick_without_cancels(tmp_path):
    g, ex, px, clock, regime, build, tick, cfg = fixture(tmp_path)
    cancels = []
    real_cancel = ex.cancel

    def spy(oid):
        cancels.append(oid)
        return real_cancel(oid)
    ex.cancel = spy

    def truncated(sym):
        raise wc.WeexError("open_orders: 10 полных страниц — список неполон")
    ex.open_orders = truncated
    with pytest.raises(wc.WeexError):
        tick(g)
    assert cancels == []
    assert disk(tmp_path)["last_tick_error"]["phase"] == "open_orders"


# ---------- Клиент: 10 полных страниц — не «весь список»
class PagedClient(wc.WeexClient):
    def __init__(self, pages: int, last: int):
        super().__init__(creds=("k", "s", "p"))
        self.pages, self.last, self.calls = pages, last, []

    def get(self, base, path, params=None):
        self.calls.append((path, dict(params or {})))
        n = len(self.calls)
        size = 100 if n < self.pages else self.last
        return [{"orderId": f"{n}-{i}", "clientOrderId": "x"} for i in range(size)]


@pytest.mark.parametrize("method", ["open_orders", "open_algo_orders"])
def test_client_open_lists_raise_when_page_cap_reached(method):
    c = PagedClient(pages=10 ** 6, last=100)            # страницы всегда полные
    with pytest.raises(wc.WeexError):
        getattr(c, method)("BTCUSDT")
    assert len(c.calls) <= 10
    c = PagedClient(pages=3, last=7)                    # полный ответ — 2 полные страницы и хвост
    rows = getattr(c, method)("BTCUSDT")
    assert len(rows) == 207 and len(c.calls) == 3


class ErrorPageClient(wc.WeexClient):
    def __init__(self):
        super().__init__(creds=("k", "s", "p"))

    def get(self, base, path, params=None):
        return {"code": "40001", "msg": "synthetic error object instead of list"}


@pytest.mark.parametrize("method", ["open_orders", "open_algo_orders"])
def test_client_open_lists_reject_non_list_page(method):
    """Объект ошибки вместо списка — не «список из ключей ответа»."""
    with pytest.raises(wc.WeexError):
        getattr(ErrorPageClient(), method)("BTCUSDT")
