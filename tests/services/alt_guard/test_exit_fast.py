"""EXIT-FAST (Donchian+ATR+объём) + детектор резьюм-в-движении против позы."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from services.alt_guard.exit_fast import exit_fast
from services.alt_guard.loop import evaluate

NOW = datetime(2026, 6, 16, 0, 0, 0, tzinfo=timezone.utc)


def test_exit_fast_up_break():
    # 30 баров флэта ~70, потом взрывной бар вверх с объёмом
    highs = [70.2] * 30 + [73.0]
    lows = [69.8] * 30 + [71.0]
    closes = [70.0] * 30 + [72.8]      # пробой максимума 70.2, ход 2.8 >> ATR
    vols = [100.0] * 30 + [500.0]      # объём ×5 > 2.4
    fired, d = exit_fast(highs, lows, closes, vols, n=20)
    assert fired and d == 1


def test_exit_fast_no_fire_in_range():
    # обычные колебания — Donchian не пробит / объём в норме → 0 ложных
    highs = [70.2, 70.4] * 15 + [70.3]
    lows = [69.8, 69.6] * 15 + [69.9]
    closes = [70.0, 70.1] * 15 + [70.05]
    vols = [100.0] * 31
    fired, _ = exit_fast(highs, lows, closes, vols, n=20)
    assert not fired


def test_exit_fast_needs_all_three():
    # пробой есть, но объём в норме → НЕ fired (нужны все три)
    highs = [70.2] * 30 + [73.0]
    lows = [69.8] * 30 + [71.0]
    closes = [70.0] * 30 + [72.8]
    vols = [100.0] * 31              # без объёмного спайка
    fired, _ = exit_fast(highs, lows, closes, vols, n=20)
    assert not fired


def _slot(name, *, status=2, profit=130.0, cur=-12.0, position=-71.0):
    mk = lambda: {"bot_name": name, "status": status, "profit": profit, "current_profit": cur,
                  "position": position, "average_price": 69.0, "balance": 7500.0,
                  "liquidation_price": 0.0}
    return {"latest": mk(), "day0": mk(), "fresh": True}


def _p():
    return {"side": "3", "raw_params_json": json.dumps({"tsl": -175, "side": 3})}


def _base(bots, **kw):
    d = dict(snap={"bots": bots, "stale_min": 0.5}, params={b: _p() for b in bots},
             managed_ids=set(), deriv={}, xrp_px_1h_ago=None, cascade_dedup={},
             state={}, now=NOW)
    d.update(kw)
    return d


def test_exitfast_against_short_kill_switch():
    bots = {"5693279219": _slot("SOL", position=-71.0, cur=-12.0)}  # шорт, мешок<0
    kw = _base(bots)
    kw["exitfast"] = {"5693279219": (True, 1)}  # взрывной ход ВВЕРХ против шорта
    alerts, _ = evaluate(**kw)
    assert any("EXIT-FAST" in a and "ВВЕРХ ПРОТИВ ШОРТ" in a and "Kill-switch" in a for a in alerts)


def test_exitfast_aligned_no_ping():
    bots = {"5693279219": _slot("SOL", position=-71.0)}
    kw = _base(bots)
    kw["exitfast"] = {"5693279219": (True, -1)}  # ход ВНИЗ — ПО шорту, не против
    alerts, _ = evaluate(**kw)
    assert not any("EXIT-FAST" in a for a in alerts)


def test_exitfast_resume_variant():
    """Если бот только что резюмировался с висящей позой — рамка «не резюмируй»."""
    bots = {"5693279219": _slot("SOL", status=2, position=-71.0, cur=-12.0)}
    kw = _base(bots)
    kw["state"] = {"resumed_with_pos": {"5693279219": NOW.isoformat()}}
    kw["exitfast"] = {"5693279219": (True, 1)}
    alerts, _ = evaluate(**kw)
    assert any("РЕЗЬЮМЕ" in a and "SOL −350" in a and "НОВЫЙ бот" in a for a in alerts)
