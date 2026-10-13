"""research/weex/orphan_check.py — разбор GPT 13.10 §3 Q2: отсутствие тейка среди открытых — повод спросить деталь,
а не доказательство позиции без выхода. Находки — только «остаток без TP» и «неизвестен»; скрипт ордера не ставит."""
import pytest

from tests.research_weex.harness import FakeClient, make_grid, run_script, side_state

TP = {"id": "tp1", "cid": "b7gBLt17000000001", "price": 101.0, "qty": "1"}


def lot_state(qty="1", tp_order=None):
    lot = {"entry": 100.0, "qty": qty, "tp": 101.0, "t": 1.0, "tp_order": dict(TP) if tp_order is None else tp_order}
    return {"symbol": "BTCUSDT", "LONG": side_state(lots=[lot]), "SHORT": side_state(), "halted": False}


def detail(status, executed="0", orig="1", **kw):
    return {"orderId": "tp1", "clientOrderId": TP["cid"], "status": status, "executedQty": executed,
            "origQty": orig, "positionSide": "LONG", "side": "SELL", "reduceOnly": True, "price": "101", **kw}


def run(tmp_path, monkeypatch, client, st=None):
    make_grid(tmp_path, monkeypatch, cfg={"release_sides": []}, st=st or lot_state(), journal=[])
    return run_script("orphan_check.py", client, monkeypatch)


def test_tp_in_open_list_is_clean(tmp_path, monkeypatch):
    live = {"orderId": "tp1", "clientOrderId": TP["cid"], "positionSide": "LONG", "side": "SELL", "price": "101",
            "origQty": "1", "executedQty": "0", "reduceOnly": True}
    code, out = run(tmp_path, monkeypatch, FakeClient(opens=[live]))
    assert code == 0, out


def test_filled_tp_awaiting_booking_is_not_lot_without_tp(tmp_path, monkeypatch):
    """TP исполнился целиком, учёт ещё не обновлён: позиции бота нет — не «лот без тейка»."""
    c = FakeClient(infos={"tp1": detail("FILLED", executed="1")})
    code, out = run(tmp_path, monkeypatch, c)
    assert c.info_calls == ["tp1"]
    assert code == 0, out
    assert "ждёт учёта" in out


def test_cancelled_tp_leaves_remainder_unprotected(tmp_path, monkeypatch):
    code, out = run(tmp_path, monkeypatch, FakeClient(infos={"tp1": detail("CANCELED")}))
    assert code == 1, out
    assert "без TP" in out and "отменён" in out


def test_partially_filled_then_cancelled_protects_nothing_of_remainder(tmp_path, monkeypatch):
    code, out = run(tmp_path, monkeypatch, FakeClient(infos={"tp1": detail("CANCELED", executed="0.4")}))
    assert code == 1, out
    assert "0.6" in out and "без TP" in out


def test_live_tp_missing_from_list_is_not_finding(tmp_path, monkeypatch):
    code, out = run(tmp_path, monkeypatch, FakeClient(infos={"tp1": detail("NEW")}))
    assert code == 0, out
    assert "пропущен списком" in out


def test_partially_filled_live_tp_protects_its_remainder(tmp_path, monkeypatch):
    code, out = run(tmp_path, monkeypatch, FakeClient(infos={"tp1": detail("PARTIALLY_FILLED", executed="0.4")}))
    assert code == 0, out
    assert "частично" in out


@pytest.mark.parametrize("info", [
    {},                                                            # пустой ответ
    {"orderId": "OTHER", "status": "FILLED", "executedQty": "1"},  # чужой orderId
    {"orderId": "tp1", "executedQty": "1"},                        # нет статуса
    {"orderId": "tp1", "status": "WEIRD", "executedQty": "1"},     # неизвестный статус
    RuntimeError("timeout"),                                      # ошибка запроса
])
def test_unknown_detail_is_unknown_not_clean(tmp_path, monkeypatch, info):
    code, out = run(tmp_path, monkeypatch, FakeClient(infos={"tp1": info}))
    assert code == 2, out
    assert "неизвест" in out and "сирот 0, лотов без тейка 0" not in out


def test_detail_for_wrong_position_side_is_unknown(tmp_path, monkeypatch):
    c = FakeClient(infos={"tp1": detail("FILLED", executed="1", positionSide="SHORT", side="BUY")})
    code, out = run(tmp_path, monkeypatch, c)
    assert code == 2, out
    assert "неизвест" in out


def test_listed_tp_smaller_than_lot_leaves_remainder_unprotected(tmp_path, monkeypatch):
    """Наличие id в списке не доказывает защиту: тейк на 0.5 при лоте 1 — 0.5 без TP."""
    live = {"orderId": "tp1", "clientOrderId": TP["cid"], "positionSide": "LONG", "side": "SELL", "price": "101",
            "origQty": "0.5", "executedQty": "0", "reduceOnly": True}
    code, out = run(tmp_path, monkeypatch, FakeClient(opens=[live]))
    assert code == 1, out
    assert "без TP" in out


def test_detail_with_other_price_is_unknown(tmp_path, monkeypatch):
    code, out = run(tmp_path, monkeypatch, FakeClient(infos={"tp1": detail("FILLED", executed="1", price="150")}))
    assert code == 2, out


def test_lot_without_tp_in_ledger_is_finding(tmp_path, monkeypatch):
    st = lot_state(tp_order=False)
    st["LONG"]["lots"][0]["tp_order"] = None
    code, out = run(tmp_path, monkeypatch, FakeClient(), st=st)
    assert code == 1, out
