"""End-to-end 'breathing' tests for pump_freeze.loop.tick().

Simulates the full cycle the operator asked for (2026-05-22):
  freeze on pump -> resume on 1% retrace -> re-freeze when price returns to
  hi -> resume again -> stall-resume when price stops making new highs.

Each tick is driven by a synthetic 31-bar window; the loop's data sources
(market CSV, snapshot CSV, exchange API) are monkeypatched.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

import services.pump_freeze.freezer as fz
import services.pump_freeze.loop as loop

UTC = timezone.utc
BOT = "4729923198"   # T1 SHORT — in APPLIES_TO_BOTS as 'short'


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolate state file + stub bot meta + exchange API."""
    sp = tmp_path / "pf_state.json"
    monkeypatch.setattr(fz, "STATE_PATH", sp)
    monkeypatch.setattr(fz, "JOURNAL_PATH", tmp_path / "pf_events.jsonl")

    api_calls = {"pause": [], "resume": []}
    monkeypatch.setattr(loop, "_api_pause",
                        lambda b: api_calls["pause"].append(b) or {"ok": 1})
    monkeypatch.setattr(loop, "_api_resume",
                        lambda b: api_calls["resume"].append(b) or {"ok": 1})
    # bot meta: large SHORT position so MIN_POSITION_USD_TO_TRIGGER passes
    monkeypatch.setattr(loop, "_read_bot_meta",
                        lambda b: (0.5, "T1", "T1") if b == BOT else (None, b, b))
    # only the one bot under test
    monkeypatch.setattr(loop, "APPLIES_TO_BOTS", {BOT: "short"})
    return api_calls


def _flat_window(price: float, end_ts: datetime, n: int = 31) -> list:
    """31 flat bars ending at end_ts."""
    return [(end_ts - timedelta(minutes=n - 1 - i), price, price, price)
            for i in range(n)]


def _ramp_window(start: float, end: float, end_ts: datetime, n: int = 31) -> list:
    """31 bars ramping start->end (a pump if end>start)."""
    out = []
    for i in range(n):
        cl = start + (end - start) * i / (n - 1)
        out.append((end_ts - timedelta(minutes=n - 1 - i), cl, cl, cl))
    return out


def _tick(monkeypatch, bars, now):
    monkeypatch.setattr(loop, "_load_recent_bars", lambda needed_min=35: bars)
    return loop.tick(now=now)


def test_freeze_fires_on_pump(env, monkeypatch):
    t = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
    bars = _ramp_window(80000, 81600, t)  # +2.0% over 30m
    r = _tick(monkeypatch, bars, t)
    assert r["frozen"] == 1
    assert fz.is_frozen(BOT)
    assert env["pause"] == [int(BOT)]


def test_no_freeze_when_flat(env, monkeypatch):
    t = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
    r = _tick(monkeypatch, _flat_window(80000, t), t)
    assert r["frozen"] == 0
    assert not fz.is_frozen(BOT)


def test_resume_on_retracement(env, monkeypatch):
    t0 = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
    _tick(monkeypatch, _ramp_window(80000, 81600, t0), t0)
    assert fz.is_frozen(BOT)
    # 20 min later price retraced -1.1% from the 81600 extreme
    t1 = t0 + timedelta(minutes=20)
    retr_price = 81600 * (1 - 0.011)
    r = _tick(monkeypatch, _flat_window(retr_price, t1), t1)
    assert r["resumed"] == 1
    assert not fz.is_frozen(BOT)
    assert env["resume"] == [int(BOT)]


def test_stall_resume_when_price_stuck_under_hi(env, monkeypatch):
    """Operator's key case: price stalls in a range under the hi — bot must
    resume on stall, not stand idle until timeout."""
    t0 = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
    _tick(monkeypatch, _ramp_window(80000, 81600, t0), t0)
    assert fz.is_frozen(BOT)
    # price sits at 81550 (only -0.06%, NO 1% retrace) — no new highs
    stuck = 81550.0
    resumed_total = 0
    for dm in (15, 30, 46, 50):
        t = t0 + timedelta(minutes=dm)
        r = _tick(monkeypatch, _flat_window(stuck, t), t)
        resumed_total += r["resumed"]
    # stall fires once idle >= RESUME_STALL_MIN(45) — around +46m
    assert resumed_total == 1
    assert not fz.is_frozen(BOT)


def test_no_stall_resume_while_new_highs_keep_coming(env, monkeypatch):
    """New highs keep resetting the stall clock → bot stays frozen."""
    t0 = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
    _tick(monkeypatch, _ramp_window(80000, 81600, t0), t0)
    px = 81600.0
    for dm in (20, 40, 60, 80):
        px += 50  # a fresh new high each tick
        t = t0 + timedelta(minutes=dm)
        r = _tick(monkeypatch, _flat_window(px, t), t)
        assert r["resumed"] == 0
    assert fz.is_frozen(BOT)  # still frozen — move is alive


def test_breathing_refreeze_after_resume(env, monkeypatch):
    """Full breathing cycle: freeze -> resume on retrace -> price returns to
    hi -> re-freeze (no time cooldown blocking it)."""
    t0 = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
    # 1) freeze on pump to 81600
    _tick(monkeypatch, _ramp_window(80000, 81600, t0), t0)
    assert fz.is_frozen(BOT)

    # 2) resume on -1.1% retrace
    t1 = t0 + timedelta(minutes=20)
    retr = 81600 * (1 - 0.011)            # ~80702
    r = _tick(monkeypatch, _flat_window(retr, t1), t1)
    assert r["resumed"] == 1 and not fz.is_frozen(BOT)

    # 3) price climbs back >1% from resume price → re-freeze gate opens AND a
    #    fresh pump window is present
    t2 = t1 + timedelta(minutes=40)
    back = retr * (1 + 0.02)              # +2% from resume price, new pump
    r = _tick(monkeypatch, _ramp_window(retr, back, t2), t2)
    assert r["frozen"] == 1
    assert fz.is_frozen(BOT)
    # paused twice, resumed once over the cycle
    assert len(env["pause"]) == 2
    assert len(env["resume"]) == 1


def test_refreeze_gate_holds_until_price_returns(env, monkeypatch):
    """After resume the gate stores resume_price; a re-freeze is only allowed
    once price climbs >=REFREEZE_RETURN_PCT back toward the hi. A mild bounce
    that stays below that level must NOT re-freeze."""
    t0 = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
    _tick(monkeypatch, _ramp_window(80000, 81600, t0), t0)
    t1 = t0 + timedelta(minutes=20)
    retr = 81600 * (1 - 0.011)                     # resume price ~80702
    _tick(monkeypatch, _flat_window(retr, t1), t1)
    assert not fz.is_frozen(BOT)
    info = fz.last_resume_info(BOT)
    assert info is not None and info["resume_price"] == round(retr, 2)

    # mild pump that ends only +0.5% above resume price — below the 1% gate.
    t2 = t1 + timedelta(minutes=40)
    mild_top = retr * 1.005
    r = _tick(monkeypatch, _ramp_window(retr * 0.985, mild_top, t2), t2)
    assert r["frozen"] == 0          # gate held — price not back to hi
    assert not fz.is_frozen(BOT)
