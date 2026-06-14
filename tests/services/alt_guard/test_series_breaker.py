"""Предохранитель серии (задача 2 Вина): 2 стопа в окне → ПАУЗА → RESTART в RANGE."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.alt_guard.loop import evaluate

NOW = datetime(2026, 6, 14, 12, 0, 0, tzinfo=timezone.utc)


def _slot(name, *, status=2, profit=30.0, cur=30.0, position=-100.0):
    mk = lambda: {"bot_name": name, "status": status, "profit": profit, "current_profit": cur,
                  "position": position, "average_price": 1.0, "balance": 7500.0,
                  "liquidation_price": 0.0}
    return {"latest": mk(), "day0": mk(), "fresh": True}


def _base(bots, params, **kw):
    d = dict(snap={"bots": bots, "stale_min": 0.5}, params=params, managed_ids=set(),
             deriv={}, xrp_px_1h_ago=None, cascade_dedup={}, state={}, now=NOW)
    d.update(kw)
    return d


def _p():
    import json
    return {"side": "3", "raw_params_json": json.dumps({"tsl": -175, "side": 3})}


def test_two_stops_trigger_pause():
    # стоп 1: бот был активен (prev_active), теперь статус 16 (TP/SL) — ждём дебаунс 3 мин
    bots = {"5617871752": _slot("WLD", status=16, profit=-50.0, cur=-50.0)}
    kw = _base(bots, {"5617871752": _p()})
    kw["state"] = {"prev_active": {"5617871752": True},
                   "inactive": {"5617871752": {"since": (NOW - timedelta(minutes=5)).isoformat(), "pinged": False}},
                   "stop_events": [{"ts": (NOW - timedelta(hours=2)).isoformat(), "bot": "SOL", "type": "STOP-TPSL", "profit": -40}]}
    alerts, state = evaluate(**kw)
    assert any("ПРЕДОХРАНИТЕЛЬ" in a and "ПАУЗА" in a for a in alerts)
    assert state["series_pause"] is True


def test_pause_lifts_in_range():
    kw = _base({}, {})
    kw["state"] = {"series_pause": True, "stop_events": [
        {"ts": (NOW - timedelta(hours=1)).isoformat(), "bot": "X", "type": "STOP-TPSL", "profit": -1}]}
    kw["regime_3state"] = "RANGE"
    alerts, state = evaluate(**kw)
    assert any("пауза предохранителя СНЯТА" in a for a in alerts)
    assert state["series_pause"] is False


def test_pause_holds_when_not_range():
    kw = _base({}, {})
    kw["state"] = {"series_pause": True, "stop_events": []}
    kw["regime_3state"] = "MARKDOWN"
    alerts, state = evaluate(**kw)
    assert not any("СНЯТА" in a for a in alerts)
    assert state["series_pause"] is True


def test_single_stop_no_pause():
    bots = {"5617871752": _slot("WLD", status=16, profit=-50.0, cur=-50.0)}
    kw = _base(bots, {"5617871752": _p()})
    kw["state"] = {"prev_active": {"5617871752": True},
                   "inactive": {"5617871752": {"since": (NOW - timedelta(minutes=5)).isoformat(), "pinged": False}}}
    alerts, state = evaluate(**kw)
    # один стоп — пинг об остановке есть, но предохранитель не сработал
    assert any("остановился" in a for a in alerts)
    assert not any("ПРЕДОХРАНИТЕЛЬ" in a for a in alerts)
    assert not state.get("series_pause")


def test_old_stops_expire_from_window():
    kw = _base({}, {})
    kw["state"] = {"stop_events": [
        {"ts": (NOW - timedelta(hours=30)).isoformat(), "bot": "A", "type": "STOP-TPSL", "profit": -1},
        {"ts": (NOW - timedelta(hours=28)).isoformat(), "bot": "B", "type": "STOP-TPSL", "profit": -1}]}
    alerts, state = evaluate(**kw)
    # оба старше 24ч окна → выпали, предохранитель не срабатывает
    assert not any("ПРЕДОХРАНИТЕЛЬ" in a for a in alerts)
    assert state["stop_events"] == []
