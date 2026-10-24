"""23.10: трендовый бот в цикле сеток — без эпизода и заявки не чаще раза в TREND_IDLE_SEC (его проход занимал до 58 с,
тейки сеток ставились с задержкой до минуты); с эпизодом/pending или при нечитаемом учёте — каждый проход."""
from __future__ import annotations

import json

import pytest

from services.weex_grid import loop


class Clock:
    def __init__(self, t: float):
        self.t = t

    def time(self) -> float:
        return self.t


class FakeTrend:
    def __init__(self):
        self.calls = 0

    def tick(self, portfolio_free=None):
        self.calls += 1


@pytest.fixture
def runner(tmp_path, monkeypatch):
    from services.weex_trend import engine as te
    import services.weex_trend.loop as tl
    monkeypatch.setattr(loop, "AUDIT_FILE", tmp_path / "audit.json")
    monkeypatch.setattr(loop.eg, "GRIDS", [])
    monkeypatch.setattr(te, "load_config", lambda: {"symbols": ["ETHUSDT", "XRPUSDT"]})
    monkeypatch.setattr(tl, "files", lambda dry, sym="ETHUSDT": (tmp_path / f"{sym}_{'dry' if dry else 'live'}.json",
                                                                tmp_path / "j.jsonl"))
    clock = Clock(1_000_000.0)
    monkeypatch.setattr(loop, "time", clock)
    r = loop.Runner()
    monkeypatch.setattr(r, "_position_audit", lambda: None)
    r.trend = FakeTrend()
    return r, clock, tmp_path


def _passes(r, clock, times):
    for t in times:
        clock.t = t
        r.tick()


def test_idle_trend_ticks_once_per_idle_period(runner):
    r, clock, _ = runner
    t0 = clock.t
    _passes(r, clock, [t0, t0 + 10, t0 + 60, t0 + loop.TREND_IDLE_SEC - 1])
    assert r.trend.calls == 1                                       # первый проход — да, дальше молчит
    _passes(r, clock, [t0 + loop.TREND_IDLE_SEC + 5])
    assert r.trend.calls == 2


@pytest.mark.parametrize("fname, field", [("XRPUSDT_live.json", "episode"), ("ETHUSDT_dry.json", "pending")])
def test_episode_or_pending_ticks_every_pass(runner, fname, field):
    r, clock, tmp = runner
    t0 = clock.t
    _passes(r, clock, [t0])
    (tmp / fname).write_text(json.dumps({field: {"side": "LONG"}}))
    _passes(r, clock, [t0 + 10, t0 + 20, t0 + 30])
    assert r.trend.calls == 4


def test_unreadable_trend_state_ticks_every_pass(runner):
    r, clock, tmp = runner
    t0 = clock.t
    _passes(r, clock, [t0])
    (tmp / "ETHUSDT_live.json").write_text("{битый")
    _passes(r, clock, [t0 + 10, t0 + 20])
    assert r.trend.calls == 3
