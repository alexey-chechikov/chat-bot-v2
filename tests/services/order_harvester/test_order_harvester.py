"""Order Harvester: кандидаты, флоу пауза→close→резюм, freeze-стоп-кран.

ВСЕ пути состояния (journal/frozen/config) подменяются в tmp_path — сервис
мутирует живых ботов, тесты не должны трогать ни боевые файлы, ни API.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from services.order_harvester import loop as oh


@pytest.fixture(autouse=True)
def _isolate_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(oh, "JOURNAL_PATH", tmp_path / "journal.jsonl")
    monkeypatch.setattr(oh, "FROZEN_PATH", tmp_path / "frozen.json")
    monkeypatch.setattr(oh, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(oh, "STATUS_POLL_SEC", 0.01)
    monkeypatch.setattr(oh, "STATUS_WAIT_MAX_SEC", 0.05)
    oh._last_harvest_mono.clear()
    oh._api_cache.clear()


class FakeAPI:
    """Мини-двойник BotsAPI: статусная машина + журнал вызовов."""

    def __init__(self, orders, statuses=None, params_extra=None):
        self.orders = orders
        self.calls: list[tuple] = []
        # очередь статусов для get_bot; последний повторяется
        self.statuses = list(statuses or [oh.STATUS_ACTIVE])
        self.params_extra = params_extra if params_extra is not None else {}
        self.close_raises = None

    def get_bot(self, bot_id):
        st = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        self.calls.append(("get_bot", bot_id, st))
        return SimpleNamespace(status=st)

    def get_orders(self, bot_id, **kw):
        self.calls.append(("get_orders", bot_id))
        return {"orders": self.orders, "totalCount": len(self.orders)}

    def get_params(self, bot_id):
        self.calls.append(("get_params", bot_id))
        return SimpleNamespace(extra_raw=self.params_extra)

    def close_order(self, bot_id, order_id):
        self.calls.append(("close_order", bot_id, order_id))
        if self.close_raises:
            raise self.close_raises


# реальная форма ордера GET /bots/{id}/orders — снята 2026-07-09 с 4499423673
REAL_CLOSED_ORDER = {
    "id": "076b894b-78ae-4594-96b5-39e36245bf18", "side": 1, "price": 62087.9,
    "quantity": 0.0066, "closedPrice": 62087.7, "closedQuantity": 0.0066,
    "fee": 0.143423, "feeExchangeCurrencyId": 11, "stopCount": 1,
    "openedAt": "2026-07-06T12:02:07Z", "closedAt": "2026-07-06T14:25:38.577906Z",
    "isOpen": False, "botId": 4499423673, "profit": 1.3050450212,
    "profitInDistance": 241.28,
    "trigger": {"price": 62379.51, "quantity": 0.0066, "initPrice": 62087.9,
                "lastPrice": 62087.9, "isTrailing": False, "quantityPositions": [3]},
}


def _order(oid="o1", profit=8.5, opened=True, **extra):
    o = {"id": oid, "profit": profit, "quantity": 0.0117, "price": 61540.2,
         "isOpen": opened, "side": 1, "botId": 4499423673}
    o.update(extra)
    return o


def _patch_control(monkeypatch, pause_action="paused", resume_action="resumed"):
    calls = []
    fake = SimpleNamespace(
        pause_bot=lambda bid, **kw: (calls.append(("pause", bid)),
                                     {"action": pause_action})[1],
        resume_bot=lambda bid, **kw: (calls.append(("resume", bid)),
                                      {"action": resume_action})[1],
    )
    import services.short_bots_guard.control as control
    monkeypatch.setattr(control, "pause_bot", fake.pause_bot)
    monkeypatch.setattr(control, "resume_bot", fake.resume_bot)
    return calls


def test_order_fields_normalizes_open_order():
    f = oh.order_fields(_order())
    assert f["order_id"] == "o1" and f["opened"] and f["profit_usd"] == 8.5
    assert f["qty"] == 0.0117 and f["price_in"] == 61540.2


def test_order_fields_closed_order_not_opened():
    f = oh.order_fields(_order(opened=False))
    assert not f["opened"]


def test_order_fields_real_api_shape():
    """Verbatim-ответ живого API (2026-07-09) — контракт адаптера."""
    f = oh.order_fields(REAL_CLOSED_ORDER)
    assert f["order_id"] == "076b894b-78ae-4594-96b5-39e36245bf18"
    assert not f["opened"]
    assert abs(f["profit_usd"] - 1.3050450212) < 1e-9
    assert f["qty"] == 0.0066 and f["price_in"] == 62087.9 and f["side"] == 1


def test_candidates_threshold_and_sorting():
    api = FakeAPI([_order("a", 3.0), _order("b", 9.1), _order("c", 7.0),
                   _order("d", 20.0, opened=False)])
    cands = oh._candidates(api, "123", 7.0)
    assert [c["order_id"] for c in cands] == ["b", "c"]  # d закрыт, a ниже порога


def test_harvest_success_flow(monkeypatch):
    control_calls = _patch_control(monkeypatch)
    # статусы: pause-wait видит STOPPED, resume-wait видит ACTIVE
    api = FakeAPI([_order()], statuses=[oh.STATUS_STOPPED, oh.STATUS_ACTIVE])
    sent = []
    n = oh.harvest_orders(api, "4499423673", "BTC-DYN",
                          [oh.order_fields(_order())], send_fn=sent.append)
    assert n == 1
    assert ("close_order", 4499423673, "o1") in api.calls
    assert [c[0] for c in control_calls] == ["pause", "resume"]
    assert sent and "+$8.50" in sent[0] and "Working" in sent[0]
    events = [json.loads(l)["event"] for l in
              oh.JOURNAL_PATH.read_text().splitlines()]
    assert events == ["HARVEST_START", "ORDER_CLOSED", "HARVESTED"]


def test_harvest_batch_one_pause_many_closes(monkeypatch):
    """Батч: несколько ордеров выше порога → ОДНА пауза, N close, ОДИН резюм,
    одно суммарное TG-сообщение."""
    control_calls = _patch_control(monkeypatch)
    api = FakeAPI([_order()], statuses=[oh.STATUS_STOPPED, oh.STATUS_ACTIVE])
    cands = [oh.order_fields(_order("a", 3.1)),
             oh.order_fields(_order("b", 2.0)),
             oh.order_fields(_order("c", 1.2))]
    sent = []
    n = oh.harvest_orders(api, "42", "X", cands, send_fn=sent.append)
    assert n == 3
    closes = [c for c in api.calls if c[0] == "close_order"]
    assert [c[2] for c in closes] == ["a", "b", "c"]
    assert [c[0] for c in control_calls] == ["pause", "resume"]  # ровно один цикл
    assert len(sent) == 1 and "ордеров: 3" in sent[0] and "+$6.30" in sent[0]
    harvested = [json.loads(l) for l in oh.JOURNAL_PATH.read_text().splitlines()
                 if json.loads(l)["event"] == "HARVESTED"]
    assert len(harvested) == 3


def test_otc_guard_freezes_and_never_pauses(monkeypatch):
    """Урок 2026-05-17: stop/start otc-бота сбрасывает otcPassed → Failed.
    Если у бота появился in.otc — не паузим, морозим сервис."""
    control_calls = _patch_control(monkeypatch)
    api = FakeAPI([_order()], params_extra={"in": {"otc": True}})
    sent = []
    n = oh.harvest_orders(api, "1", "X", [oh.order_fields(_order())],
                          send_fn=sent.append)
    assert n == 0
    assert oh.is_frozen()
    assert not control_calls                      # паузы НЕ было
    assert sent and "ЗАМОРОЖЕН" in sent[0]


def test_resume_failure_freezes_and_alerts(monkeypatch):
    control_calls = _patch_control(monkeypatch)
    # pause-wait: STOPPED; дальше get_bot всегда STOPPED — резюм «не работает»
    api = FakeAPI([_order()], statuses=[oh.STATUS_STOPPED])
    monkeypatch.setattr(oh, "RESUME_RETRIES", 2)
    sent = []
    n = oh.harvest_orders(api, "1", "X", [oh.order_fields(_order())],
                          send_fn=sent.append)
    assert n == 1                                 # ордер закрыт, но бот стоит
    assert oh.is_frozen()
    assert any("КРИТИЧНО" in s for s in sent)
    assert [c[0] for c in control_calls] == ["pause", "resume", "resume"]


def test_close_failure_still_resumes(monkeypatch):
    """close упал → бот ОБЯЗАН быть перезапущен, алерт со ⚠️."""
    control_calls = _patch_control(monkeypatch)
    api = FakeAPI([_order()], statuses=[oh.STATUS_STOPPED, oh.STATUS_ACTIVE])
    api.close_raises = RuntimeError("boom")
    sent = []
    n = oh.harvest_orders(api, "1", "X", [oh.order_fields(_order())],
                          send_fn=sent.append)
    assert n == 0
    assert [c[0] for c in control_calls] == ["pause", "resume"]
    assert sent and "не удалось закрыть" in sent[0]
    assert not oh.is_frozen()                     # это не критично, продолжаем жить


def test_tick_skips_when_frozen_or_disabled(monkeypatch):
    oh.freeze("test")
    assert oh.tick(api=FakeAPI([_order()])) == 0
    oh.FROZEN_PATH.unlink()
    oh.CONFIG_PATH.write_text(json.dumps({"enabled": False}), encoding="utf-8")
    assert oh.tick(api=FakeAPI([_order()])) == 0


def test_tick_ignores_non_active_bot(monkeypatch):
    _patch_control(monkeypatch)
    oh.CONFIG_PATH.write_text(json.dumps({
        "enabled": True,
        "bots": {"42": {"alias": "X", "min_order_profit_usd": 7.0}},
    }), encoding="utf-8")
    api = FakeAPI([_order()], statuses=[oh.STATUS_STOPPED])
    assert oh.tick(api=api) == 0
    assert ("get_orders", "42") not in api.calls  # до сканирования не дошли


def test_tick_daily_cap(monkeypatch):
    _patch_control(monkeypatch)
    oh.CONFIG_PATH.write_text(json.dumps({
        "enabled": True,
        "bots": {"42": {"alias": "X", "min_order_profit_usd": 7.0}},
        "max_orders_per_day_per_bot": 0,
    }), encoding="utf-8")
    api = FakeAPI([_order()])
    assert oh.tick(api=api) == 0
    assert all(c[0] != "close_order" for c in api.calls)


def test_tick_batch_respects_cycle_budget(monkeypatch):
    """max_orders_per_cycle режет батч: 3 кандидата, бюджет 2 → закрыты 2 лучших."""
    _patch_control(monkeypatch)
    oh.CONFIG_PATH.write_text(json.dumps({
        "enabled": True,
        "bots": {"42": {"alias": "X", "min_order_profit_usd": 1.0}},
        "max_orders_per_cycle": 2,
        "max_orders_per_day_per_bot": 40,
        "min_gap_between_harvests_sec": 600,
    }), encoding="utf-8")
    # get_bot: ACTIVE (скан) → STOPPED (pause-wait) → ACTIVE (resume-wait)
    api = FakeAPI([_order("a", 1.5), _order("b", 9.0), _order("c", 4.0)],
                  statuses=[oh.STATUS_ACTIVE, oh.STATUS_STOPPED, oh.STATUS_ACTIVE])
    assert oh.tick(api=api) == 2
    closes = [c[2] for c in api.calls if c[0] == "close_order"]
    assert closes == ["b", "c"]                   # топ-2 по профиту, "a" ждёт
    assert "42" in oh._last_harvest_mono          # gap-таймер взведён
