"""Grid Autotune: авто-расширение gs/target при drift Stage>=2 + откат.

ВСЕ пути состояния подменяются в tmp_path — сервис мутирует живых ботов,
тесты не должны трогать ни боевые файлы, ни API.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from services.grid_autotune import loop as gat


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(gat, "CONFIG_PATH", tmp_path / "cfg.json")
    monkeypatch.setattr(gat, "ACTIVE_PATH", tmp_path / "active.json")
    monkeypatch.setattr(gat, "JOURNAL_PATH", tmp_path / "journal.jsonl")
    monkeypatch.setattr(gat, "FROZEN_PATH", tmp_path / "frozen.json")
    gat._last_episode_mono.clear()
    gat._api_cache.clear()


def _cfg(tmp=None, **over):
    cfg = {
        "enabled": True, "widen_pct": 30, "trigger_stage": 2,
        "restore_bag_usd": -20.0, "max_episodes_per_day_per_bot": 2,
        "min_gap_between_episodes_sec": 7200,
        "bots": {"42": {"alias": "ETH-DYN"}},
    }
    cfg.update(over)
    gat.CONFIG_PATH.write_text(json.dumps(cfg), encoding="utf-8")


def _real_params(gs, tog, maxq, extra):
    """НАСТОЯЩИЙ DefaultGridParams (frozen+slots) — ловит FrozenInstanceError,
    которую SimpleNamespace-фейк пропускал (баг 2026-07-21)."""
    from services.ginarea_api.models import DefaultGridParams
    d = {"gs": gs, "side": 3, "p": True, "obap": True,
         "gap": {"tog": tog, "minS": 0.01, "maxS": 0.1},
         "q": {"minQ": None, "maxQ": maxq, "qr": 1.1},
         "tr": {"tr": 0}}
    d.update(extra or {})
    return DefaultGridParams.from_dict(d)


class FakeAPI:
    def __init__(self, gs=0.1, tog=0.85, p=True, extra=None, status=2,
                 maxq=None):
        self.params = _real_params(gs, tog, maxq, extra)
        self.status = status
        self.set_calls: list[tuple] = []
        self.set_raises = None
        self.flip_otc_on_set = False   # симуляция сброса otcPassed записью

    def get_params(self, bot_id):
        return self.params

    def set_params(self, bot_id, params):
        maxq = params.q.maxQ
        self.set_calls.append((round(params.gs, 4), round(params.gap.tog, 4),
                               float(maxq) if maxq is not None else None))
        if self.flip_otc_on_set and (params.extra_raw or {}).get("in"):
            # extra_raw — dict, общий с исходным инстансом; мутируем содержимое
            params.extra_raw["in"] = dict(params.extra_raw["in"],
                                          otcPassed=False)
        self.params = params    # re-read вернёт записанное (как реальный API)
        if self.set_raises:
            raise self.set_raises

    def get_bot(self, bot_id):
        return SimpleNamespace(status=self.status)


def _events():
    return [json.loads(l)["event"]
            for l in gat.JOURNAL_PATH.read_text().splitlines()]


def test_widen_on_stage2(tmp_path):
    _cfg()
    api = FakeAPI(gs=0.1, tog=0.85)
    sent = []
    n = gat.tick(send_fn=sent.append, api=api,
                 drift={"42": 2}, bags={"42": {"bag": -150.0, "status": 2}})
    assert n == 1
    assert api.set_calls == [(0.13, 1.105, None)]     # +30%
    assert "APPLIED" in _events()
    active = json.loads(gat.ACTIVE_PATH.read_text())
    assert active["42"]["orig"] == {"gs": 0.1, "tog": 0.85}
    assert sent and "АВТОШИРЕНИЕ" in sent[0] and "0.13" in sent[0]


def test_restore_after_recovery(tmp_path):
    _cfg()
    gat.ACTIVE_PATH.write_text(json.dumps(
        {"42": {"orig": {"gs": 0.1, "tog": 0.85}, "applied_ts": "x",
                "widen_pct": 30}}), encoding="utf-8")
    api = FakeAPI(gs=0.13, tog=1.105)
    sent = []
    n = gat.tick(send_fn=sent.append, api=api,
                 drift={"42": 0}, bags={"42": {"bag": -5.0, "status": 2}})
    assert n == 1
    assert api.set_calls == [(0.1, 0.85, None)]       # откат к исходным
    assert "RESTORED" in _events()
    assert json.loads(gat.ACTIVE_PATH.read_text()) == {}
    assert sent and "вернул" in sent[0]


def test_no_restore_while_bag_deep(tmp_path):
    _cfg()
    gat.ACTIVE_PATH.write_text(json.dumps(
        {"42": {"orig": {"gs": 0.1, "tog": 0.85}, "applied_ts": "x",
                "widen_pct": 30}}), encoding="utf-8")
    api = FakeAPI()
    n = gat.tick(api=api, drift={"42": 0},
                 bags={"42": {"bag": -300.0, "status": 2}})
    assert n == 0 and not api.set_calls               # мешок глубоко — ждём


def test_verify_failure_freezes_and_rolls_back(tmp_path):
    """set_params прошёл, но бот не Active → откат + freeze + CRITICAL."""
    _cfg()
    api = FakeAPI(status=10)                          # FAILED после записи
    sent = []
    n = gat.tick(send_fn=sent.append, api=api,
                 drift={"42": 2}, bags={"42": {"bag": -150.0, "status": 2}})
    assert n == 0
    assert gat.is_frozen()
    # два вызова: попытка widen + rollback на исходные
    assert api.set_calls == [(0.13, 1.105, None), (0.1, 0.85, None)]
    assert any("КРИТИЧНО" in s for s in sent)
    assert "APPLY_FAILED" in _events()


def test_otc_guard_freezes_without_write(tmp_path):
    _cfg()
    api = FakeAPI(extra={"in": {"otc": True}})
    sent = []
    n = gat.tick(send_fn=sent.append, api=api,
                 drift={"42": 2}, bags={"42": {"bag": -150.0, "status": 2}})
    assert n == 0
    assert gat.is_frozen() and not api.set_calls
    assert sent and "ЗАМОРОЖЕН" in sent[0]


def test_disabled_and_low_stage_do_nothing(tmp_path):
    _cfg(enabled=False)
    api = FakeAPI()
    assert gat.tick(api=api, drift={"42": 3},
                    bags={"42": {"bag": -500.0, "status": 2}}) == 0
    _cfg()  # enabled, но stage 1 < trigger 2
    assert gat.tick(api=api, drift={"42": 1},
                    bags={"42": {"bag": -500.0, "status": 2}}) == 0
    # и не-Active бот не трогаем
    assert gat.tick(api=api, drift={"42": 3},
                    bags={"42": {"bag": -500.0, "status": 12}}) == 0
    assert not api.set_calls


def test_daily_cap(tmp_path):
    _cfg(max_episodes_per_day_per_bot=0)
    api = FakeAPI()
    assert gat.tick(api=api, drift={"42": 2},
                    bags={"42": {"bag": -150.0, "status": 2}}) == 0
    assert not api.set_calls


BTCLONG_BOT = {
    "5317457827": {
        "alias": "BTC-LONG", "trigger": "btc_move_1h", "move_pct_1h": 0.8,
        "calm_hours": 4, "min_abs_position": 5500, "episode_maxQ": 100,
        "quiet_maxQ": 300, "restore_bag": -0.0003, "otc_expected": True,
    }
}


def _btclong_api(gs=0.09, tog=0.77, maxq=300, **kw):
    return FakeAPI(gs=gs, tog=tog, maxq=maxq,
                   extra={"in": {"otc": True, "otcPassed": True}}, **kw)


def test_btc_move_widens_and_cuts_order_size(tmp_path, monkeypatch):
    """Оператор: сильное движение BTC → ордер $100 + шире шаг/таргет.
    in.otc НЕ морозит сервис (otc_expected), otcPassed проверяется."""
    _cfg(bots=BTCLONG_BOT)
    monkeypatch.setattr(gat, "read_btc_move",
                        lambda **kw: {"move_1h_pct": 1.2,
                                      "max_move_calm_pct": 1.2})
    api = _btclong_api()
    sent = []
    n = gat.tick(send_fn=sent.append, api=api, drift={},
                 bags={"5317457827": {"bag": -0.001, "status": 2,
                                      "position": 6000}})
    assert n == 1
    assert api.set_calls == [(0.117, 1.001, 100.0)]   # gs/tog +30%, ордер 100$
    assert not gat.is_frozen()
    active = json.loads(gat.ACTIVE_PATH.read_text())
    assert active["5317457827"]["orig"] == {"gs": 0.09, "tog": 0.77, "maxQ": 300}
    assert sent and "100" in sent[0] and "АВТОШИРЕНИЕ" in sent[0]


def test_btc_move_restores_quiet_size_on_calm(tmp_path, monkeypatch):
    _cfg(bots=BTCLONG_BOT)
    gat.ACTIVE_PATH.write_text(json.dumps(
        {"5317457827": {"orig": {"gs": 0.09, "tog": 0.77, "maxQ": 300},
                        "applied_ts": "x", "widen_pct": 30}}), encoding="utf-8")
    monkeypatch.setattr(gat, "read_btc_move",
                        lambda **kw: {"move_1h_pct": 0.1,
                                      "max_move_calm_pct": 0.3})
    api = _btclong_api(gs=0.117, tog=1.001, maxq=100)
    sent = []
    n = gat.tick(send_fn=sent.append, api=api, drift={},
                 bags={"5317457827": {"bag": -0.0001, "status": 2,
                                      "position": 6000}})
    assert n == 1
    assert api.set_calls == [(0.09, 0.77, 300.0)]     # исходные + quiet 300$
    assert json.loads(gat.ACTIVE_PATH.read_text()) == {}
    assert sent and "300" in sent[0]


def test_btc_move_no_restore_until_calm(tmp_path, monkeypatch):
    """Движение продолжается в calm-окне → сидим в эпизоде."""
    _cfg(bots=BTCLONG_BOT)
    gat.ACTIVE_PATH.write_text(json.dumps(
        {"5317457827": {"orig": {"gs": 0.09, "tog": 0.77, "maxQ": 300},
                        "applied_ts": "x", "widen_pct": 30}}), encoding="utf-8")
    monkeypatch.setattr(gat, "read_btc_move",
                        lambda **kw: {"move_1h_pct": 0.2,
                                      "max_move_calm_pct": 1.5})
    api = _btclong_api()
    assert gat.tick(api=api, drift={},
                    bags={"5317457827": {"bag": 0.0, "status": 2}}) == 0
    assert not api.set_calls


def test_btc_move_stale_prices_do_nothing(tmp_path, monkeypatch):
    _cfg(bots=BTCLONG_BOT)
    monkeypatch.setattr(gat, "read_btc_move", lambda **kw: None)
    api = _btclong_api()
    assert gat.tick(api=api, drift={},
                    bags={"5317457827": {"bag": -0.001, "status": 2}}) == 0
    assert not api.set_calls


def test_otc_passed_flip_freezes_and_rolls_back(tmp_path, monkeypatch):
    """Если запись вдруг сбросит otcPassed (урок 17.05) — rollback + freeze."""
    _cfg(bots=BTCLONG_BOT)
    monkeypatch.setattr(gat, "read_btc_move",
                        lambda **kw: {"move_1h_pct": 1.2,
                                      "max_move_calm_pct": 1.2})
    api = _btclong_api()
    api.flip_otc_on_set = True
    sent = []
    n = gat.tick(send_fn=sent.append, api=api, drift={},
                 bags={"5317457827": {"bag": -0.001, "status": 2,
                                      "position": 6000}})
    assert n == 0
    assert gat.is_frozen()
    assert len(api.set_calls) == 2                    # попытка + rollback
    assert any("КРИТИЧНО" in s for s in sent)


def test_btc_position_below_threshold_left_alone(tmp_path, monkeypatch):
    """Оператор: пока не набрал позицию (~$5-6k) — не трогаем, даже при
    сильном движении BTC."""
    _cfg(bots=BTCLONG_BOT)
    monkeypatch.setattr(gat, "read_btc_move",
                        lambda **kw: {"move_1h_pct": 1.5,
                                      "max_move_calm_pct": 1.5})
    api = _btclong_api()
    n = gat.tick(api=api, drift={},
                 bags={"5317457827": {"bag": -0.001, "status": 2,
                                      "position": 2300}})  # < 5500
    assert n == 0
    assert not api.set_calls
    assert "SKIP_SMALL_POS" in _events()


def test_read_btc_move_from_csv(tmp_path):
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    lines = ["ts,open,high,low,close,volume"]
    t = now - timedelta(minutes=300)
    while t <= now:
        px = 64000.0 if t <= now - timedelta(minutes=60) else 65000.0
        lines.append(f"{t.isoformat()},{px},{px},{px},{px},1")
        t += timedelta(minutes=1)
    csv = tmp_path / "m1.csv"
    csv.write_text("\n".join(lines) + "\n", encoding="utf-8")
    mv = gat.read_btc_move(csv, calm_hours=4.0, now=now)
    assert mv is not None
    assert abs(mv["move_1h_pct"] - 1.5625) < 0.01     # 64000→65000
    assert mv["max_move_calm_pct"] >= mv["move_1h_pct"] - 0.01
    # протухшие свечи → None
    old = gat.read_btc_move(csv, calm_hours=4.0,
                            now=now + timedelta(minutes=30))
    assert old is None


def test_notional_gate_blocks_small_position(tmp_path):
    """Оператор 2026-07-21: альты — только от $2000 нотионала.
    16.5 BCH × $100 = $1650 < $2000 → не трогаем."""
    _cfg(bots={"42": {"alias": "BCH-DYN", "min_notional_usd": 2000}})
    api = FakeAPI()
    n = gat.tick(api=api, drift={"42": 3},
                 bags={"42": {"bag": -150.0, "status": 2, "position": 16.5,
                              "notional": 1650.0}})
    assert n == 0
    assert not api.set_calls
    assert "SKIP_SMALL_POS" in _events()


def test_notional_gate_allows_loaded_position(tmp_path):
    """16.5 BCH × $226 = $3730 >= $2000 → расширяем."""
    _cfg(bots={"42": {"alias": "BCH-DYN", "min_notional_usd": 2000}})
    api = FakeAPI()
    n = gat.tick(api=api, drift={"42": 3},
                 bags={"42": {"bag": -150.0, "status": 2, "position": 16.5,
                              "notional": 3730.0}})
    assert n == 1
    assert api.set_calls == [(0.13, 1.105, None)]


def test_notional_gate_missing_price_is_failsafe(tmp_path):
    """Нет avg_price → нотионал неизвестен → вслепую не действуем."""
    _cfg(bots={"42": {"alias": "BCH-DYN", "min_notional_usd": 2000}})
    api = FakeAPI()
    assert gat.tick(api=api, drift={"42": 3},
                    bags={"42": {"bag": -150.0, "status": 2, "position": 16.5,
                                 "notional": None}}) == 0
    assert not api.set_calls


def test_read_bags_computes_notional(tmp_path):
    """avg_price (поле 14) → нотионал = |поза| × цена."""
    csv = tmp_path / "snaps.csv"
    head = ("ts_utc,bot_id,bot_name,alias,status,position,profit,"
            "current_profit,in_c,in_q,out_c,out_q,tr_c,tr_q,average_price,"
            "trade_volume,balance,liq,schema\n")
    csv.write_text(
        head +
        "2026-07-20T10:01:00+00:00,42,BCH,B,2,16.5,100.0,55.0,1,,1,,0,,226.0,"
        "1000,500,0,3\n", encoding="utf-8")
    bags = gat.read_bags(csv)
    assert abs(bags["42"]["avg_price"] - 226.0) < 1e-9
    assert abs(bags["42"]["notional"] - 3729.0) < 1e-6
    # OKX-семантика: bag = current_profit (поле 7) напрямую, без вычитания
    assert abs(bags["42"]["bag"] - 55.0) < 1e-9


def test_read_bags_parses_snapshot_tail(tmp_path):
    """Последняя строка бота побеждает; неполная схема (съехали поля) —
    отбраковывается, вслепую не парсим."""
    csv = tmp_path / "snaps.csv"
    head = ("ts_utc,bot_id,bot_name,alias,status,position,profit,"
            "current_profit,in_c,in_q,out_c,out_q,tr_c,tr_q,average_price,"
            "trade_volume,balance,liq,schema\n")
    csv.write_text(
        head +
        "2026-07-20T10:00:00+00:00,42,ETH,E,2,-1.5,100.0,40.0,1,,1,,0,,1800,"
        "1000,500,0,3\n"
        "2026-07-20T10:01:00+00:00,42,ETH,E,2,-1.5,100.0,55.0,1,,1,,0,,1800,"
        "1000,500,0,3\n"
        "2026-07-20T10:02:00+00:00,99,BAD,B,2,-1.5,100.0,55.0\n",  # обрезана
        encoding="utf-8")
    bags = gat.read_bags(csv)
    assert bags["42"]["status"] == 2
    assert abs(bags["42"]["bag"] - 55.0) < 1e-9       # current_profit последней строки
    assert abs(bags["42"]["position"] - (-1.5)) < 1e-9
    assert abs(bags["42"]["notional"] - 2700.0) < 1e-6
    assert "99" not in bags                           # битую строку пропустили