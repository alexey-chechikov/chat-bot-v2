"""Разбор GPT 15.10 (docs/WEEX_GPT_REVIEW_AND_MANUAL_STRATEGIES_2026-10-15.md §1; пробы test_audit_alert_delivery.py
из WEEX_GPT_REVIEW_REPRO_2026-10-15.zip прочитаны, не запускались):
P1 — null/{} истории ордеров («or []») считались полной пустой историей: после TTL намерение стиралось, и при ордере,
     который принят, но не виден в списке открытых, вставал ВТОРОЙ живой вход. Теперь негодный ответ — исход неизвестен
     (намерение на диске, новых ордеров стороны нет); годный пустой ответ — не доказательство с одного раза.
P2 — передача стороны: запись журнала прошла, снятие флага в учёте — нет → после рестарта вторая запись «передано
     оператору». Теперь event_id в учёте и журнале, дозапись идемпотентна.
P2 — доставка: метка интервала эскалации ставилась до отправки, сбой Telegram глотался → первое сообщение терялось и
     повтор шёл через час. Теперь alert_outbox с повторами 1/2/5/10 мин, интервал — от удачной доставки.
Биржа и Telegram — имитаторы; проверка логики, не замер реального WEEX. Каждый проход в стенде live_grid — новый Grid с
диска (как loop.py), то есть каждый проход — «рестарт»."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from services.weex_api import client as wc
from services.weex_grid import engine as eg
from services.weex_grid import loop as lp
from tests.services.weex_grid.test_weex_gpt1013 import HAND, _short_bag, disk, handovers, live_entries
from tests.services.weex_grid.test_weex_gpt1014 import live_grid, stuck
from tests.services.weex_grid.test_weex_regime_gpt import bot_markets, fixture

NOT_REACHED = "считаю не дошедшим"


# ======================================================================================================== P1
class LostReplyExchange(eg.DryExchange):
    """Ответ на POST потерян (таймаут): lose='after' — биржа ордер ПРИНЯЛА; 'before' — ордер не дошёл."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.lose = None

    def place_limit(self, *a, **kw):
        mode, self.lose = self.lose, None
        if mode == "before":
            raise TimeoutError("synthetic: POST timeout, order not accepted")
        r = super().place_limit(*a, **kw)
        if mode == "after":
            raise TimeoutError("synthetic: POST timeout after the exchange accepted the order")
        return r


def lost_entry(tmp_path: Path, mode: str):
    """Стоящий вход переставляется за ценой; ответ на новый POST потерян. → (стенд, номер принятого ордера|None, pending)."""
    t = live_grid(tmp_path, LostReplyExchange, filled=False)
    assert len(live_entries(t.ex)) == 1
    t.ex.lose = mode
    t.px.mid = 100300.                                   # вход 99 800 отстал на 0.5% — снять и поставить новый
    t.g = t.tick()
    s = t.g.st["LONG"]
    assert s["pending"] and s["pending"]["kind"] == "e" and s["entry"] is None
    ids = live_entries(t.ex)
    if mode == "after":
        assert len(ids) == 1 and t.ex.orders[ids[0]]["clientOrderId"] == s["pending"]["cid"]
        return t, ids[0], dict(s["pending"])
    assert ids == []
    return t, None, dict(s["pending"])


def hide_from_open(t, oid: str) -> None:
    """Принятый ордер не виден в списке открытых (задержка/неполнота списка у биржи)."""
    real_open = t.ex.open_orders
    t.ex.open_orders = lambda sym: [o for o in real_open(sym) if str(o["orderId"]) != oid]


@pytest.mark.parametrize("bad_history", [None, {}], ids=["null", "empty_object"])
def test_p1_unknown_history_keeps_pending_and_single_live_entry(tmp_path, bad_history):
    """POST timeout → история null/{} → старый ордер живой, но не в списке открытых → 15 мин проходов с рестартом
    каждого → по-прежнему ровно один живой вход и то же намерение на диске; оператор узнаёт о сбое; история снова годна
    → тот же ордер привязан как вход, второго нет. На 17c970b: после TTL намерение стёрто, второй вход."""
    t, lost_id, p = lost_entry(tmp_path, "after")
    hide_from_open(t, lost_id)
    t.ex.order_history = lambda *a, **kw: bad_history
    t.sends.clear()
    for _ in range(15 * 6):
        t.g = t.tick()
        assert live_entries(t.ex) == [lost_id]             # ни одного второго входа ни на одном проходе
    st = disk(tmp_path)["LONG"]
    assert st["pending"]["cid"] == p["cid"] and st["entry"] is None and not st["pending"].get("absent")
    assert not any(NOT_REACHED in m for m in t.sends)
    assert any("без чистого прохода" in m and p["cid"] in m for m in t.sends)   # сбой поиска поднят сообщением
    del t.ex.order_history                               # история снова отвечает списком — ордер в ней есть
    for _ in range(3):
        t.g = t.tick()
    s = t.g.st["LONG"]
    assert live_entries(t.ex) == [lost_id] and s["entry"]["id"] == lost_id and not s["pending"]


def test_p1_valid_empty_history_once_is_not_proof_lagging_order_adopted(tmp_path):
    """Годный пустой список истории в первом поиске после TTL (история запаздывает) — не «не дошёл»: следующий поиск
    находит принятый ордер, он привязывается, второго входа нет. На 17c970b: один пустой ответ после TTL → второй вход."""
    t, lost_id, p = lost_entry(tmp_path, "after")
    hide_from_open(t, lost_id)
    real_hist = t.ex.order_history
    lag_until = p["t"] + eg.PENDING_TTL + 15             # первый поиск после TTL — ещё пусто
    t.ex.order_history = lambda *a, **kw: [] if t.clock["t"] < lag_until else real_hist(*a, **kw)
    for _ in range(30):
        t.g = t.tick()
        assert live_entries(t.ex) == [lost_id]
    s = t.g.st["LONG"]
    assert s["entry"]["id"] == lost_id and not s["pending"]
    assert not any(NOT_REACHED in m for m in t.sends)


def test_p1_absence_needs_two_spaced_valid_reads_then_one_new_entry(tmp_path):
    """Ордер действительно не дошёл, история годна и пуста: на первом поиске после TTL намерение ещё живо и нового
    входа нет; после второго годного поиска (≥ PENDING_RECHECK спустя) и пустых сделок окна — «не дошёл», ровно один
    новый вход, сообщение одно. На 17c970b: стирание и новый вход уже на первом поиске после TTL."""
    t, _, p = lost_entry(tmp_path, "before")
    while t.clock["t"] < p["t"] + eg.PENDING_TTL:
        t.g = t.tick()
    s = disk(tmp_path)["LONG"]
    assert s["pending"] and s["pending"]["cid"] == p["cid"] and live_entries(t.ex) == []
    assert len(s["pending"]["absent"]) == 1
    for _ in range(4):                                   # 40 с: второй годный поиск через 30 с после первого
        t.g = t.tick()
    s = t.g.st["LONG"]
    assert not s["pending"] and len(live_entries(t.ex)) == 1 and s["entry"]["cid"] != p["cid"]
    assert sum(NOT_REACHED in m for m in t.sends) == 1
    for _ in range(5):
        t.g = t.tick()
    assert len(live_entries(t.ex)) == 1


def test_p1_filled_lost_order_missing_from_history_found_by_window_trades(tmp_path):
    """Принятый ордер сразу исполнился (в открытых его нет), а история так его и не показала (годный пустой список):
    перед «не дошёл» — сделки окна → деталь → clientOrderId; исполнение учтено лотом этого ордера, второй вход не
    ставится поверх. На 17c970b: после TTL «не дошёл», исполнение 0.0012 осталось без учёта и без тейка."""
    t, lost_id, p = lost_entry(tmp_path, "after")
    t.ex.order_history = lambda *a, **kw: []
    t.px.mid = 100000.                                   # стакан пересёк вход 100 099.4 — исполнен
    for _ in range(25):
        t.g = t.tick()
    s = t.g.st["LONG"]
    assert t.ex.orders[lost_id]["status"] == "FILLED"
    assert [l["parent"] for l in s["lots"]] == [lost_id] and float(s["lots"][0]["qty"]) == pytest.approx(.0012)
    assert not s["pending"] and not any(NOT_REACHED in m for m in t.sends)
    journal = [json.loads(x) for x in (tmp_path / "journal.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["order_id"] for r in journal if r.get("kind") == "вход"] == [lost_id]


def test_p1_bad_read_between_valid_reads_restarts_the_count(tmp_path):
    """Подтверждения отсутствия — только подряд: негодный ответ между двумя годными пустыми обнуляет счёт."""
    t, _, p = lost_entry(tmp_path, "before")
    while t.clock["t"] < p["t"] + eg.PENDING_TTL:
        t.g = t.tick()
    pend = disk(tmp_path)["LONG"]["pending"]
    assert pend and len(pend.get("absent") or []) == 1
    t.ex.order_history = lambda *a, **kw: None
    t.g = t.tick()
    pend = disk(tmp_path)["LONG"]["pending"]
    assert pend and not pend.get("absent")
    del t.ex.order_history
    for _ in range(3):                                   # 30 с: второй годный поиск снова лишь первый подряд
        t.g = t.tick()
    assert disk(tmp_path)["LONG"]["pending"] and live_entries(t.ex) == []


class _GetClient(wc.WeexClient):
    def __init__(self, resp):
        super().__init__(creds=("k", "s", "p"))
        self.resp = resp

    def get(self, base, path, params=None):
        return self.resp


BAD_LISTS = [None, {}, {"code": "40001", "msg": "synthetic error object"}]


@pytest.mark.parametrize("resp", BAD_LISTS, ids=["null", "empty_object", "error_object"])
def test_p1_client_history_rejects_non_list(resp):
    """Клиент: история ордеров — только массив (документация WEEX; чтение со счёта 13.10). null/{}/объект ошибки →
    WeexIncomplete, а не «пустая полная история». На 17c970b: null и {} → [], объект ошибки отдавался как есть."""
    with pytest.raises(wc.WeexIncomplete):
        _GetClient(resp).order_history("BTCUSDT", start_ms=1, end_ms=2)
    row = {"orderId": 900000000000000011, "clientOrderId": "b7gBLe1", "status": "NEW", "executedQty": "0",
           "symbol": "BTCUSDT", "positionSide": "LONG", "time": 1797000000000, "updateTime": 1797000060000}
    assert _GetClient([row]).order_history("BTCUSDT") == [row]
    assert _GetClient([]).order_history("BTCUSDT") == []


@pytest.mark.parametrize("method", ["open_orders", "open_algo_orders"])
@pytest.mark.parametrize("resp", [None, {}], ids=["null", "empty_object"])
def test_p1_client_open_lists_reject_null_and_empty_object(method, resp):
    """Список открытых: null/{} — не «открытых нет» (проба GPT test_null_open_orders_is_still_accepted_as_empty)."""
    with pytest.raises(wc.WeexIncomplete):
        getattr(_GetClient(resp), method)("BTCUSDT")
    assert getattr(_GetClient([]), method)("BTCUSDT") == []


def test_p1_engine_rejects_non_list_open_orders_before_decisions(tmp_path):
    """Сетка: список открытых {} (имитатор, минуя клиент) — не «открытых нет»: проход прерывается до решений; ни отмен,
    ни постановок. На 17c970b: {} принимался как пустой полный список."""
    t = live_grid(tmp_path)
    before = {k: dict(v) for k, v in t.ex.orders.items()}
    t.ex.open_orders = lambda sym: {}
    with pytest.raises(wc.WeexIncomplete):
        t.tick()
    assert {k: dict(v) for k, v in t.ex.orders.items()} == before
    err = disk(tmp_path)["last_tick_error"]
    assert err["fatal"] and err["phase"] == "open_orders"


def test_p1_guard_flatten_with_null_history_finds_market_by_trades(tmp_path):
    """Защитный (на 17c970b тоже зелёный): рыночное закрытие с потерянным ответом при истории null — проход не падает,
    market найден по сделкам окна, учтён один раз, второго market нет."""
    g, ex, px, clock, regime, build, tick, cfg = fixture(tmp_path)
    real = ex.place_market

    def lost(*a, **kw):
        real(*a, **kw)
        raise TimeoutError("accepted and filled, response lost")
    ex.place_market = lost
    regime["up"] = False
    tick(g)
    ex.place_market = real
    ex.order_history = lambda *a, **kw: None
    for _ in range(3):
        g = build()
        tick(g)
    assert len(bot_markets(ex)) == 1 and not g.st["LONG"]["lots"] and not g.st["LONG"].get("flatten")
    closes = [json.loads(x) for x in (tmp_path / "journal.jsonl").read_text(encoding="utf-8").splitlines()]
    assert sum(1 for r in closes if r.get("kind") == "закрытие по режиму") == 1
    assert (disk(tmp_path).get("last_tick_error") or {}).get("fatal") is not True


# ======================================================================================================== P2 передача
@pytest.mark.parametrize("fault", ["crash_after_append", "state_save_fails_after_append"])
def test_p2_handover_appended_then_state_not_cleared_two_restarts_one_event(tmp_path, fault):
    """Запись «передано оператору» в журнал прошла, а снятие флага handover_unjournaled на диске — нет (сбой процесса
    сразу после записи / сбой записи учёта) → два рестарта → в журнале ОДНО событие с тем же event_id, что и в учёте,
    одна передача, итог не изменился. На 17c970b: 2 записи журнала / 1 передача в учёте."""
    g, ex, px, clock, build, tick, cfg = _short_bag(tmp_path, 100350.)
    before = g.bot_pnl(px.mid)
    fired = []
    if fault == "crash_after_append":
        original = g._journal

        def append_then_crash(rec):
            original(rec)
            if rec.get("kind") == HAND:
                raise RuntimeError("synthetic crash after journal append")
        g._journal = append_then_crash
    else:
        real_save = g.save

        def save_fails():
            if not g.st["SHORT"].get("handover_unjournaled") and handovers(tmp_path) and not fired:
                fired.append(1)
                raise OSError("synthetic state write failure after journal append")
            return real_save()
        g.save = save_fails
    cfg["sides"], cfg["release_sides"] = [], ["SHORT"]
    with pytest.raises((RuntimeError, OSError), match="synthetic"):
        tick(g)
    assert len(handovers(tmp_path)) == 1 and disk(tmp_path)["SHORT"].get("handover_unjournaled")
    for _ in range(2):                                   # два рестарта
        g = build()
        tick(g)
    h = handovers(tmp_path)
    st = disk(tmp_path)["SHORT"]
    assert len(h) == 1
    assert len(st["transfers"]) == 1 and not st.get("handover_unjournaled")
    assert h[0]["event_id"] and h[0]["event_id"] == st["transfers"][0]["event_id"]
    assert g.bot_pnl(px.mid) == pytest.approx(before, abs=1e-9)


# ======================================================================================================== P2 доставка
class Flaky:
    """Отправитель Telegram: первые fail попыток не доставлены (исключение или False), дальше — доставлено (None, как
    list.append)."""

    def __init__(self, clock, fail: int, mode: str = "raise"):
        self.clock, self.fail, self.mode = clock, fail, mode
        self.attempts: list[float] = []
        self.delivered: list[tuple[float, str]] = []

    def __call__(self, text):
        self.attempts.append(self.clock["t"])
        if len(self.attempts) <= self.fail:
            if self.mode == "raise":
                raise TimeoutError("synthetic Telegram delivery failure")
            return False
        self.delivered.append((self.clock["t"], text))
        return None


def run_with(t, send, seconds: int) -> None:
    """Проходы по 10 с, каждый — новый Grid с диска (рестарт) с заданным отправителем."""
    for _ in range(seconds // 10):
        t.clock["t"] += 10
        g = t.build()
        g.send = send
        g.tick()
        t.g = g


def stuck_tp(tmp_path):
    t = live_grid(tmp_path)
    tp = t.g.st["LONG"]["lots"][0]["tp_order"]["id"]
    t.ex.orders[tp]["status"] = "CANCELED"              # снят вне бота, деталь не читается
    stuck(t.ex, tp, "empty")
    return t, tp


@pytest.mark.parametrize("mode", ["raise", "false"])
def test_p2_failed_first_unknown_alert_is_retried_then_hourly_from_success(tmp_path, mode):
    """Первая доставка эскалации неудачна (исключение / False) → повтор через 1 мин, доставлено; дальше часовой
    интервал — от удачной доставки; повторных проходов-рестартов без дубля. На 17c970b: метка ставилась до отправки,
    сбой глотался — 0 доставок за 30 мин, повтор только через час."""
    t, tp = stuck_tp(tmp_path)
    send = Flaky(t.clock, fail=1, mode=mode)
    run_with(t, send, 10 * 60)
    assert len(send.attempts) == 2 and len(send.delivered) == 1
    first, ok = send.attempts
    assert ok - first == 60.
    assert tp in send.delivered[0][1] and "замену не ставлю" in send.delivered[0][1]
    st = disk(tmp_path)
    assert st["unknown_alert_ts"] == pytest.approx(ok) and "alert_outbox" not in st
    assert st["alert_delivered"]["unknown"]["attempts"] == 2
    left = int(ok + eg.UNKNOWN_ALERT_EVERY - t.clock["t"]) - 10
    run_with(t, send, left)                              # до часа от доставки — тихо
    assert len(send.delivered) == 1
    run_with(t, send, 20)                                # час от УДАЧНОЙ доставки — повтор
    assert len(send.delivered) == 2 and send.delivered[1][0] - ok == pytest.approx(eg.UNKNOWN_ALERT_EVERY, abs=10)


def test_p2_undelivered_alert_backoff_is_bounded(tmp_path):
    """Telegram недоступен 40 мин: попытки через 1, 2, 5, затем каждые 10 мин (не каждый проход и не раз в час);
    после восстановления — одна доставка, ожидание снято."""
    t, tp = stuck_tp(tmp_path)
    send = Flaky(t.clock, fail=10 ** 6)
    run_with(t, send, 45 * 60)
    gaps = [b - a for a, b in zip(send.attempts, send.attempts[1:])]
    assert gaps[:4] == [60., 120., 300., 600.] and all(g == 600. for g in gaps[3:])
    assert len(send.attempts) >= 6 and send.delivered == []
    rec = disk(tmp_path)["alert_outbox"]["unknown"]
    assert rec["attempts"] == len(send.attempts) and rec["last_attempt"] == pytest.approx(send.attempts[-1])
    assert "unknown_alert_ts" not in disk(tmp_path)
    send.fail = 0
    run_with(t, send, 11 * 60)
    assert len(send.delivered) == 1 and "alert_outbox" not in disk(tmp_path)


def test_p2_failed_issue_alert_is_retried(tmp_path):
    """То же для «N мин без чистого прохода»: первая доставка упала → повтор через минуту, дальше раз в 30 мин от
    доставки. На 17c970b: метка до отправки — 30 мин тишины."""
    t = live_grid(tmp_path, stress_budget_frac=.25)

    def boom():
        raise TimeoutError("synthetic balance failure")
    t.ex.futures_balance = boom
    send = Flaky(t.clock, fail=1)
    run_with(t, send, 13 * 60)
    assert len(send.attempts) == 2 and len(send.delivered) == 1
    assert send.attempts[1] - send.attempts[0] == 60.
    assert "без чистого прохода" in send.delivered[0][1] and "баланс не прочитан" in send.delivered[0][1]
    ok = send.attempts[1]
    assert disk(tmp_path)["issue_alert_ts"] == pytest.approx(ok)
    run_with(t, send, int(ok + eg.ISSUE_ALERT_EVERY - t.clock["t"]) - 10)
    assert len(send.delivered) == 1
    run_with(t, send, 20)
    assert len(send.delivered) == 2


def test_p2_alert_dropped_when_condition_clears_before_delivery(tmp_path):
    """Сообщение ждёт доставки, а неясный ордер тем временем подтвердился — устаревшее сообщение не отправляется."""
    t, tp = stuck_tp(tmp_path)
    send = Flaky(t.clock, fail=10 ** 6)
    run_with(t, send, 6 * 60)
    assert len(send.attempts) == 1 and "unknown" in (disk(tmp_path).get("alert_outbox") or {})
    t.ex.order_info = eg.DryExchange.order_info.__get__(t.ex)
    send.fail = 0
    run_with(t, send, 5 * 60)
    assert send.delivered == [] and "alert_outbox" not in disk(tmp_path)


def test_p2_notify_reports_delivery(tmp_path):
    """_notify сообщает вызывающему результат: исключение / False — не доставлено, None/True — доставлено."""
    def g_with(send):
        return eg.Grid(eg.DryExchange(lambda: (1., 2.)), {**eg.DEFAULT}, state_path=tmp_path / "st.json",
                       journal_path=tmp_path / "j.jsonl", send_fn=send)

    def boom(text):
        raise TimeoutError("synthetic")
    assert g_with(boom)._notify("x") is False
    assert g_with(lambda text: False)._notify("x") is False
    assert g_with(lambda text: None)._notify("x") is True
    assert g_with(lambda text: True)._notify("x") is True
    assert g_with(None)._notify("x") is False


def test_p2_channel_router_send_returns_delivery_result():
    """Боевой отправитель (build_send_fn → send_with_retry) отдаёт результат: Telegram недоступен — False, доставлено
    хотя бы в один чат — True. На 17c970b: всегда None, сетка не могла узнать о недоставке."""
    from services.telegram.channel_router import build_send_fn
    app = MagicMock()
    app.allowed_chat_ids = [100]
    app.bot = MagicMock()
    with patch.dict(os.environ, {"ROUTINE_CHAT_IDS": ""}), \
            patch("services.common.silent_families.tg_muted", return_value=False), \
            patch("services.common.tg_send_with_retry.time.sleep"):
        send = build_send_fn(app, "WEEX_GRID")
        assert send("ok") is True
        app.bot.send_message.side_effect = TimeoutError("synthetic telegram timeout")
        assert send("lost") is False


def test_p2_loop_error_alert_throttle_counts_from_delivery():
    """Сообщение цикла «ошибка прохода» (раз в 30 мин): первая доставка упала — следующая ошибка шлёт снова, после
    удачной — тишина 30 мин. На 17c970b: метка до отправки — после неудачи 30 мин тишины."""
    clock = {"t": 0.}
    send = Flaky(clock, fail=1)
    r = lp.Runner(send_fn=send)
    for _ in range(3):
        r.on_error(RuntimeError("synthetic tick failure"))
    assert len(send.attempts) == 2 and len(send.delivered) == 1
