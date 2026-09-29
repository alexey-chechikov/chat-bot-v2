"""Гейт шорта: счёт по вчерашнему дню, карточка только при переключении."""
from __future__ import annotations

import json

import pytest

from services.short_gate import loop as sg


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(sg, "CONFIG_PATH", tmp_path / "cfg.json")
    monkeypatch.setattr(sg, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(sg, "JOURNAL_PATH", tmp_path / "j.jsonl")
    monkeypatch.setattr(sg, "HEARTBEAT_PATH", tmp_path / "hb.json")
    sg.CONFIG_PATH.write_text(json.dumps({"enabled": True, "sma_days": 5}),
                              encoding="utf-8")


def closes(vals, start=1):
    return {f"2026-01-{start + i:02d}": v for i, v in enumerate(vals)}


def test_gate_needs_history():
    assert sg.gate_state(closes([100, 101, 102]), 5) is None


def test_gate_on_when_yesterday_below_sma():
    #  5 дней по 100, вчера 90, сегодня (последний день) не участвует
    g = sg.gate_state(closes([100] * 5 + [90, 999]), 5)
    assert g["on"] and g["day"] == "2026-01-06"
    assert g["close"] == 90 and g["sma"] == pytest.approx(100)
    assert g["dist_pct"] == pytest.approx(-10.0)


def test_gate_off_when_yesterday_above_sma():
    g = sg.gate_state(closes([100] * 5 + [110, 1]), 5)
    assert not g["on"]
    assert g["dist_pct"] == pytest.approx(10.0)


def test_today_is_not_counted():
    """Сегодняшний день ещё идёт — решение принимаем по вчерашнему закрытию."""
    g = sg.gate_state(closes([100] * 5 + [90, 500]), 5)
    assert g["close"] == 90


def test_tick_sends_only_on_flip(monkeypatch):
    seq = [closes([100] * 5 + [90, 0]),        # включён
           closes([100] * 5 + [95, 0]),        # остался включён
           closes([100] * 5 + [120, 0])]       # выключился
    box = {"i": 0}

    def fake_gate(cfg=None):
        g = sg.gate_state(seq[box["i"]], 5)
        box["i"] = min(box["i"] + 1, len(seq) - 1)
        return g

    monkeypatch.setattr(sg, "current_gate", fake_gate)
    sent = []
    assert sg.tick(send_fn=sent.append) == "ok"      # первый расчёт — молча
    assert sent == []
    assert sg.tick(send_fn=sent.append) == "ok"      # без переключения — молча
    assert sent == []
    assert sg.tick(send_fn=sent.append) == "flip"
    assert len(sent) == 1 and "ШОРТ ЗАПРЕЩЁН" in sent[0]
    assert "выше SMA5" in sent[0]
    events = [json.loads(x)["event"] for x in
              sg.JOURNAL_PATH.read_text(encoding="utf-8").splitlines()]
    assert events == ["INIT", "FLIP"]
    assert json.loads(sg.HEARTBEAT_PATH.read_text())["status"] == "flip"


def test_disabled_config_is_silent(monkeypatch):
    sg.CONFIG_PATH.write_text(json.dumps({"enabled": False}), encoding="utf-8")
    sent = []
    assert sg.tick(send_fn=sent.append) == "disabled"
    assert sent == []
