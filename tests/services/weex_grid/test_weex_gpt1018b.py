"""Разбор GPT 7ecda96 §2.1: поздний досчёт комиссий (_settle_fees) суммировал строки ЧУЖОГО ордера и принимал
null как успешное пустое чтение (курсор помечался проверенным и мог истечь без проверки). Должно падать на 7ecda96."""
from __future__ import annotations

import pytest

from tests.services.weex_grid.test_weex_gpt1014 import live_grid


def _book(g, oid="555"):
    now = g.now()
    g.st["LONG"]["fee_book"][oid] = {"done": 0.0, "t": now, "t0": now}
    g.st["fee_checked"] = 0.0
    return g.st["LONG"]["fees"]


def test_late_fee_only_own_order_rows(tmp_path):
    t = live_grid(tmp_path, filled=False)
    g = t.g
    before = _book(g)
    g.c.user_trades = lambda sym, oid=None, **kw: [
        {"orderId": oid, "symbol": "BTCUSDT", "commission": "0.01"},
        {"orderId": "999999", "symbol": "BTCUSDT", "commission": "7"},       # чужой ордер в ответе
        {"symbol": "BTCUSDT", "commission": "3"},                            # без номера ордера
    ]
    g._settle_fees()
    assert g.st["LONG"]["fees"] - before == pytest.approx(0.01)
    assert g.st["LONG"]["fee_book"]["555"]["done"] == pytest.approx(0.01)


@pytest.mark.parametrize("bad", [None, {}, "x"], ids=["null", "object", "string"])
def test_late_fee_bad_reply_does_not_mark_checked(tmp_path, bad):
    t = live_grid(tmp_path, filled=False)
    g = t.g
    _book(g)
    g.c.user_trades = lambda *a, **kw: bad
    g._settle_fees()
    rec = g.st["LONG"]["fee_book"]["555"]
    assert not rec.get("checked"), "негодный ответ не считается проверкой — курсор не должен истечь"
    assert any("комисси" in w for _, w in g._other_issues)
