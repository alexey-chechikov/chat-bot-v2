"""Проверка покрытия ботов автоматикой ловит ровно те дыры, что были 17.08.

Тест не про «печатает ли что-то», а про то, что каждая из четырёх реальных
ситуаций даёт ненулевое число расхождений.
"""
from __future__ import annotations

import json

import tools.config_coverage as cc

LIVE = {
    "bots": [
        {"id": 111, "name": "BTC SHORT", "active": True},
        {"id": 222, "name": "ETH DYN", "active": True},
        {"id": 999, "name": "клон", "active": False},
    ]
}


def _write(tmp_path, monkeypatch, portfolio, harvester, autotune):
    p = tmp_path / "portfolio.json"
    h = tmp_path / "harvester.json"
    a = tmp_path / "autotune.json"
    p.write_text(json.dumps(portfolio), encoding="utf-8")
    h.write_text(json.dumps(harvester), encoding="utf-8")
    a.write_text(json.dumps(autotune), encoding="utf-8")
    monkeypatch.setattr(cc, "PORTFOLIO", p)
    monkeypatch.setattr(cc, "SERVICES", {"харвестер": h, "автотюнер": a})


def test_full_coverage_is_zero(tmp_path, monkeypatch):
    both = {"bots": {"111": {}, "222": {}}}
    _write(tmp_path, monkeypatch, LIVE, both, both)
    assert cc.check() == 0


def test_bot_missing_from_harvester_is_caught(tmp_path, monkeypatch):
    """Ровно случай BTC SHORT: в автотюнере есть, в харвестере нет."""
    _write(tmp_path, monkeypatch, LIVE,
           {"bots": {"222": {}}}, {"bots": {"111": {}, "222": {}}})
    assert cc.check() == 1


def test_bot_missing_from_both_is_caught_twice(tmp_path, monkeypatch):
    """Утреннее состояние 17.08: шорта не было ни там, ни там."""
    _write(tmp_path, monkeypatch, LIVE,
           {"bots": {"222": {}}}, {"bots": {"222": {}}})
    assert cc.check() == 2


def test_dead_bot_still_listed_is_caught(tmp_path, monkeypatch):
    """Мёртвый ID в конфиге — урок переезда на OKX 23.07."""
    _write(tmp_path, monkeypatch, LIVE,
           {"bots": {"111": {}, "222": {}, "5330789037": {}}},
           {"bots": {"111": {}, "222": {}}})
    assert cc.check() == 1


def test_inactive_bots_are_not_required(tmp_path, monkeypatch):
    """Клон с active:false в служебных конфигах быть не обязан."""
    both = {"bots": {"111": {}, "222": {}}}
    _write(tmp_path, monkeypatch, LIVE, both, both)
    assert cc.check() == 0


def test_empty_portfolio_reports_problem(tmp_path, monkeypatch):
    """Пустой portfolio.json — это и есть состояние до 16.08, когда гард
    пропускал всё. Молча возвращать «покрытие полное» нельзя."""
    _write(tmp_path, monkeypatch, {"bots": []},
           {"bots": {}}, {"bots": {}})
    assert cc.check() == 1
