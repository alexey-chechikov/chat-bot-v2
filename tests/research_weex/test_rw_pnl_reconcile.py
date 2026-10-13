"""research/weex/pnl_reconcile.py — разбор GPT 13.10 §3 Q3: сверять все стороны, которыми бот КОГДА-ЛИБО владел
(не только cfg.sides); переданную — до границы передачи; нет clientOrderId / null истории — «не прочитано» (код 2)."""
import time

import pytest

from tests.research_weex.harness import FakeClient, iso, make_grid, run_script, side_state, trade

NOW = time.time()
T0 = NOW - 5 * 86400


def bot_info(*oids, prefix="b7gBS"):
    return {o: {"orderId": o, "clientOrderId": f"{prefix}{o}"} for o in oids}


def run(tmp_path, monkeypatch, client, st, journal, cfg=None):
    make_grid(tmp_path, monkeypatch, cfg={"release_sides": [], **(cfg or {})}, st=st, journal=journal)
    return run_script("pnl_reconcile.py", client, monkeypatch)


def st_with(**sides):
    st = {"symbol": "BTCUSDT", "LONG": side_state(), "SHORT": side_state(), "halted": False}
    for s, kw in sides.items():
        st[s].update(kw)
    return st


# ---------- сторона убрана из sides и опустела — всё равно сверяется
SHORT_JOURNAL = [{"ts": iso(T0), "side": "SHORT", "kind": "вход", "order_id": "open"},
                 {"ts": iso(T0 + 3600), "side": "SHORT", "kind": "тейк", "order_id": "close"}]
SHORT_TRADES = [trade("1", "open", side="SELL", price=105.0, at=T0),
                trade("2", "close", side="BUY", price=100.0, at=T0 + 3600)]


def test_removed_and_emptied_side_mismatch_is_not_hidden(tmp_path, monkeypatch):
    """Биржа по SHORT $5, учёт $7; SHORT убран из sides и пуст — расхождение $2 не должно пропасть."""
    st = st_with(SHORT={"realized": 7.0, "n_entries": 1, "n_tps": 1})
    c = FakeClient(trades=SHORT_TRADES, infos=bot_info("open", "close"))
    code, out = run(tmp_path, monkeypatch, c, st, SHORT_JOURNAL)
    assert code == 1, out
    assert "SHORT" in out and "+2.0000" in out


def test_removed_and_emptied_side_that_matches_is_ok(tmp_path, monkeypatch):
    st = st_with(SHORT={"realized": 5.0, "n_entries": 1, "n_tps": 1})
    c = FakeClient(trades=SHORT_TRADES, infos=bot_info("open", "close"))
    code, out = run(tmp_path, monkeypatch, c, st, SHORT_JOURNAL)
    assert code == 0, out
    assert "SHORT" in out


def test_bot_fills_on_side_unknown_to_journal_and_state_are_reconciled(tmp_path, monkeypatch):
    """Сделки бота (b7g) на SHORT, а журнал, учёт и sides SHORT не знают (записи потеряны/учёт сброшен) — сторону
    нельзя молча пропустить: биржа $5, учёт $0 → расхождение."""
    journal = [{"ts": iso(T0 - 60), "side": "LONG", "kind": "вход", "order_id": "l0"}]
    c = FakeClient(trades=SHORT_TRADES, infos=bot_info("open", "close"))
    code, out = run(tmp_path, monkeypatch, c, st_with(), journal)
    assert code == 1, out
    assert "SHORT" in out and "-5.0000" in out


# ---------- нет clientOrderId у совпавшего orderId → владелец неизвестен
@pytest.mark.parametrize("cid_field", [{}, {"clientOrderId": None}, {"clientOrderId": ""}])
def test_missing_cid_is_unknown_not_manual(tmp_path, monkeypatch, cid_field):
    trs = [trade("1", "open", pos="LONG", side="BUY", price=100.0, at=T0),
           trade("2", "close", pos="LONG", side="SELL", price=105.0, at=T0 + 3600)]
    infos = {o: {"orderId": o, **cid_field} for o in ("open", "close")}
    journal = [{"ts": iso(T0), "side": "LONG", "kind": "вход"}]
    code, out = run(tmp_path, monkeypatch, FakeClient(trades=trs, infos=infos), st_with(), journal)
    assert code == 2, out
    assert "совпадает" not in out


# ---------- история null — ошибка чтения
@pytest.mark.parametrize("resp", [None, {"code": "40001"}])
def test_null_history_is_read_error(tmp_path, monkeypatch, resp):
    journal = [{"ts": iso(T0), "side": "LONG", "kind": "вход"}]
    code, out = run(tmp_path, monkeypatch, FakeClient(trades=resp), st_with(), journal)
    assert code == 2, out
    assert "совпадает" not in out


# ---------- переданная сторона: деньги до границы передачи
HANDOVER = T0 + 2 * 86400
REL_JOURNAL = [{"ts": iso(T0), "side": "SHORT", "kind": "вход", "order_id": "s1"},
               {"ts": iso(T0 + 60), "side": "SHORT", "kind": "вход", "order_id": "s2"},
               {"ts": iso(T0 + 3600), "side": "SHORT", "kind": "тейк", "order_id": "s3"},
               {"ts": iso(HANDOVER), "side": "SHORT", "kind": "передано оператору", "qty": "1", "avg": 105.0,
                "mark": 100.0, "bag": 5.0, "lots": 1}]
# вход 105 (передан), вход 104 → тейк 103 (+1); после передачи — ручная покупка оператора
REL_TRADES = [trade("1", "s1", side="SELL", price=105.0, at=T0),
              trade("2", "s2", side="SELL", price=104.0, at=T0 + 60),
              trade("3", "s3", side="BUY", price=103.0, at=T0 + 3600),
              trade("4", "m1", side="BUY", price=90.0, at=HANDOVER + 86400)]
REL_INFOS = {**bot_info("s1", "s2", "s3"), "m1": {"orderId": "m1", "clientOrderId": "web-manual"}}


def test_released_side_money_reconciled_up_to_handover(tmp_path, monkeypatch):
    """Учёт SHORT $3 закрыто вместо $1: до передачи расхождение $2 должно быть найдено."""
    st = st_with(SHORT={"realized": 3.0, "n_entries": 2, "n_tps": 1})
    c = FakeClient(trades=REL_TRADES, infos=REL_INFOS)
    code, out = run(tmp_path, monkeypatch, c, st, REL_JOURNAL, cfg={"release_sides": ["SHORT"]})
    assert code == 1, out
    assert "+2.0000" in out


def test_released_side_matching_and_manual_after_handover_is_ok(tmp_path, monkeypatch):
    st = st_with(SHORT={"realized": 1.0, "n_entries": 2, "n_tps": 1})
    c = FakeClient(trades=REL_TRADES, infos=REL_INFOS)
    code, out = run(tmp_path, monkeypatch, c, st, REL_JOURNAL, cfg={"release_sides": ["SHORT"]})
    assert code == 0, out


def test_bot_fill_after_handover_is_problem(tmp_path, monkeypatch):
    st = st_with(SHORT={"realized": 1.0, "n_entries": 2, "n_tps": 1})
    trs = REL_TRADES + [trade("5", "s4", side="BUY", price=95.0, at=HANDOVER + 3600)]
    c = FakeClient(trades=trs, infos={**REL_INFOS, **bot_info("s4")})
    code, out = run(tmp_path, monkeypatch, c, st, REL_JOURNAL, cfg={"release_sides": ["SHORT"]})
    assert code == 1, out
    assert "ПРОБЛЕМА" in out


def test_released_side_without_record_but_with_bot_fills_is_unknown(tmp_path, monkeypatch):
    st = st_with(SHORT={"realized": 5.0, "n_entries": 1, "n_tps": 1})
    c = FakeClient(trades=SHORT_TRADES, infos=bot_info("open", "close"))
    code, out = run(tmp_path, monkeypatch, c, st, SHORT_JOURNAL, cfg={"release_sides": ["SHORT"]})
    assert code == 2, out
    assert "неизвест" in out
