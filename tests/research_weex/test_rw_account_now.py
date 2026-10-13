"""research/weex/account_now.py — ложные «ок» из разбора GPT 13.10 (§3 Q1): свежесть файла учёта ≠ успешный
проход, нет clientOrderId ≠ ручной, null истории ≠ ноль сделок, нет записи передачи при сделках бота ≠ «не трогал»,
SMA без проверки свежести/непрерывности дневок."""
import time

import pytest

from services.weex_grid import engine as eg
from tests.research_weex.harness import (FakeClient, daily_rows, iso, make_grid, run_script, side_state,
                                         trade)

NOW = time.time()
HANDOVER = NOW - 2 * 86400
JOURNAL = [{"ts": iso(NOW - 5 * 86400), "side": "SHORT", "kind": "вход", "order_id": "e0"},
           {"ts": iso(HANDOVER), "side": "SHORT", "kind": "передано оператору", "qty": "1", "avg": 100.0,
            "mark": 100.0, "bag": 0.0, "lots": 1}]


def state(**top):
    return {"symbol": "BTCUSDT", "LONG": side_state(), "SHORT": side_state(), "halted": False,
            "last_tick_ok_ts": time.time() - 5, **top}


def run(tmp_path, monkeypatch, client=None, cfg=None, st=None, journal=None):
    make_grid(tmp_path, monkeypatch, cfg=cfg, st=state() if st is None else st,
              journal=JOURNAL if journal is None else journal)
    return run_script("account_now.py", client or FakeClient(), monkeypatch)


# ---------- контроль: всё в порядке → ок, код 0
def test_control_fresh_success_is_ok(tmp_path, monkeypatch):
    code, out = run(tmp_path, monkeypatch)
    assert code == 0, out
    assert "цикл жив" in out and "ИТОГ: ок" in out


# ---------- (a) жив ли цикл — по успешному проходу, не по mtime
def test_failing_ticks_keep_mtime_fresh_but_last_success_old_is_problem(tmp_path, monkeypatch):
    """Три падающих прохода освежают файл (_orphans сохраняет учёт до _side), а успешного прохода не было 400 с."""
    code, out = run(tmp_path, monkeypatch, st=state(last_tick_ok_ts=time.time() - 400))
    assert code == 1, out
    assert "ПРОБЛЕМА" in out and "ИТОГ: ок" not in out


def test_old_engine_without_success_key_is_not_ok(tmp_path, monkeypatch):
    st = state()
    st.pop("last_tick_ok_ts")
    code, out = run(tmp_path, monkeypatch, st=st)
    assert code == 2, out
    assert "успешность прохода не подтверждена" in out
    assert "ИТОГ: ок" not in out


def test_error_newer_than_success_is_problem(tmp_path, monkeypatch):
    st = state(last_tick_ok_ts=time.time() - 30,
               last_tick_error={"ts": time.time() - 3, "phase": "_side", "error": "TimeoutError: synthetic"})
    code, out = run(tmp_path, monkeypatch, st=st)
    assert code == 1, out
    assert "ПРОБЛЕМА" in out and "TimeoutError" in out


@pytest.mark.parametrize("fatal", [True, False])
def test_engine_error_shape_newer_than_success_is_problem_with_reason(tmp_path, monkeypatch, fatal):
    """Форма записи движка (пакет WP1): {ts, phase, err, fatal}; fatal false — проход без исключения, но с неясной
    деталью ордера, успех не отмечен. Причина должна быть видна в выводе."""
    st = state(last_tick_ok_ts=time.time() - 30,
               last_tick_error={"ts": time.time() - 3, "phase": "tps", "fatal": fatal,
                                "err": "TimeoutError: synthetic-err"})
    code, out = run(tmp_path, monkeypatch, st=st)
    assert code == 1, out
    assert "ПРОБЛЕМА" in out and "synthetic-err" in out and "tps" in out


def test_error_older_than_success_is_ok(tmp_path, monkeypatch):
    st = state(last_tick_ok_ts=time.time() - 5, last_tick_error={"ts": time.time() - 100, "error": "old"})
    code, out = run(tmp_path, monkeypatch, st=st)
    assert code == 0, out


def test_success_between_60_and_180s_is_recheck_not_ok(tmp_path, monkeypatch):
    code, out = run(tmp_path, monkeypatch, st=state(last_tick_ok_ts=time.time() - 120))
    assert code == 2, out
    assert "перепроверить" in out and "ИТОГ: ок" not in out


# ---------- (b) нет clientOrderId у совпавшего orderId — владелец неизвестен, не «ручной»
@pytest.mark.parametrize("info", [{"orderId": "o1"}, {"orderId": "o1", "clientOrderId": None},
                                  {"orderId": "o1", "clientOrderId": ""}])
def test_missing_or_null_cid_is_unknown_owner(tmp_path, monkeypatch, info):
    c = FakeClient(trades=[trade("t1", "o1", at=NOW - 86400)], infos={"o1": info})
    code, out = run(tmp_path, monkeypatch, client=c)
    assert code == 2, out
    assert "ИТОГ: ок" not in out


def test_missing_cid_but_order_in_bot_registry_counts_as_bot_after_handover(tmp_path, monkeypatch):
    """Тейк бота (курсор в order_fills) исполнился после передачи; деталь без clientOrderId → сделка бота → ПРОБЛЕМА."""
    st = state()
    st["SHORT"]["order_fills"] = {"o9": {"filled": 0.0, "val": 0.0, "t": NOW - 3 * 86400}}
    c = FakeClient(trades=[trade("t1", "o9", side="BUY", at=NOW - 86400)], infos={"o9": {"orderId": "o9"}})
    code, out = run(tmp_path, monkeypatch, client=c, st=st)
    assert code == 1, out
    assert "ПРОБЛЕМА" in out


def test_manual_trade_after_handover_is_ok(tmp_path, monkeypatch):
    c = FakeClient(trades=[trade("t1", "m1", side="BUY", at=NOW - 86400)],
                   infos={"m1": {"orderId": "m1", "clientOrderId": "web123"}})
    code, out = run(tmp_path, monkeypatch, client=c)
    assert code == 0, out


# ---------- пограничная секунда: запись передачи — с точностью до секунды
def test_bot_fill_in_handover_second_booked_before_handover_is_not_after(tmp_path, monkeypatch):
    """Тейк исполнился в ту же секунду, что и запись передачи, и учтён журналом до неё — это не «после передачи»."""
    journal = [JOURNAL[0], {"ts": iso(HANDOVER), "side": "SHORT", "kind": "тейк", "order_id": "tpb"}, JOURNAL[1]]
    c = FakeClient(trades=[trade("t1", "tpb", side="BUY", at=HANDOVER)],
                   infos={"tpb": {"orderId": "tpb", "clientOrderId": "b7gBSt17000000003"}})
    code, out = run(tmp_path, monkeypatch, client=c, journal=journal)
    assert code == 0, out


def test_bot_fill_in_handover_second_not_booked_is_problem(tmp_path, monkeypatch):
    c = FakeClient(trades=[trade("t1", "tpx", side="BUY", at=HANDOVER)],
                   infos={"tpx": {"orderId": "tpx", "clientOrderId": "b7gBSt17000000004"}})
    code, out = run(tmp_path, monkeypatch, client=c)
    assert code == 1, out


# ---------- (c) история сделок null/не список — ошибка чтения, не ноль
@pytest.mark.parametrize("resp", [None, {"code": "40001", "msg": "busy"}])
def test_null_or_non_list_history_is_read_error(tmp_path, monkeypatch, resp):
    code, out = run(tmp_path, monkeypatch, client=FakeClient(trades=resp))
    assert code == 2, out
    assert "ИТОГ: ок" not in out


# ---------- (d) нет записи передачи, а сделки бота на стороне есть — результат неизвестен
def test_no_handover_record_with_bot_fills_is_unknown(tmp_path, monkeypatch):
    journal = [{"ts": iso(NOW - 5 * 86400), "side": "LONG", "kind": "вход", "order_id": "x"}]
    c = FakeClient(trades=[trade("t1", "o1", at=NOW - 86400)],
                   infos={"o1": {"orderId": "o1", "clientOrderId": "b7gBSe17000000001"}})
    code, out = run(tmp_path, monkeypatch, client=c, journal=journal)
    assert code == 2, out
    assert "неизвест" in out and "бот сторону не трогал" not in out


def test_no_handover_record_without_bot_fills_is_ok(tmp_path, monkeypatch):
    journal = [{"ts": iso(NOW - 5 * 86400), "side": "LONG", "kind": "вход", "order_id": "x"}]
    code, out = run(tmp_path, monkeypatch, journal=journal)
    assert code == 0, out


def test_released_side_without_any_journal_is_not_confirmed(tmp_path, monkeypatch):
    """Журнала нет — начала истории нет, сделки бота на переданной стороне не проверены: это не «не трогал»."""
    c = FakeClient(trades=[trade("t1", "o1", at=NOW - 86400)],
                   infos={"o1": {"orderId": "o1", "clientOrderId": "b7gBSe17000000001"}})
    code, out = run(tmp_path, monkeypatch, client=c, journal=[])
    assert code == 2, out
    assert "бот сторону не трогал" not in out and "ИТОГ: ок" not in out


def test_open_order_on_released_side_without_cid_is_unknown(tmp_path, monkeypatch):
    """Открытый ордер на переданной стороне без clientOrderId и не из реестра бота — владелец неизвестен."""
    o = {"orderId": "x1", "positionSide": "SHORT", "side": "BUY", "price": "90", "origQty": "1"}
    code, out = run(tmp_path, monkeypatch, client=FakeClient(opens=[o]))
    assert code == 2, out
    assert "ИТОГ: ок" not in out


def test_open_order_on_released_side_without_cid_but_in_registry_is_problem(tmp_path, monkeypatch):
    st = state()
    st["SHORT"]["strays"] = [{"id": "x2", "cid": "b7gBSt1"}]
    o = {"orderId": "x2", "positionSide": "SHORT", "side": "BUY", "price": "90", "origQty": "1"}
    code, out = run(tmp_path, monkeypatch, client=FakeClient(opens=[o]), st=st)
    assert code == 1, out


def test_manual_open_order_on_released_side_is_ok(tmp_path, monkeypatch):
    o = {"orderId": "m5", "clientOrderId": "5f0c2b8e-uuid", "positionSide": "SHORT", "side": "BUY", "price": "90",
         "origQty": "1"}
    code, out = run(tmp_path, monkeypatch, client=FakeClient(opens=[o]))
    assert code == 0, out


def test_side_in_both_sides_and_release_sides_is_not_released(tmp_path, monkeypatch):
    """Движок не передаёт сторону, которая есть в sides; её тейк — не «ордер бота на переданной стороне»."""
    tp = {"orderId": "tp1", "clientOrderId": "b7gBSt17000000002", "positionSide": "SHORT", "side": "BUY",
          "price": "99", "origQty": "1", "executedQty": "0", "reduceOnly": True}
    code, out = run(tmp_path, monkeypatch, client=FakeClient(opens=[tp]),
                    cfg={"sides": ["LONG", "SHORT"], "release_sides": ["SHORT"]})
    assert code == 0, out


# ---------- (e) SMA: та же проверка дневок, что у engine.regime_up
def test_stale_daily_candles_are_problem_not_long(tmp_path, monkeypatch):
    monkeypatch.setattr(eg, "_fetch_daily", lambda sym, n: daily_rows(last_closed_days_ago=101))
    code, out = run(tmp_path, monkeypatch, cfg={"regime_sma": 100})
    assert code == 1, out
    assert "режим ЛОНГ" not in out and "ПРОБЛЕМА" in out


def test_missing_day_in_daily_candles_is_problem(tmp_path, monkeypatch):
    monkeypatch.setattr(eg, "_fetch_daily", lambda sym, n: daily_rows(drop=60))
    code, out = run(tmp_path, monkeypatch, cfg={"regime_sma": 100})
    assert code == 1, out
    assert "режим ЛОНГ" not in out


def test_valid_daily_candles_show_regime(tmp_path, monkeypatch):
    monkeypatch.setattr(eg, "_fetch_daily", lambda sym, n: daily_rows())
    code, out = run(tmp_path, monkeypatch, cfg={"regime_sma": 100})
    assert code == 0, out
    assert "режим ЛОНГ" in out
