"""Alt-Guard evaluate(): чистая логика на реальных формах данных трекера.

Форма slot/params — как из services.morning_brief.tracker_reader (строки CSV
2026-06-10: XRP/WLD/SOL живые альт-гриды, tsl=-175 в raw_params_json).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from services.alt_guard.loop import evaluate

NOW = datetime(2026, 6, 10, 15, 0, 0, tzinfo=timezone.utc)  # 18:00 мск


def _slot(name: str, *, status=2, profit=30.0, cur=30.0, day0_profit=0.0,
          day0_cur=0.0, position=-100.0):
    mk = lambda p, c: {"bot_name": name, "status": status, "profit": p,
                       "current_profit": c, "position": position,
                       "average_price": 1.0, "balance": 7500.0,
                       "liquidation_price": 0.0}
    return {"latest": mk(profit, cur), "day0": mk(day0_profit, day0_cur), "fresh": True}


def _params(side="3", tsl=-175):
    return {"side": side, "raw_params_json": json.dumps({"tsl": tsl, "side": int(side)})}


def _base(bots, params):
    return dict(snap={"bots": bots, "stale_min": 0.5}, params=params,
                managed_ids={"6287583200"}, deriv={}, xrp_px_1h_ago=None,
                cascade_dedup={}, state={}, now=NOW)


def test_net_close_ping_and_cooldown():
    bots = {"5617871752": _slot("WLD", profit=80.0, cur=75.0)}  # net дня = Δcur = +75
    params = {"5617871752": _params()}
    kw = _base(bots, params)
    alerts, state = evaluate(**kw)
    assert any("net дня +75$" in a and "закрыть руками" in a for a in alerts)
    # повтор в кулдауне — молчим
    kw["state"] = state
    alerts2, _ = evaluate(**kw)
    assert not any("закрыть руками" in a for a in alerts2)


def test_sl_warn_uses_tsl():
    # мешок −150 при tsl=-175 → 86% от SL → предупреждение
    bots = {"4306550166": _slot("XRP", profit=10.0, cur=-140.0)}
    params = {"4306550166": _params(tsl=-175)}
    alerts, _ = evaluate(**_base(bots, params))
    assert any("от SL −$175" in a for a in alerts)


def test_stopped_bot_pinged_once():
    bots = {"5693279219": _slot("SOL", status=12, profit=5.0, cur=-160.0)}
    params = {"5693279219": _params()}
    kw = _base(bots, params)
    kw["state"] = {"prev_active": {"5693279219": True}}
    alerts, state = evaluate(**kw)
    assert any("ОСТАНОВИЛСЯ" in a for a in alerts)
    kw["state"] = state  # второй тик — уже не активен в prev → молчим
    alerts2, _ = evaluate(**kw)
    assert not any("ОСТАНОВИЛСЯ" in a for a in alerts2)


def test_xrp_pump_guard_price_trigger():
    bots = {"4306550166": _slot("XRP")}
    params = {"4306550166": _params()}
    kw = _base(bots, params)
    kw["deriv"] = {"XRPUSDT": {"funding_rate_8h": -0.00005, "mark_price": 1.18}}
    kw["xrp_px_1h_ago"] = 1.13  # +4.4%/час
    alerts, _ = evaluate(**kw)
    assert any("памп-риск" in a and "short-ногу" in a for a in alerts)


def test_xrp_pump_guard_silent_without_xrp_bot():
    bots = {"5617871752": _slot("WLD")}
    params = {"5617871752": _params()}
    kw = _base(bots, params)
    kw["deriv"] = {"XRPUSDT": {"funding_rate_8h": -0.01, "mark_price": 1.18}}
    kw["xrp_px_1h_ago"] = 1.0
    alerts, _ = evaluate(**kw)
    assert not any("памп-риск" in a for a in alerts)


def test_cascade_correlation_ping():
    bots = {"5617871752": _slot("WLD"), "5693279219": _slot("SOL")}
    params = {"5617871752": _params(), "5693279219": _params()}
    kw = _base(bots, params)
    kw["cascade_dedup"] = {"short_5.0": (NOW - timedelta(minutes=2)).isoformat()}
    alerts, _ = evaluate(**kw)
    assert any("КОРРЕЛИРУЮТ" in a and "2 грида" in a for a in alerts)


def test_evening_check_once_per_day():
    now = datetime(2026, 6, 10, 20, 5, 0, tzinfo=timezone.utc)  # 23:05 мск
    bots = {"5617871752": _slot("WLD", profit=40.0, cur=20.0)}
    params = {"5617871752": _params()}
    kw = _base(bots, params)
    kw["now"] = now
    alerts, state = evaluate(**kw)
    assert any("НЕ оставляем на ночь" in a for a in alerts)
    kw["state"] = state
    alerts2, _ = evaluate(**kw)
    assert not any("НЕ оставляем" in a for a in alerts2)


def test_managed_and_non_dynamic_ignored():
    bots = {
        "6287583200": _slot("SHORT-T2", profit=200.0, cur=200.0),  # managed
        "5403878196": _slot("T1 GIN", profit=300.0, cur=300.0),    # side=2
    }
    params = {"6287583200": _params(side="2"), "5403878196": _params(side="2")}
    alerts, _ = evaluate(**_base(bots, params))
    assert alerts == []
