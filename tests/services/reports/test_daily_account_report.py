"""Суточный отчёт читает журналы служб, а не оркестратора.

Оператор 28.08 показал прежнюю выдачу за 27.08: «Всего событий: 2, ботов
затронуто: 1, btc_short: REDUCE → RUN». В тот день по журналам было 726
записей, три закрытых ордера на +$13.42 и две остановки риск-контуром.
"""
from __future__ import annotations

import json

import pytest

from services.reports import daily_account_report as rep

DAY = "2026-08-27"


@pytest.fixture(autouse=True)
def _iso(monkeypatch, tmp_path):
    src = {k: tmp_path / f"{k}.jsonl" for k in rep.SOURCES}
    monkeypatch.setattr(rep, "SOURCES", src)
    monkeypatch.setattr(rep, "_account_state", lambda api=None: None)
    return src


def _write(path, rows):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False)
                              for r in rows), encoding="utf-8")


def test_closed_orders_and_money_are_reported(_iso):
    _write(_iso["harvester"], [
        {"event": "ORDER_CLOSED", "alias": "BTC-c-c", "profit_usd": 4.28,
         "ts": f"{DAY}T09:02:36+00:00"},
        {"event": "ORDER_CLOSED", "alias": "BTC-c-c", "profit_usd": 2.81,
         "ts": f"{DAY}T09:57:40+00:00"},
        {"event": "ORDER_CLOSED", "alias": "ETH-c", "profit_usd": 6.33,
         "ts": f"{DAY}T11:00:00+00:00"},
    ])
    txt = rep.build_report(DAY)
    assert "зафиксировано 3 ордеров на +$13.42" in txt
    assert "BTC-c-c: 2 шт, +$7.09" in txt
    assert "ETH-c: 1 шт, +$6.33" in txt


def test_risk_guard_actions_are_reported(_iso):
    _write(_iso["risk"], [
        {"event": "NOTIFY", "reason": "экспозиция", "ts": f"{DAY}T10:00:00+00:00"},
        {"event": "HALT", "reason": "экспозиция $3,169 = 1.47x выше предела",
         "ts": f"{DAY}T12:00:00+00:00"},
    ])
    txt = rep.build_report(DAY)
    assert "HALT" in txt
    assert "1.47x" in txt


def test_step_changes_are_reported(_iso):
    _write(_iso["autotune"], [
        {"event": "LADDER_APPLIED", "alias": "SOL", "gs_from": 0.2,
         "gs_to": 0.7, "occupancy_pct": 15.1, "ts": f"{DAY}T14:43:36+00:00"},
        {"event": "LADDER_MANUAL_HELD", "ts": f"{DAY}T15:00:00+00:00"},
        {"event": "LADDER_MANUAL_HELD", "ts": f"{DAY}T15:01:00+00:00"},
    ])
    txt = rep.build_report(DAY)
    assert "SOL: 0.2 → 0.7" in txt
    assert "удержано 2 раз" in txt


def test_other_days_are_not_counted(_iso):
    _write(_iso["harvester"], [
        {"event": "ORDER_CLOSED", "alias": "X", "profit_usd": 99.0,
         "ts": "2026-08-26T10:00:00+00:00"},
    ])
    txt = rep.build_report(DAY)
    assert "ордеров не закрывалось" in txt
    assert "99" not in txt


def test_quiet_day_says_so_without_inventing(_iso):
    txt = rep.build_report(DAY)
    assert "ордеров не закрывалось" in txt
    assert "не вмешивался" in txt
    assert "не менялся" in txt
    assert "записей в журналах за сутки: 0" in txt


def test_empty_day_detected(_iso):
    assert rep.is_empty_day(DAY) is True
    _write(_iso["pauses"], [{"action": "paused",
                             "ts": f"{DAY}T10:00:00+00:00"}])
    assert rep.is_empty_day(DAY) is False


def test_unreadable_state_is_not_invented(_iso):
    """Состояние счёта не прочиталось — так и пишем, а не выдумываем."""
    txt = rep.build_report(DAY)
    assert "состояние счёта недоступно" in txt


def test_orchestrator_phantom_bot_is_not_in_report(_iso):
    """btc_short_l1 больше не должен появляться: у него нет id GinArea."""
    _write(_iso["harvester"], [
        {"event": "ORDER_CLOSED", "alias": "BTC-c-c", "profit_usd": 1.0,
         "ts": f"{DAY}T09:00:00+00:00"}])
    txt = rep.build_report(DAY)
    assert "btc_short" not in txt
    assert "REGIME" not in txt
