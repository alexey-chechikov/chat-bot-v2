"""Портфельный контроль убытка.

Каждый тест здесь соответствует конкретному звену ликвидации 19-22.08 —
если он падает, значит вернулось то, что уже один раз стоило счёта.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from services.risk_guard import loop as rg

NOW = datetime.now(timezone.utc)
BTC, ETH = "4696727145", "4470088018"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(rg, "CONFIG_PATH", tmp_path / "cfg.json")
    monkeypatch.setattr(rg, "JOURNAL_PATH", tmp_path / "journal.jsonl")
    monkeypatch.setattr(rg, "FROZEN_PATH", tmp_path / "frozen.json")
    # без изоляции состояние антиспама переживало между тестами и глушило
    # тревогу в соседнем
    monkeypatch.setattr(rg, "ALERT_STATE", tmp_path / "alert.json")
    monkeypatch.setattr(rg, "_price_of", lambda api, inst: PRICES.get(inst))
    monkeypatch.setattr("services.short_bots_guard.control.pause_bot",
                        lambda bot_id, **kw: {"action": "paused"})


PRICES = {"BTC-USDT-SWAP": 76_850.0, "ETH-USDT-SWAP": 2_410.0,
          "BTC-USD-SWAP": 76_850.0}


def _cfg(tmp=None, **over):
    cfg = {
        "enabled": True, "deposit_usd": 2160.0,
        "warn_pct": 10, "kill_pct": 20, "max_leverage": 1.0,
        "max_stale_minutes": 15,
        "bots": {
            BTC: {"alias": "BTC_c_c", "inst_id": "BTC-USDT-SWAP"},
            ETH: {"alias": "ETH_c", "inst_id": "ETH-USDT-SWAP"},
        },
    }
    cfg.update(over)
    rg.CONFIG_PATH.write_text(json.dumps(cfg), encoding="utf-8")
    return cfg


def _bot(bid, pos, profit, cur, status=2, age_min=1.0):
    stat = SimpleNamespace(position=pos, profit=profit, currentProfit=cur,
                           updatedAt=NOW - timedelta(minutes=age_min))
    return SimpleNamespace(id=int(bid), status=status, stat=stat)


class FakeAPI:
    def __init__(self, bots):
        self._bots = bots
        self.closed: list[int] = []

    def list_bots(self):
        return self._bots

    def close_position(self, bot_id):
        self.closed.append(int(bot_id))
        return {}


def _events():
    if not rg.JOURNAL_PATH.exists():
        return []
    return [json.loads(l) for l in rg.JOURNAL_PATH.read_text().splitlines()]


# ─── арифметика ──────────────────────────────────────────────────────────
def test_snapshot_sums_across_bots():
    """Мешки складываются: поодиночке терпимо, вместе — предел."""
    cfg = _cfg()
    api = FakeAPI([_bot(BTC, -0.0384, 0.0, -120.0),
                   _bot(ETH, -0.502, 2.34, -80.0)])
    s = rg.snapshot(api, cfg)
    assert s["total_unrealized_usd"] == pytest.approx(-202.34, abs=0.01)
    # 0.0384×76850 + 0.502×2410 = 2951 + 1210
    assert s["total_notional_usd"] == pytest.approx(4161.0, abs=2.0)
    assert s["leverage"] == pytest.approx(1.93, abs=0.02)


def test_inverse_bot_uses_contracts_and_coin_bag():
    """У инверсного позиция уже в долларах, мешок в монете."""
    cfg = _cfg(bots={BTC: {"alias": "SHORT", "inst_id": "BTC-USD-SWAP",
                           "inverse": True}})
    api = FakeAPI([_bot(BTC, -31_000.0, 0.001, -0.079)])
    s = rg.snapshot(api, cfg)
    assert s["total_notional_usd"] == pytest.approx(31_000.0)
    assert s["total_unrealized_usd"] == pytest.approx(-0.08 * 76_850, abs=50)


# ─── ступени ─────────────────────────────────────────────────────────────
def test_within_limits_does_nothing():
    cfg = _cfg(max_leverage=5.0)
    api = FakeAPI([_bot(BTC, -0.001, 0.0, -5.0)])
    assert rg.evaluate(rg.snapshot(api, cfg), cfg)["action"] == "NONE"


def test_warn_halts_but_does_not_close():
    """−10%: тормозим набор, позицию НЕ трогаем — на истории оттуда
    мешок дважды из шести возвращался сам."""
    cfg = _cfg(max_leverage=99)
    api = FakeAPI([_bot(BTC, -0.001, 0.0, -250.0)])   # −11.6% от 2160
    assert rg.tick(api=api) == "halt"
    assert api.closed == []
    assert _events()[-1]["event"] == "HALT"


def test_limit_without_allow_close_only_pauses():
    """Оператор 27.08: «без закрытий — только пауза ботов и предупреждение».

    Предел убытка достигнут, но закрытие выключено: боты встают,
    позиции остаются, приходит тревога.
    """
    _cfg(max_leverage=99)          # allow_close отсутствует = выключено
    api = FakeAPI([_bot(BTC, -0.0384, 0.0, -300.0),
                   _bot(ETH, -0.502, 0.0, -200.0)])
    sent = []
    assert rg.tick(api=api, send_fn=sent.append) == "limit_no_close"
    assert api.closed == [], "позиции трогать нельзя"
    assert not rg.is_frozen(), "служба должна продолжать следить"
    ev = _events()[-1]
    assert ev["event"] == "LIMIT_NO_CLOSE"
    assert sent and "НЕ ЗАКРЫТЫ" in sent[0]


def test_alert_is_not_spammed_every_tick():
    """Порог держится часами, тик раз в минуту — тревога не должна
    повторяться каждый раз, иначе её перестанут читать."""
    _cfg(max_leverage=99, alert_gap_minutes=30)
    api = FakeAPI([_bot(BTC, -0.0384, 0.0, -600.0)])
    sent = []
    for _ in range(5):
        rg.tick(api=api, send_fn=sent.append)
    assert len(sent) == 1, f"ожидали одну тревогу, пришло {len(sent)}"


def test_kill_closes_everything():
    """−20% с ЯВНО включённым закрытием. 4 из 4 эпизодов углублялись."""
    cfg = _cfg(max_leverage=99, allow_close=True)
    api = FakeAPI([_bot(BTC, -0.0384, 0.0, -300.0),
                   _bot(ETH, -0.502, 0.0, -200.0)])   # −23% от 2160
    assert rg.tick(api=api) == "kill"
    assert sorted(api.closed) == sorted([int(BTC), int(ETH)])
    ev = _events()[-1]
    assert ev["event"] == "KILL"
    assert rg.is_frozen(), "после KILL служба обязана замереть"


def test_kill_wins_over_stale():
    """Убыток за пределом важнее любых оговорок про данные."""
    cfg = _cfg(max_leverage=99, allow_close=True)
    api = FakeAPI([_bot(BTC, -0.0384, 0.0, -600.0, age_min=999)])
    assert rg.tick(api=api) == "kill"
    assert api.closed == [int(BTC)]


def test_close_is_off_by_default_in_shipped_config():
    """Боевой конфиг не должен уметь закрывать без явного разрешения."""
    import json as _json
    from pathlib import Path as _P

    live = _json.loads((_P(rg.ROOT) / "state" / "risk_guard_config.json")
                       .read_text(encoding="utf-8"))
    assert live.get("allow_close") is not True, \
        "закрытие в боевом конфиге включено — оператор этого не разрешал"


# ─── уроки 22.08 ─────────────────────────────────────────────────────────
def test_stale_data_halts_instead_of_reporting_calm():
    """22.08 я принял 22-часовой кэш за живое состояние и сказал, что
    позиции целы, когда их уже ликвидировали."""
    cfg = _cfg(max_leverage=99)
    api = FakeAPI([_bot(BTC, -0.001, 0.0, -1.0, age_min=22 * 60)])
    assert rg.tick(api=api) == "halt"
    assert "устарели" in _events()[-1]["reason"]
    assert api.closed == []


def test_missing_price_halts_not_guesses():
    cfg = _cfg(bots={BTC: {"alias": "X", "inst_id": "НЕТ-ТАКОГО"}})
    api = FakeAPI([_bot(BTC, -0.001, 0.0, -1.0)])
    assert rg.tick(api=api) == "halt"
    assert "нет цены" in _events()[-1]["reason"]


def test_leverage_cap_halts_before_loss_appears():
    """Экспозиция ловится ДО убытка: 19.08 плечо было 8.8x при мешке −$46."""
    cfg = _cfg()
    api = FakeAPI([_bot(BTC, -0.0384, 0.0, -5.0),
                   _bot(ETH, -0.502, 0.0, -5.0)])     # 1.93x при пределе 1.0
    assert rg.tick(api=api) == "halt"
    assert "экспозиция" in _events()[-1]["reason"]
    assert api.closed == []


def test_api_failure_halts():
    _cfg()

    class Broken:
        def list_bots(self):
            raise RuntimeError("сеть")

    assert rg.tick(api=Broken()) == "halt"


# ─── выключатели ─────────────────────────────────────────────────────────
def test_disabled_does_nothing():
    _cfg(enabled=False)
    api = FakeAPI([_bot(BTC, -1.0, 0.0, -9999.0)])
    assert rg.tick(api=api) == "disabled"
    assert api.closed == []


def test_frozen_does_nothing():
    _cfg()
    rg.freeze("тест")
    api = FakeAPI([_bot(BTC, -1.0, 0.0, -9999.0)])
    assert rg.tick(api=api) == "frozen"
    assert api.closed == []


def test_unknown_bots_are_ignored():
    """Считаем только тех, кто заведён — чужой бот не должен ронять счёт."""
    cfg = _cfg(max_leverage=99)
    api = FakeAPI([_bot(BTC, -0.001, 0.0, -5.0),
                   _bot("9999999999", -50.0, 0.0, -99_999.0)])
    s = rg.snapshot(api, cfg)
    assert s["total_unrealized_usd"] == pytest.approx(-5.0)


def test_stopped_bots_are_ignored():
    cfg = _cfg(max_leverage=99)
    api = FakeAPI([_bot(BTC, -0.001, 0.0, -5.0),
                   _bot(ETH, -9.0, 0.0, -9999.0, status=12)])
    s = rg.snapshot(api, cfg)
    assert s["total_unrealized_usd"] == pytest.approx(-5.0)


def test_close_position_is_denied_outside_risk_guard():
    """Аварийный тормоз не должен быть доступен обычному коду."""
    from services.ginarea_api.bots import BotsAPI
    from services.ginarea_api.exceptions import GinAreaProductionBotGuardError

    api = BotsAPI(client=SimpleNamespace(request=lambda *a, **k: {}))
    with pytest.raises(GinAreaProductionBotGuardError):
        api.close_position(123)
