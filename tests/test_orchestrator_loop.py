from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock

from core.orchestrator.orchestrator_loop import OrchestratorLoop


@dataclass
class _Change:
    category_key: str
    from_action: str
    to_action: str
    reason_ru: str
    affected_bots: list[str]


@dataclass
class _Alert:
    text: str


@dataclass
class _Result:
    changed: list[_Change]
    unchanged: list[str]
    alerts: list[_Alert]


def test_orchestrator_loop_tick_no_changes(monkeypatch):
    loop = OrchestratorLoop({"ORCHESTRATOR_LOOP_INTERVAL_SEC": 1})
    monkeypatch.setattr("core.orchestrator.orchestrator_loop.build_full_snapshot", lambda symbol="BTCUSDT": {"regime": {"primary": "RANGE", "modifiers": []}})
    called = {"ks": 0, "dispatch": 0}
    monkeypatch.setattr("core.orchestrator.orchestrator_loop.check_all_killswitch_triggers", lambda config: called.__setitem__("ks", called["ks"] + 1))
    monkeypatch.setattr("core.orchestrator.orchestrator_loop.dispatch_orchestrator_decisions", lambda store, regime: called.__setitem__("dispatch", called["dispatch"] + 1) or _Result([], [], []))
    monkeypatch.setattr("core.orchestrator.orchestrator_loop.send_telegram_alert", AsyncMock())
    monkeypatch.setattr("core.orchestrator.orchestrator_loop.send_daily_report", AsyncMock())

    asyncio.run(loop._tick())
    assert called["ks"] == 1
    assert called["dispatch"] == 1


def test_orchestrator_loop_sends_alerts_on_change(monkeypatch):
    loop = OrchestratorLoop({"ORCHESTRATOR_LOOP_INTERVAL_SEC": 1})
    send_mock = AsyncMock()
    monkeypatch.setattr("core.orchestrator.orchestrator_loop.build_full_snapshot", lambda symbol="BTCUSDT": {"regime": {"primary": "TREND_DOWN", "modifiers": ["X"]}})
    monkeypatch.setattr("core.orchestrator.orchestrator_loop.check_all_killswitch_triggers", lambda config: None)
    monkeypatch.setattr(
        "core.orchestrator.orchestrator_loop.dispatch_orchestrator_decisions",
        lambda store, regime: _Result(
            [_Change("btc_long", "RUN", "PAUSE", "reason", ["btc_long_l1"])],
            [],
            [_Alert("extra alert")],
        ),
    )
    monkeypatch.setattr("core.orchestrator.orchestrator_loop.send_telegram_alert", send_mock)
    monkeypatch.setattr("core.orchestrator.orchestrator_loop.send_daily_report", AsyncMock())

    asyncio.run(loop._tick())
    # 2026-07-29: дубль «ОРКЕСТРАТОР: ИЗМЕНЕНИЕ» убран — он повторял карточку
    # действия из _build_alerts (на одну смену режима уходило 3 сообщения).
    assert send_mock.await_count == 1
    assert send_mock.await_args_list[0].args[0] == "extra alert"


def test_orchestrator_loop_format_change_alert():
    loop = OrchestratorLoop({})
    text = loop._format_change_alert(
        _Change("btc_long", "RUN", "PAUSE", "reason text", ["bot_a"]),
        {"primary": "TREND_DOWN", "modifiers": ["VOLATILITY_SPIKE"]},
    )
    assert "reason text" in text
    assert "bot_a" in text
    assert "TREND_DOWN" in text


def test_orchestrator_loop_sends_daily_report_once_per_day(monkeypatch):
    loop = OrchestratorLoop({"ORCHESTRATOR_LOOP_INTERVAL_SEC": 300, "ORCHESTRATOR_DAILY_REPORT_TIME": "09:00"})
    send_mock = AsyncMock()

    class _FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 4, 18, 9, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr("core.orchestrator.orchestrator_loop.datetime", _FakeDatetime)
    monkeypatch.setattr("core.orchestrator.orchestrator_loop.send_daily_report", send_mock)

    asyncio.run(loop._maybe_send_daily_report())
    asyncio.run(loop._maybe_send_daily_report())
    assert send_mock.await_count == 1
    assert loop._last_daily_report_date == date(2026, 4, 18)


def test_orchestrator_loop_stop_exits_start(monkeypatch):
    loop = OrchestratorLoop({"ORCHESTRATOR_LOOP_INTERVAL_SEC": 1})

    async def fake_tick():
        loop.stop()

    monkeypatch.setattr(loop, "_tick", fake_tick)
    monkeypatch.setattr("core.orchestrator.orchestrator_loop.asyncio.sleep", AsyncMock())
    asyncio.run(loop.start())
    assert loop._running is False
