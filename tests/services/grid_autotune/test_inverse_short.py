"""Автотюнер на монетно-маржинальном BTC SHORT 5189290547.

Три отличия от линейных DYN-ботов, каждое ломало автоматику по-своему:
  * мешок приходит в МОНЕТЕ (масштаб 1e-4 BTC), а пороги долларовые;
  * position уже в долларовых контрактах — умножать на цену нельзя;
  * таргет трогать нельзя (оператор 17.08: «таргет шорту не трогай только
    шаг сетки»); 0.29 стоит вплотную к обрыву 0.29->0.34 (просадка ×27).

Числа с живого бота 17.08: позиция −20200 контрактов, средняя 63299.
_isolate импортируется как autouse-фикстура — все пути состояния уходят
в tmp_path, боевые файлы не трогаются.
"""
from __future__ import annotations

import json

from services.grid_autotune import loop as gat
from tests.services.grid_autotune.test_grid_autotune import (  # noqa: F401
    FakeAPI, _cfg, _events, _isolate)

SHORT = "5189290547"
AVG = 63299.0
BAG_BTC = -0.00031          # ≈ −$19.6


def _short_cfg(bot_over=None, **over):
    bots = {SHORT: {"alias": "BTC-SHORT-INV", "inverse": True,
                    "widen_target": False, "otc_expected": True,
                    "min_notional_usd": 500}}
    bots[SHORT].update(bot_over or {})
    _cfg(bots=bots, **over)


def _snap(bag_btc=BAG_BTC, position=-20200.0, status=2):
    return {SHORT: {"bag": bag_btc, "status": status, "position": position,
                    "avg_price": AVG, "notional": abs(position) * AVG}}


def _api():
    return FakeAPI(gs=0.03, tog=0.29,
                   extra={"in": {"otc": True, "otcPassed": True}})


def _applied():
    for line in gat.JOURNAL_PATH.read_text().splitlines():
        rec = json.loads(line)
        if rec.get("event") == "APPLIED":
            return rec
    return None


def test_target_untouched_step_widened():
    """Главное требование оператора: шаг ×1.3, таргет как был."""
    _short_cfg()
    api = _api()
    sent = []
    n = gat.tick(send_fn=sent.append, api=api, drift={SHORT: 2}, bags=_snap())
    assert n == 1
    gs, tog, _ = api.set_calls[0]
    assert gs == 0.039                      # 0.03 × 1.3
    assert tog == 0.29                      # НЕ тронут
    assert tog < 0.34, "таргет не должен переходить обрыв 0.29->0.34"


def test_linear_bots_still_widen_both():
    """Регрессия: у обычных ботов по-прежнему растут и шаг, и таргет."""
    _cfg(bots={"42": {"alias": "ETH-DYN"}})
    api = FakeAPI(gs=0.1, tog=0.85)
    n = gat.tick(send_fn=[].append, api=api, drift={"42": 2},
                 bags={"42": {"bag": -150.0, "status": 2}})
    assert n == 1
    assert api.set_calls == [(0.13, 1.105, None)]


def test_bag_converted_to_usd_so_episode_can_open():
    """Без перевода мешок −0.00031 BTC сравнивался бы с −$20 как «мелкий»,
    эпизод не открылся бы никогда."""
    _short_cfg()
    n = gat.tick(send_fn=[].append, api=_api(), drift={SHORT: 2}, bags=_snap())
    assert n == 1
    rec = _applied()
    assert rec is not None
    assert -20.5 < rec["bag"] < -19.0, \
        f"мешок должен быть в долларах, а он {rec['bag']}"


def test_shallow_bag_in_coin_allows_restore():
    """Успокоение считается по тем же долларам: −0.0001 BTC = −$6.3."""
    _short_cfg()
    gat.ACTIVE_PATH.write_text(json.dumps(
        {SHORT: {"orig": {"gs": 0.03, "tog": 0.29}, "applied_ts": "x",
                 "widen_pct": 30}}), encoding="utf-8")
    api = FakeAPI(gs=0.039, tog=0.29,
                  extra={"in": {"otc": True, "otcPassed": True}})
    n = gat.tick(send_fn=[].append, api=api, drift={SHORT: 0},
                 bags=_snap(bag_btc=-0.0001))
    assert n == 1
    assert api.set_calls[0][:2] == (0.03, 0.29)      # откат шага
    assert "RESTORED" in _events()


def test_deep_bag_in_coin_blocks_restore():
    """−0.0006 BTC = −$38, глубже порога −$20 — откатывать рано."""
    _short_cfg()
    gat.ACTIVE_PATH.write_text(json.dumps(
        {SHORT: {"orig": {"gs": 0.03, "tog": 0.29}, "applied_ts": "x",
                 "widen_pct": 30}}), encoding="utf-8")
    api = FakeAPI(gs=0.039, tog=0.29,
                  extra={"in": {"otc": True, "otcPassed": True}})
    n = gat.tick(send_fn=[].append, api=api, drift={SHORT: 0},
                 bags=_snap(bag_btc=-0.0006))
    assert n == 0
    assert not api.set_calls


def test_notional_gate_uses_dollars():
    """position уже в долларах: $300 ниже гейта $500 и трогать бота не надо,
    хотя ×avg_price дало бы $19 млн и гейт бы «прошёл»."""
    _short_cfg()
    api = _api()
    n = gat.tick(send_fn=[].append, api=api, drift={SHORT: 2},
                 bags=_snap(position=-300.0))
    assert n == 0
    assert not api.set_calls


def test_move_direction_up_only_fires_on_rise(monkeypatch):
    """Шорту вредит только рост. Падение 1.2% триггером быть не должно."""
    _short_cfg(bot_over={"trigger": "btc_move_1h", "move_pct_1h": 0.8,
                         "move_direction": "up"})
    for signed, expect in ((+1.2, 1), (-1.2, 0)):
        gat.ACTIVE_PATH.write_text("{}", encoding="utf-8")
        def _fake_move(s=signed, **kw):
            return {"move_1h_pct": abs(s), "move_1h_signed": s,
                    "max_move_calm_pct": abs(s)}
        monkeypatch.setattr(gat, "read_btc_move", _fake_move)
        api = _api()
        n = gat.tick(send_fn=[].append, api=api, drift={}, bags=_snap())
        assert n == expect, f"движение {signed:+.1f}% -> ожидалось {expect}"
        if expect:
            assert api.set_calls[0][0] == 0.039     # шаг расширен
            assert api.set_calls[0][1] == 0.29      # таргет цел


def test_otc_passed_reset_is_caught():
    """set_params может сбросить otcPassed (инцидент 17.05) — верификация
    обязана поймать это и остановить сервис."""
    _short_cfg()
    api = _api()
    api.flip_otc_on_set = True
    sent = []
    n = gat.tick(send_fn=sent.append, api=api, drift={SHORT: 2}, bags=_snap())
    assert n == 0
    assert gat.FROZEN_PATH.exists()
