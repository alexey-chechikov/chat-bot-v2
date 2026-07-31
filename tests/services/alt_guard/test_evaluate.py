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
    # 2026-07-31: выставленный tsl по-прежнему главнее пропорционального порога
    # (формулировка «от SL» → «от порога»: у ботов OKX стопа нет вообще)
    bots = {"4306550166": _slot("XRP", profit=10.0, cur=-140.0)}
    params = {"4306550166": _params(tsl=-175)}
    alerts, _ = evaluate(**_base(bots, params))
    assert any("от порога −$175" in a for a in alerts)


def test_stopped_bot_debounced_then_pinged_with_status():
    """SOL-урок 2026-06-11: статус 13 на 1 мин (рестарт цикла) — НЕ пинговать.
    Пинг только после 3 мин не-активности, с расшифровкой статуса."""
    from datetime import timedelta
    bots = {"5693279219": _slot("SOL", status=16, profit=5.0, cur=-160.0)}
    params = {"5693279219": _params()}
    kw = _base(bots, params)
    kw["state"] = {"prev_active": {"5693279219": True}}
    # тик 1: только что не-активен → молчим (дебаунс)
    alerts1, state = evaluate(**kw)
    assert not any("остановился" in a for a in alerts1)
    # тик 2: +4 мин всё ещё не-активен → пинг с расшифровкой статуса 16
    kw["state"] = state
    kw["now"] = NOW + timedelta(minutes=4)
    alerts2, state2 = evaluate(**kw)
    assert any("остановился — стоп (TP/SL)" in a for a in alerts2)
    # тик 3: повтора нет
    kw["state"] = state2
    kw["now"] = NOW + timedelta(minutes=5)
    alerts3, _ = evaluate(**kw)
    assert not any("остановился" in a for a in alerts3)


def test_cycle_restart_no_ping_and_resume_after_real_stop():
    """Транзиент (1 мин) молчит; после реального стопа возврат в актив → «СНОВА АКТИВЕН»."""
    from datetime import timedelta
    params = {"5693279219": _params()}
    # транзиент: не-активен 1 тик → снова активен, пинга не было → и «возобновился» не шлём
    kw = _base({"5693279219": _slot("SOL", status=13)}, params)
    kw["state"] = {"prev_active": {"5693279219": True}}
    _a1, st = evaluate(**kw)
    kw2 = _base({"5693279219": _slot("SOL", status=2)}, params)
    kw2["state"] = st
    kw2["now"] = NOW + timedelta(minutes=1)
    alerts, st2 = evaluate(**kw2)
    assert not any("СНОВА АКТИВЕН" in a for a in alerts)
    # реальный стоп ≥3 мин (пинг был) → возврат в актив → «СНОВА АКТИВЕН»
    kw3 = _base({"5693279219": _slot("SOL", status=16)}, params)
    kw3["state"] = st2
    kw3["now"] = NOW + timedelta(minutes=2)
    _a3, st3 = evaluate(**kw3)
    kw4 = dict(kw3, now=NOW + timedelta(minutes=6))
    kw4["state"] = st3
    a4, st4 = evaluate(**kw4)
    assert any("остановился" in a for a in a4)
    kw5 = _base({"5693279219": _slot("SOL", status=2)}, params)
    kw5["state"] = st4
    kw5["now"] = NOW + timedelta(minutes=7)
    a5, _ = evaluate(**kw5)
    assert any("СНОВА АКТИВЕН" in a for a in a5)


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


def test_regime_leg_against_markdown():
    """WLD-урок: лонг-нога в MARKDOWN с мешком ≥40% SL → ранний пинг (до 80%)."""
    # бот в лонг-ноге (+694), мешок −80 (46% от SL −175)
    bots = {"4306550166": _slot("XRP", profit=14.0, cur=-66.0, position=694.0)}
    params = {"4306550166": _params(tsl=-175)}
    kw = _base(bots, params)
    kw["regime_3state"] = "MARKDOWN"
    alerts, state = evaluate(**kw)
    assert any("ПРОТИВ режима" in a and "ЛОНГ-нога" in a for a in alerts)
    # обычный slwarn (80%) при этом НЕ сработал — мешок только −80
    assert not any("Решай: дождаться SL" in a for a in alerts)
    # кулдаун
    kw["state"] = state
    alerts2, _ = evaluate(**kw)
    assert not any("ПРОТИВ режима" in a for a in alerts2)


def test_regime_leg_silent_when_aligned_or_range():
    bots = {"4306550166": _slot("XRP", profit=14.0, cur=-66.0, position=-694.0)}
    params = {"4306550166": _params(tsl=-175)}
    kw = _base(bots, params)
    kw["regime_3state"] = "MARKDOWN"  # шорт-нога ПО режиму → молчим
    alerts, _ = evaluate(**kw)
    assert not any("ПРОТИВ режима" in a for a in alerts)
    kw2 = _base({"4306550166": _slot("XRP", profit=14.0, cur=-66.0, position=694.0)},
                params)
    kw2["regime_3state"] = "RANGE"  # рейндж → гейт не активен
    alerts2, _ = evaluate(**kw2)
    assert not any("ПРОТИВ режима" in a for a in alerts2)


def test_drift_ladder_pings_on_transitions():
    """StageAlerter-дедуп (Win f337990): пинг на переходе вверх; та же стадия молчит."""
    bots = {"4306550166": _slot("XRP", profit=10.0, cur=-120.0)}
    params = {"4306550166": _params()}
    mx = {"bag_pct": 0.82, "pos_pin": 1.0, "bag": -143.0, "total": -78.0,
          "bag_accel": -12.0, "pinned_neg_min": 185}
    kw = _base(bots, params)
    kw["drift"] = {"4306550166": (3, "ЗАКРЫТЬ бота — стойкий дрифтер", mx)}
    alerts, state = evaluate(**kw)
    assert any("DRIFT Stage 3" in a and "ЗАКРЫТЬ" in a and "82% SL" in a for a in alerts)
    assert any("пригвождён<0 185м" in a for a in alerts)  # новое поле
    # та же Stage 3 сразу — дедуп молчит (напоминание раз в час)
    kw["state"] = state
    alerts2, state2 = evaluate(**kw)
    assert not any("DRIFT" in a for a in alerts2)


def test_drift_stage3_remind_4h_not_hourly():
    """2026-07-20 (ETH-эпизод = 96 пингов): Stage-3 напоминается раз в 4 часа.
    Через 65 мин — молчит, через 4ч05м — напоминает."""
    from datetime import timedelta
    bots = {"4306550166": _slot("XRP", profit=10.0, cur=-120.0)}
    params = {"4306550166": _params()}
    mx = {"bag_pct": 0.82, "pos_pin": 1.0, "bag": -143.0, "total": -78.0,
          "bag_accel": -12.0, "pinned_neg_min": 185}
    kw = _base(bots, params)
    kw["drift"] = {"4306550166": (3, "ЗАКРЫТЬ", mx)}
    _a, state = evaluate(**kw)
    # +65 мин той же Stage 3 → МОЛЧИТ (было: напоминание каждый час = спам)
    kw["state"] = state
    kw["now"] = NOW + timedelta(minutes=65)
    a2, state = evaluate(**kw)
    assert not any("DRIFT Stage 3" in a for a in a2)
    # +4ч05м → напоминание
    kw["state"] = state
    kw["now"] = NOW + timedelta(hours=4, minutes=5)
    a3, _ = evaluate(**kw)
    assert any("DRIFT Stage 3" in a for a in a3)


def test_drift_recover_to_healthy_pings_once():
    """Спад ≥2→0 = «дрифт снят» (один раз)."""
    bots = {"5617871752": _slot("WLD", profit=50.0, cur=-52.0)}
    params = {"5617871752": _params()}
    mx2 = {"bag_pct": 0.58, "pos_pin": 1.0, "bag": -102.0, "total": -68.0,
           "bag_accel": -9.0, "pinned_neg_min": 30}
    kw = _base(bots, params)
    kw["drift"] = {"5617871752": (2, "РАСШИРИТЬ step/target ×2", mx2)}
    a1, state = evaluate(**kw)
    assert any("Stage 2" in a and "сам сделает" in a for a in a1)
    # восстановился в healthy
    kw["state"] = state
    kw["drift"] = {"5617871752": (0, "healthy", dict(mx2, bag_pct=0.1, total=20.0))}
    a2, _ = evaluate(**kw)
    assert any("DRIFT снят" in a for a in a2)


def test_decorr_ping_both_directions():
    """Win-ретро: excess ≤ −3% (лонг-нога) или ≥ +3% (шорт-нога) → 🟠 DECORR."""
    params = {"5617871752": _params()}
    kw = _base({"5617871752": _slot("WLD")}, params)
    kw["idio"] = {"5617871752": -3.4}
    alerts, state = evaluate(**kw)
    assert any("DECORR" in a and "вниз" in a and "ЛОНГ-нога" in a for a in alerts)
    # кулдаун: повтор молчит
    kw["state"] = state
    alerts2, _ = evaluate(**kw)
    assert not any("DECORR" in a for a in alerts2)
    # вверх — шорт-нога
    kw3 = _base({"5693279219": _slot("SOL")}, {"5693279219": _params()})
    kw3["idio"] = {"5693279219": 3.8}
    alerts3, _ = evaluate(**kw3)
    assert any("DECORR" in a and "вверх" in a and "ШОРТ-нога" in a for a in alerts3)
    # слабый excess — тишина
    kw4 = _base({"5693279219": _slot("SOL")}, {"5693279219": _params()})
    kw4["idio"] = {"5693279219": -1.2}
    alerts4, _ = evaluate(**kw4)
    assert not any("DECORR" in a for a in alerts4)


def test_portfolio_day_gate_once():
    """∑net альтов ≤ −$90 → гейт «новые не открывать», раз в день."""
    bots = {
        "5617871752": _slot("WLD", profit=5.0, cur=-60.0),   # net −60
        "5693279219": _slot("SOL", profit=5.0, cur=-40.0),   # net −40
    }
    params = {"5617871752": _params(), "5693279219": _params()}
    kw = _base(bots, params)
    alerts, state = evaluate(**kw)
    assert any("портфельный гейт" in a and "не открывать" in a for a in alerts)
    kw["state"] = state
    alerts2, _ = evaluate(**kw)
    assert not any("портфельный гейт" in a for a in alerts2)


def test_managed_and_non_dynamic_ignored():
    bots = {
        "6287583200": _slot("SHORT-T2", profit=200.0, cur=200.0),  # managed
        "5403878196": _slot("T1 GIN", profit=300.0, cur=300.0),    # side=2
    }
    params = {"6287583200": _params(side="2"), "5403878196": _params(side="2")}
    alerts, _ = evaluate(**_base(bots, params))
    assert alerts == []


def test_drift_stage2_says_already_widened_when_episode_open(monkeypatch):
    """2026-07-21: пинг обещал «сделает +30%», хотя сетка уже расширена.
    2026-07-22: при открытом эпизоде пинг вообще молчит до подхода к SL —
    поэтому проверяем текст на мешке у SL (0.92), где он снова звучит."""
    import services.alt_guard.loop as al
    monkeypatch.setattr(al, "_autotune_active", lambda bid: True)
    bots = {"5617871752": _slot("WLD", profit=50.0, cur=-52.0)}
    params = {"5617871752": _params()}
    mx = {"bag_pct": 0.92, "pos_pin": 1.0, "bag": -161.0, "total": -68.0,
          "bag_accel": -9.0, "pinned_neg_min": 30}
    kw = _base(bots, params)
    kw["drift"] = {"5617871752": (2, "РАСШИРИТЬ step/target x2", mx)}
    alerts, _ = evaluate(**kw)
    assert any("уже расширен" in a for a in alerts)
    assert not any("сам сделает" in a for a in alerts)


def test_drift_muted_while_autotune_holds_episode(monkeypatch):
    """2026-07-22: пинг просил «РАСШИРИТЬ», хотя автоширитель уже расширил —
    чистый шум. Пока эпизод открыт и мешок не у SL, молчим."""
    import services.alt_guard.loop as al
    monkeypatch.setattr(al, "_autotune_active", lambda bid: True)
    bots = {"5617871752": _slot("WLD", profit=50.0, cur=-52.0)}
    params = {"5617871752": _params()}
    mx = {"bag_pct": 0.57, "pos_pin": 0.95, "bag": -100.0, "total": -25.0,
          "bag_accel": -5.0, "pinned_neg_min": 239}
    kw = _base(bots, params)
    kw["drift"] = {"5617871752": (2, "РАСШИРИТЬ step/target x2", mx)}
    alerts, _ = evaluate(**kw)
    assert not any("DRIFT" in a for a in alerts)


def test_drift_speaks_again_near_sl_even_with_episode(monkeypatch):
    """У SL рычаг автоширителя исчерпан — решение снова оператора."""
    import services.alt_guard.loop as al
    monkeypatch.setattr(al, "_autotune_active", lambda bid: True)
    bots = {"5617871752": _slot("WLD", profit=50.0, cur=-52.0)}
    params = {"5617871752": _params()}
    mx = {"bag_pct": 0.95, "pos_pin": 1.0, "bag": -166.0, "total": -90.0,
          "bag_accel": -12.0, "pinned_neg_min": 300}
    kw = _base(bots, params)
    kw["drift"] = {"5617871752": (3, "ЗАКРЫТЬ", mx)}
    alerts, _ = evaluate(**kw)
    assert any("DRIFT Stage 3" in a for a in alerts)
