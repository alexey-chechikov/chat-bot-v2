"""Сигнал о близком уровне: порог, повтор не чаще cooldown, текст с деньгами."""
from __future__ import annotations

import json

import pytest

from services.grid_model import bot_money as bm
from services.grid_model import level_alerts as la


def _book() -> bm.Book:
    return bm.Book(name="BTC USDT DYNAMIC", coin="BTC", inverse=False, grid_side=2,
                   step=0.006, target=0.0139, obap=False, order_qty=0.01,
                   max_orders=200, border_top=86_500.0, border_bottom=None,
                   orders=[bm.Order(2, 0.01, 84_000.0, 82_832.4)], bag_usd=-20.0)


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(la, "CONFIG", tmp_path / "cfg.json")
    monkeypatch.setattr(la, "STATE", tmp_path / "st.json")
    monkeypatch.setattr(la, "JOURNAL", tmp_path / "j.jsonl")
    (tmp_path / "cfg.json").write_text(json.dumps(
        {"enabled": True, "threshold_4h": 0.30, "cooldown_hours": 4.0}), encoding="utf-8")
    return tmp_path


def _touch(p4):
    return lambda pct, h: p4 if h == "4ч" else 0.6


def test_alert_fires_above_threshold_once_per_cooldown(paths):
    kw = dict(books={"BTC": [_book()]}, prices={"BTC": 85_900.0})
    sent = la.tick(touch_by_sym={"BTC": _touch(0.35)}, now=1_000_000.0, **kw)
    assert any("граница 86,500" in s for s in sent)
    assert all("шанс дойти за 4ч 35%" in s for s in sent)
    again = la.tick(touch_by_sym={"BTC": _touch(0.35)}, now=1_000_000.0 + 3600, **kw)
    assert again == [], "повтор раньше 4 часов — шум"
    later = la.tick(touch_by_sym={"BTC": _touch(0.35)}, now=1_000_000.0 + 5 * 3600, **kw)
    assert later, "после паузы снова можно"
    lines = (paths / "j.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(sent) + len(later)


def test_no_alert_below_threshold(paths):
    sent = la.tick(books={"BTC": [_book()]}, prices={"BTC": 85_900.0},
                   touch_by_sym={"BTC": _touch(0.10)}, now=2_000_000.0)
    assert sent == []


def test_border_message_has_money_and_stop():
    c = {"name": "граница", "level": 86_500.0, "pct": 0.011, "p4": 0.35, "p24": 0.7,
         "realized": 0.0, "total": -303.0}
    msg = la.message("BTC шорт", c)
    assert msg.startswith("⚠️ BTC шорт: граница 86,500")
    assert "-303$" in msg and "набор остановится" in msg


def test_disabled_sends_nothing(paths):
    (paths / "cfg.json").write_text(json.dumps({"enabled": False}), encoding="utf-8")
    assert la.tick(books={"BTC": [_book()]}, prices={"BTC": 85_900.0},
                   touch_by_sym={"BTC": _touch(0.9)}) == []
