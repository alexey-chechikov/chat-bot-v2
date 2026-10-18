"""18.10: параллельный проход сеток (Runner.tick) — скорость, доли общего потолка, изоляция ошибок."""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from services.weex_grid import engine as eg
from services.weex_grid import loop as lp


def _runner(monkeypatch, names, free=None, cfgs=None, book=None, send=None):
    monkeypatch.setattr(eg, "GRIDS", tuple(names))
    r = lp.Runner(send_fn=send)
    client = SimpleNamespace(book=book or (lambda sym: (100.0, 100.0)))
    monkeypatch.setattr(r, "_client", lambda: client)
    monkeypatch.setattr(r, "_portfolio_free", lambda: free)
    r.trend = SimpleNamespace(tick=lambda portfolio_free=None: None)
    if cfgs is not None:
        monkeypatch.setattr(lp, "grid_config", lambda n: cfgs[n])
    return r


def _cfg(enabled=True, dry=False, qty="1", sym="BTCUSDT", sides=("LONG",)):
    return {"enabled": enabled, "dry_run": dry, "order_qty": qty, "symbol": sym, "sides": list(sides)}


def test_grids_tick_in_parallel(monkeypatch):
    r = _runner(monkeypatch, ["A", "B", "C", "D"])
    seen = []

    def slow(name, free=None):
        seen.append(threading.current_thread().name)
        time.sleep(0.3)

    monkeypatch.setattr(r, "tick_one", slow)
    t0 = time.monotonic()
    r.tick()
    assert time.monotonic() - t0 < 0.9            # по очереди было бы 1.2 с
    assert len(set(seen)) == 4


def test_room_shares_sum_never_exceeds_free(monkeypatch):
    cfgs = {"A": _cfg(), "B": _cfg(), "C": _cfg(dry=True), "D": _cfg(enabled=False)}
    r = _runner(monkeypatch, cfgs, free=1000.0, cfgs=cfgs)
    shares = r._room_shares(list(cfgs), 1000.0)
    need = 1 * 100.0 * 1.01                       # один вход на сторону, ask с запасом 1%
    assert shares["A"] == pytest.approx(1000 - need) and shares["B"] == pytest.approx(1000 - need)
    assert shares["C"] == pytest.approx(1000 - 2 * need) and shares["D"] == pytest.approx(1000 - 2 * need)
    # худший случай: каждая живая сетка ставит вход на всю свою долю, но не больше одного входа
    for n in ("A", "B"):
        assert shares[n] + sum(need for m in ("A", "B") if m != n) <= 1000 + 1e-9


def test_room_shares_tight_cap_gives_no_double_room(monkeypatch):
    """Свободно $150, две живые сетки по $100: по очереди прошла бы одна; параллельно — ни одна (строже, не шире)."""
    cfgs = {"A": _cfg(), "B": _cfg()}
    r = _runner(monkeypatch, cfgs, cfgs=cfgs)
    shares = r._room_shares(["A", "B"], 150.0)
    assert all(s < 101.0 for s in shares.values())


def test_price_failure_closes_room_for_neighbours(monkeypatch):
    def boom(sym):
        raise RuntimeError("book down")

    cfgs = {"A": _cfg(), "B": _cfg(), "E": _cfg(sym="ETHUSDT")}
    calls = []
    r = _runner(monkeypatch, cfgs, cfgs=cfgs, book=lambda sym: calls.append(sym) or boom(sym))
    shares = r._room_shares(["A", "B", "E"], 1000.0)
    assert shares == {"A": 0.0, "B": 0.0, "E": 0.0}   # у каждой есть сосед с неизвестной ценой → места нет
    assert sorted(set(calls)) == ["BTCUSDT", "ETHUSDT"]


def test_free_none_no_book_calls(monkeypatch):
    calls = []
    r = _runner(monkeypatch, ["A"], book=lambda sym: calls.append(sym) or (1.0, 1.0))
    assert r._room_shares(["A"], None) == {}
    assert calls == []


def test_error_isolated_and_raised_after_all(monkeypatch):
    sends = []
    r = _runner(monkeypatch, ["A", "B", "C"], send=lambda m: sends.append(m) or True)
    done = []

    def tick_one(name, free=None):
        if name == "B":
            raise RuntimeError("сбой B")
        if name == "C":
            raise eg.StateCorrupt("учёт C битый")
        done.append(name)

    monkeypatch.setattr(r, "tick_one", tick_one)
    with pytest.raises(RuntimeError, match="B: сбой B"):
        r.tick()
    assert done == ["A"]
    assert len(sends) == 1 and "C" in sends[0]


def test_share_passed_to_tick_one(monkeypatch):
    cfgs = {"A": _cfg(), "B": _cfg()}
    r = _runner(monkeypatch, cfgs, free=500.0, cfgs=cfgs)
    got = {}
    monkeypatch.setattr(r, "tick_one", lambda name, free=None: got.__setitem__(name, free))
    r.tick()
    assert got["A"] == pytest.approx(500 - 101.0) and got["B"] == pytest.approx(500 - 101.0)
