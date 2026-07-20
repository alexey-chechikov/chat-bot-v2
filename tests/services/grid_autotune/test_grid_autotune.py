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


class FakeAPI:
    def __init__(self, gs=0.1, tog=0.85, p=True, extra=None, status=2):
        self.params = SimpleNamespace(gs=gs, gap=SimpleNamespace(tog=tog),
                                      p=p, extra_raw=extra or {})
        self.status = status
        self.set_calls: list[tuple] = []
        self.set_raises = None

    def get_params(self, bot_id):
        return self.params

    def set_params(self, bot_id, params):
        self.set_calls.append((round(params.gs, 4), round(params.gap.tog, 4)))
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
    assert api.set_calls == [(0.13, 1.105)]           # +30%
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
    assert api.set_calls == [(0.1, 0.85)]             # откат к исходным
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
    assert api.set_calls == [(0.13, 1.105), (0.1, 0.85)]
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


def test_read_bags_parses_snapshot_tail(tmp_path, monkeypatch):
    csv = tmp_path / "snaps.csv"
    csv.write_text(
        "ts_utc,bot_id,bot_name,alias,status,position,profit,current_profit,x\n"
        "2026-07-20T10:00:00+00:00,42,ETH,E,2,-1.5,100.0,40.0,z\n"
        "2026-07-20T10:01:00+00:00,42,ETH,E,2,-1.5,100.0,55.0,z\n",
        encoding="utf-8")
    bags = gat.read_bags(csv)
    assert bags["42"]["status"] == 2
    assert abs(bags["42"]["bag"] - (-45.0)) < 1e-9    # последняя строка бота