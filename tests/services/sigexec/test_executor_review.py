"""Самопроверка по чек-листу живого ордерного кода (12.11, до разбора GPT): отказы биржи подряд, аварийный уровень
уже пройден, потолок с добором, запрещённая сторона, пропавший учёт при живом журнале."""
from __future__ import annotations

import json

import pytest

from services.sigexec.exchange.base import LONG, SHORT
from services.sigexec.exchange.sim import SimExchange
from services.sigexec.executor import Executor, Halt

from .test_executor import T0, d432, d_long, d_cs, mk, run


def jr(tmp_path):
    return [json.loads(x) for x in (tmp_path / "jr.jsonl").read_text().splitlines()]


def test_rejected_stop_is_not_retried_forever(tmp_path):
    said = []
    e, ex = mk(tmp_path, entry={"kind": "market"})
    e.notify = said.append
    run(e, ex, {"432": d432()})                          # вход
    for _ in range(6):
        ex.fail_next("place", "reject")                  # каждый аварийный стоп — отказ
    run(e, ex, {"432": d432()}, n=10)
    stops = [r for r in e.st["orders"].values() if r["role"] == "stop"]
    assert len(stops) == 3                               # max_rejects, дальше не долбит биржу
    assert any("АВАРИЙНОГО СТОПА НЕТ" in s for s in said)
    assert sum("АВАРИЙНОГО СТОПА НЕТ" in s for s in said) == 1   # сообщение раз в час, не каждый проход


def test_rejected_stop_retried_after_backoff(tmp_path):
    e, ex = mk(tmp_path, entry={"kind": "market"})
    run(e, ex, {"432": d432()})
    for _ in range(3):
        ex.fail_next("place", "reject")
    run(e, ex, {"432": d432()}, n=6, dt=5)
    assert [r["status"] for r in e.st["orders"].values() if r["role"] == "stop"] == ["REJECTED"] * 3
    run(e, ex, {"432": d432()}, n=2, dt=600)               # пауза прошла — новая попытка, биржа приняла
    assert [r["status"] for r in e.st["orders"].values() if r["role"] == "stop"][-1] == "UNTRIGGERED"


def test_entry_market_rejected_aborts_episode(tmp_path):
    e, ex = mk(tmp_path, entry={"kind": "market"})
    for _ in range(5):
        ex.fail_next("place", "reject")
    run(e, ex, {"432": d432()}, n=6)
    assert e.st["slots"]["432"]["ep"] is None
    assert T0 in e.st["slots"]["432"]["done"]
    assert len([r for r in e.st["orders"].values() if r["role"] == "entry"]) == 3
    assert ex.pos[LONG] == 0.0


def test_exit_market_rejected_keeps_retrying_slowly(tmp_path):
    e, ex = mk(tmp_path, entry={"kind": "market"}, exit={"kind": "market"})
    run(e, ex, {"432": d432()}, n=2)
    for _ in range(4):
        ex.fail_next("place", "reject")
    run(e, ex, {"432": None}, n=8, dt=5)                  # 3 отказа подряд → пауза 60 с
    n_exit = len([r for r in e.st["orders"].values() if r["role"] == "exit"])
    assert n_exit == 3 and ex.pos[LONG] > 0
    run(e, ex, {"432": None}, n=3, dt=40)                 # через минуту повтор (4-й отказ), ещё через минуту — исполнен
    run(e, ex, {"432": None}, n=3, dt=40)
    assert ex.pos[LONG] == pytest.approx(0.0)


def test_emergency_level_already_crossed_exits_by_itself(tmp_path):
    e, ex = mk(tmp_path, entry={"kind": "market"}, exit={"kind": "market"})
    run(e, ex, {"432": d432()}, n=2)
    stop = next(r for r in e.st["orders"].values() if r["role"] == "stop")
    ex.orders[stop["cid"]]["status"] = "CANCELED"         # стоп пропал (снят, истёк)
    ex.px = 60000.0                                       # цена уже ниже аварийного уровня 61 600 без хода через стоп
    run(e, ex, {"432": d432()}, n=3)
    assert ex.pos[LONG] == pytest.approx(0.0)
    assert any(r["kind"] == "выход начат" and "аварийный уровень" in r["why"] for r in jr(tmp_path))


def test_cap_reserves_room_for_add(tmp_path):
    e, ex = mk(tmp_path, entry={"kind": "market"}, cap_usd=1500.0)
    run(e, ex, {"system": d_long(add_lv=72000.0)}, n=2)   # $500 вход + $500 добор держат $1 000
    run(e, ex, {"system": d_long(add_lv=72000.0), "432": d432()}, n=2)
    q432 = e.qty(e.st["slots"]["432"]["ep"])
    assert 0.0070 <= q432 <= 0.0073                       # остаток места ≈$506 (без брони добора было бы 0.0142)
    ex.move(72100.0)
    run(e, ex, {"system": d_long(add_lv=72000.0), "432": d432()}, n=3)
    total = sum(e.qty(S["ep"]) * 70000 for S in e.st["slots"].values() if S["ep"])
    assert total <= 1500 * 1.03


def test_forbidden_side_is_skipped(tmp_path):
    e, ex = mk(tmp_path, entry={"kind": "market"}, allowed_sides=["LONG"])
    run(e, ex, {"system": d_cs()}, n=3)                    # шорт под жёлтой на WEEX: сторона SHORT — оператора
    assert e.st["slots"]["system"]["ep"] is None and ex.pos[SHORT] == 0.0
    assert not e.st["orders"]


def test_missing_state_with_journal_halts(tmp_path):
    e, ex = mk(tmp_path, entry={"kind": "market"})
    run(e, ex, {"432": d432()}, n=2)
    (tmp_path / "st.json").unlink()
    e.close()
    with pytest.raises(Halt, match="пропал"):
        Executor(SimExchange(), {"enabled": True}, tmp_path / "st.json", tmp_path / "jr.jsonl")


def test_post_only_rejects_do_not_block_entry(tmp_path):
    e, ex = mk(tmp_path, entry={"kind": "chase", "wait_s": 300, "reprice_s": 20, "max_orders": 20})
    for _ in range(5):
        ex.fail_next("place", "reject")                   # post-only пересёк стакан 5 раз подряд — это не отказ биржи
    run(e, ex, {"system": d_long()}, n=7)
    ep = e.st["slots"]["system"]["ep"]
    assert ep is not None and ep["phase"] == "entering"
    assert any(r["status"] == "NEW" and r["kind"] == "LIMIT" for r in e.st["orders"].values())
