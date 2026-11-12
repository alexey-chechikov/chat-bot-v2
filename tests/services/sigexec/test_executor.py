"""Исполнитель сигналов на имитаторе биржи: тактики, потерянные ответы, частичные исполнения, добор, цель, стоп, выход."""
from __future__ import annotations

import json

import pytest

from services.sigexec.exchange.base import LONG, SHORT
from services.sigexec.exchange.sim import SimExchange
from services.sigexec.executor import Executor, Halt, validate_config
from services.sigexec.strategy import Desired

T0 = 1_800_000_000  # закрытие 4ч сигнала


def mk(tmp_path, ex=None, **cfg):
    ex = ex or SimExchange(price=70000.0)
    ex._t = T0 + 5
    base = {"enabled": True, "base_usd": 1000.0, "cap_usd": 5000.0}
    base.update(cfg)
    e = Executor(ex, base, tmp_path / "st.json", tmp_path / "jr.jsonl")
    return e, ex


def d_long(**kw):
    x = dict(slot="system", entry_t=T0, side=1, tag="над синей", w=1.0, sig_px=70000.0, main_frac=0.5, add_lv=72000.0, add_frac=0.5, add_done=False,
             target=None, exit_by_t=None, exit_text="")
    x.update(kw)
    return Desired(**x)


def d_cs(**kw):
    x = dict(slot="system", entry_t=T0, side=-1, tag="под жёлтой", w=1.0, sig_px=70000.0, main_frac=1.0, add_lv=None, add_frac=0.0, add_done=False,
             target=68000.0, exit_by_t=None, exit_text="")
    x.update(kw)
    return Desired(**x)


def d432(**kw):
    x = dict(slot="432", entry_t=T0, side=1, tag="432", w=1.0, sig_px=70000.0, main_frac=1.0, add_lv=None, add_frac=0.0, add_done=False, target=None,
             exit_by_t=T0 + 80 * 3600, exit_text="")
    x.update(kw)
    return Desired(**x)


def run(e, ex, desired, n=1, dt=5.0, events=None):
    for _ in range(n):
        e.step(desired, events)
        ex.tick_clock(dt)


def journal(tmp_path):
    return [json.loads(x) for x in (tmp_path / "jr.jsonl").read_text().splitlines()]


def roles(e, live=True):
    return sorted((r["role"], r["kind"]) for r in e.st["orders"].values() if (r["status"] not in ("FILLED", "CANCELED", "REJECTED", "ABSENT")) == live)


def test_chase_entry_fills_as_maker_then_protects(tmp_path):
    e, ex = mk(tmp_path)
    run(e, ex, {"system": d_long()})
    assert roles(e) == [("entry", "LIMIT")]
    ex.move(69990.0)                                    # цена прошла сквозь лимитку покупки
    run(e, ex, {"system": d_long()})
    ep = e.st["slots"]["system"]["ep"]
    assert ep["phase"] == "open"
    assert e.qty(ep) == pytest.approx(0.0071)           # $500 / 70 000 → 0.0071
    assert roles(e) == [("add", "STOP"), ("stop", "STOP")]
    stop = next(r for r in e.st["orders"].values() if r["role"] == "stop" and r["status"] == "UNTRIGGERED")
    assert stop["trigger"] == pytest.approx(70000 * 0.88, abs=0.2) and stop["qty"] == pytest.approx(0.0071)
    fees = [r["fee"] for r in e.st["orders"].values() if r["role"] == "entry" and r["filled"]]
    assert fees[0] == pytest.approx(0.0071 * 69999.9 * 0.00016, rel=1e-3)   # мейкер


def test_chase_falls_back_to_market_after_wait(tmp_path):
    e, ex = mk(tmp_path, entry={"kind": "chase", "wait_s": 30, "reprice_s": 10, "max_orders": 20})
    for p in (70050, 70100, 70150, 70200, 70250, 70300, 70350, 70400):  # цена уходит вверх, лимитка не наливается
        run(e, ex, {"system": d_long()})
        ex.move(p)
    run(e, ex, {"system": d_long()}, n=3)
    ep = e.st["slots"]["system"]["ep"]
    assert ep["phase"] == "open"
    kinds = [r["kind"] for r in e.st["orders"].values() if r["role"] == "entry" and r["filled"] > 0]
    assert kinds == ["MARKET"]
    limits = [r for r in e.st["orders"].values() if r["role"] == "entry" and r["kind"] == "LIMIT"]
    assert len(limits) >= 2 and all(r["status"] == "CANCELED" for r in limits)   # переставлял и снимал, двух живых не было


def test_lost_reply_no_double_entry(tmp_path):
    e, ex = mk(tmp_path, entry={"kind": "market"})
    ex.fail_next("place", "unknown_placed")             # рыночный исполнился, ответ потерян
    run(e, ex, {"system": d_long()})
    run(e, ex, {"system": d_long()}, n=3)
    ent = [r for r in e.st["orders"].values() if r["role"] == "entry"]
    assert len(ent) == 1 and ent[0]["status"] == "FILLED"
    assert ex.pos[LONG] == pytest.approx(0.0071)


def test_lost_reply_order_absent_then_retries(tmp_path):
    e, ex = mk(tmp_path, entry={"kind": "market"}, unknown_grace_s=60)
    ex.fail_next("place", "unknown_lost")               # ответ потерян, ордера нет
    run(e, ex, {"system": d_long()})
    run(e, ex, {"system": d_long()}, n=5, dt=5)          # меньше grace — новой заявки нет
    assert len([r for r in e.st["orders"].values() if r["role"] == "entry"]) == 1
    run(e, ex, {"system": d_long()}, n=3, dt=40)         # grace прошёл → ABSENT → новая заявка
    ent = [r for r in e.st["orders"].values() if r["role"] == "entry"]
    assert [r["status"] for r in ent] == ["ABSENT", "FILLED"]
    assert ex.pos[LONG] == pytest.approx(0.0071)


def test_incomplete_lookup_keeps_waiting(tmp_path):
    e, ex = mk(tmp_path, entry={"kind": "market"}, unknown_grace_s=10)
    ex.fail_next("place", "unknown_lost")
    run(e, ex, {"system": d_long()})
    for _ in range(4):
        ex.fail_next("order", "incomplete")
        run(e, ex, {"system": d_long()}, dt=30)
    ent = [r for r in e.st["orders"].values() if r["role"] == "entry"]
    assert len(ent) == 1 and ent[0]["status"] == "UNKNOWN"   # неполный поиск ≠ «не было»


def test_partial_market_fill_is_completed(tmp_path):
    e, ex = mk(tmp_path, entry={"kind": "market"})
    ex.partial_next(0.4)
    run(e, ex, {"system": d_long()}, n=3)
    ent = [r for r in e.st["orders"].values() if r["role"] == "entry"]
    assert len(ent) == 2 and sum(r["filled"] for r in ent) == pytest.approx(0.0071)
    assert e.st["slots"]["system"]["ep"]["phase"] == "open"


def test_add_stop_fills_and_emergency_stop_resized(tmp_path):
    e, ex = mk(tmp_path, entry={"kind": "market"})
    run(e, ex, {"system": d_long()}, n=2)
    ex.move(72100.0)                                    # стоп добора сработал на бирже
    run(e, ex, {"system": d_long()}, n=3)
    ep = e.st["slots"]["system"]["ep"]
    assert e._filled(ep, ("add",)) == pytest.approx(0.0069)      # $500 / 72 000
    stops = [r for r in e.st["orders"].values() if r["role"] == "stop" and r["status"] == "UNTRIGGERED"]
    assert len(stops) == 1 and stops[0]["qty"] == pytest.approx(0.0140)
    assert ex.pos[LONG] == pytest.approx(0.0140)


def test_engine_add_done_but_exchange_missed_is_followed_by_market(tmp_path):
    e, ex = mk(tmp_path, entry={"kind": "market"})
    run(e, ex, {"system": d_long()}, n=2)
    run(e, ex, {"system": d_long(add_done=True)}, n=4)    # Binance коснулся, перп — нет
    ep = e.st["slots"]["system"]["ep"]
    adds = [r for r in e.st["orders"].values() if r["role"] == "add"]
    assert [r["kind"] for r in adds if r["filled"]] == ["MARKET"] and any(r["kind"] == "STOP" and r["status"] == "CANCELED" for r in adds)
    assert e._filled(ep, ("add",)) == pytest.approx(0.0069)
    run(e, ex, {"system": d_long(add_done=True)}, n=3)
    assert len([r for r in e.st["orders"].values() if r["role"] == "add" and r["filled"]]) == 1   # второй раз не добирает


def test_signal_exit_cancels_protection_and_closes(tmp_path):
    e, ex = mk(tmp_path, entry={"kind": "market"}, exit={"kind": "market"})
    run(e, ex, {"system": d_long()}, n=2)
    ex.move(71000.0)
    ev = [{"slot": "system", "kind": "выход", "t": T0 + 14400, "entry_t": T0, "px": 71000.0, "why": "2 закрытия 4ч под красной", "res": 0.6}]
    run(e, ex, {"system": None}, events=ev)
    run(e, ex, {"system": None}, n=3)
    assert e.st["slots"]["system"]["ep"] is None
    assert ex.pos[LONG] == pytest.approx(0.0)
    assert roles(e) == []
    tr = [r for r in journal(tmp_path) if r["kind"] == "сделка"]
    assert len(tr) == 1 and tr[0]["pnl_usd"] == pytest.approx(0.0071 * (71000 * 0.9999 - 70000 * 1.0001) - tr[0]["fee"], abs=0.02)
    assert tr[0]["engine_usd"] == pytest.approx(6.0)
    run(e, ex, {"system": d_long()}, n=3)                # тот же эпизод повторно не открывается
    assert e.st["slots"]["system"]["ep"] is None


def test_cs_short_target_limit_fills(tmp_path):
    e, ex = mk(tmp_path, entry={"kind": "market"})
    run(e, ex, {"system": d_cs()}, n=2)
    assert roles(e) == [("stop", "STOP"), ("target", "LIMIT")]
    run(e, ex, {"system": d_cs(target=68500.0)}, n=3)     # цель сдвинулась через 4ч — лимитка переставлена
    tg = [r for r in e.st["orders"].values() if r["role"] == "target" and r["status"] == "NEW"]
    assert len(tg) == 1 and tg[0]["price"] == pytest.approx(68500.0)
    ex.move(68400.0)
    run(e, ex, {"system": d_cs(target=68500.0)}, n=3)
    assert e.st["slots"]["system"]["ep"] is None and ex.pos[SHORT] == pytest.approx(0.0)
    tr = [r for r in journal(tmp_path) if r["kind"] == "сделка"][0]
    assert tr["avg_out"] == pytest.approx(68500.0) and tr["pnl_usd"] > 0


def test_emergency_stop_closes_episode_without_reentry(tmp_path):
    e, ex = mk(tmp_path, entry={"kind": "market"})
    run(e, ex, {"432": d432()}, n=2)
    ex.move(61000.0)                                    # −12.9% — аварийный стоп
    run(e, ex, {"432": d432()}, n=3)
    assert e.st["slots"]["432"]["ep"] is None and ex.pos[LONG] == pytest.approx(0.0)
    run(e, ex, {"432": d432()}, n=3)
    assert e.st["slots"]["432"]["ep"] is None           # движок ещё в позиции — повторно не входим


def test_external_close_shrinks_ledger(tmp_path):
    e, ex = mk(tmp_path, entry={"kind": "market"})
    run(e, ex, {"432": d432()}, n=2)
    ex.external_trade(LONG, -0.005)                     # кто-то закрыл часть наших контрактов
    run(e, ex, {"432": d432()}, n=4)
    ep = e.st["slots"]["432"]["ep"]
    assert e.qty(ep) == pytest.approx(ex.pos[LONG])
    assert any(r["kind"] == "закрыто извне" for r in journal(tmp_path))


def test_foreign_position_on_same_side_is_not_ours(tmp_path):
    e, ex = mk(tmp_path, entry={"kind": "market"}, exit={"kind": "market"})
    ex.external_trade(LONG, 0.05)                        # лонги сетки или ручные на той же стороне
    run(e, ex, {"432": d432()}, n=2)
    run(e, ex, {"432": None}, n=3)
    assert ex.pos[LONG] == pytest.approx(0.05)          # закрыто ровно своё


def test_stale_signal_skipped(tmp_path):
    e, ex = mk(tmp_path)
    ex._t = T0 + 4000
    run(e, ex, {"system": d_long()})
    assert e.st["slots"]["system"]["ep"] is None and T0 in e.st["slots"]["system"]["done"]


def test_cap_limits_second_slot(tmp_path):
    e, ex = mk(tmp_path, entry={"kind": "market"}, cap_usd=1200.0)
    run(e, ex, {"system": d_long(w=1.6, main_frac=0.8), "432": d432()}, n=3)
    total = sum(e.qty(S["ep"]) * 70000 for S in e.st["slots"].values() if S["ep"])
    assert total <= 1200 * 1.001


def test_disabled_no_new_but_manages_open(tmp_path):
    e, ex = mk(tmp_path, entry={"kind": "market"}, exit={"kind": "market"})
    run(e, ex, {"432": d432()}, n=2)
    e.cfg["enabled"] = False
    run(e, ex, {"432": None}, n=3)
    assert ex.pos[LONG] == pytest.approx(0.0)
    run(e, ex, {"432": d432(entry_t=T0 + 14400)}, n=2)
    assert e.st["slots"]["432"]["ep"] is None


def test_stale_data_holds_position(tmp_path):
    e, ex = mk(tmp_path, entry={"kind": "market"})
    run(e, ex, {"432": d432()}, n=2)
    run(e, ex, None, n=3)                                # данные несвежие — не выходим «по пустому сигналу»
    assert ex.pos[LONG] == pytest.approx(0.0142)


def test_restart_resumes_from_state(tmp_path):
    e, ex = mk(tmp_path, entry={"kind": "market"}, exit={"kind": "market"})
    run(e, ex, {"432": d432()}, n=2)
    e2 = Executor(ex, dict(e.cfg), tmp_path / "st.json", tmp_path / "jr.jsonl")
    run(e2, ex, {"432": d432()}, n=2)
    assert len([r for r in e2.st["orders"].values() if r["role"] == "entry"]) == 1
    run(e2, ex, {"432": None}, n=3)
    assert ex.pos[LONG] == pytest.approx(0.0)


def test_crash_after_intent_before_send(tmp_path):
    e, ex = mk(tmp_path, entry={"kind": "market"}, unknown_grace_s=30)
    rec = e._send  # имитируем падение между записью намерения и отправкой
    ep = e._start("432", d432())
    cid = e._cid("432", "entry")
    e.st["orders"][cid] = {"cid": cid, "ep": ep["id"], "role": "entry", "kind": "MARKET", "side": "BUY", "qty": 0.0142, "price": None, "trigger": None,
                           "status": "SENDING", "filled": 0.0, "avg": 0.0, "fee": 0.0, "oid": "", "t_sent": ex.now(), "t_done": None}
    ep["work"] = {"role": "entry", "t0": ex.now(), "n": 1, "cur": cid}
    e.save()
    e2 = Executor(ex, dict(e.cfg), tmp_path / "st.json", tmp_path / "jr.jsonl")
    run(e2, ex, {"432": d432()}, n=2, dt=10)
    assert ex.pos[LONG] == 0.0                           # пока grace — новой заявки нет
    run(e2, ex, {"432": d432()}, n=3, dt=20)
    assert ex.pos[LONG] == pytest.approx(0.0142)
    assert rec is not None


def test_broken_state_halts(tmp_path):
    (tmp_path / "st.json").write_text("{broken")
    with pytest.raises(Halt):
        Executor(SimExchange(), {"enabled": True}, tmp_path / "st.json", tmp_path / "jr.jsonl")


def test_bad_config_halts():
    with pytest.raises(Halt):
        validate_config({"base_usd": -1})
    with pytest.raises(Halt):
        validate_config({"unknown_key": 1})
    with pytest.raises(Halt):
        validate_config({"entry": {"kind": "twap"}})


def test_filled_decrease_halts(tmp_path):
    e, ex = mk(tmp_path, entry={"kind": "market"})
    run(e, ex, {"432": d432()}, n=1)
    cid = next(iter(e.st["orders"]))
    ex.orders[cid]["filled"] = 0.001                     # биржа «забыла» исполнение — учёт не верит
    e.st["orders"][cid]["status"] = "NEW"
    with pytest.raises(Halt):
        e.step({"432": d432()})


def test_two_slots_same_side_separate_ledgers(tmp_path):
    e, ex = mk(tmp_path, entry={"kind": "market"}, exit={"kind": "market"})
    run(e, ex, {"system": d_long(add_lv=80000.0), "432": d432()}, n=2)
    assert ex.pos[LONG] == pytest.approx(0.0071 + 0.0142)
    run(e, ex, {"system": d_long(add_lv=80000.0), "432": None}, n=3)   # 432 вышел, система держит
    assert ex.pos[LONG] == pytest.approx(0.0071)
    assert e.qty(e.st["slots"]["system"]["ep"]) == pytest.approx(0.0071)


def test_post_only_reject_reprices(tmp_path):
    e, ex = mk(tmp_path)
    ex.fail_next("place", "reject")
    run(e, ex, {"system": d_long()}, n=2)
    ent = [r for r in e.st["orders"].values() if r["role"] == "entry"]
    assert [r["status"] for r in ent] == ["REJECTED", "NEW"]
