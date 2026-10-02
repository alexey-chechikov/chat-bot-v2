"""Выключатель отправки карточек входов.

Главное свойство: при потерянном или испорченном конфиге лента ДОЛЖНА
молчать, а не оживать сама.
"""
import json

from services.setup_detector import push_gate


def test_off_by_default_when_config_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(push_gate, "CONFIG_PATH", tmp_path / "нет.json")
    assert push_gate.actionable_push_enabled() is False


def test_off_when_config_broken(tmp_path, monkeypatch):
    p = tmp_path / "cfg.json"
    p.write_text("{не json", encoding="utf-8")
    monkeypatch.setattr(push_gate, "CONFIG_PATH", p)
    assert push_gate.actionable_push_enabled() is False


def test_off_when_flag_false(tmp_path, monkeypatch):
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({"actionable_to_telegram": False}),
                 encoding="utf-8")
    monkeypatch.setattr(push_gate, "CONFIG_PATH", p)
    assert push_gate.actionable_push_enabled() is False


def test_on_only_when_explicitly_enabled(tmp_path, monkeypatch):
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({"actionable_to_telegram": True}),
                 encoding="utf-8")
    monkeypatch.setattr(push_gate, "CONFIG_PATH", p)
    assert push_gate.actionable_push_enabled() is True


def test_live_config_is_muted():
    """Боевой конфиг сейчас должен быть выключен — это и есть решение."""
    assert push_gate.actionable_push_enabled() is False
