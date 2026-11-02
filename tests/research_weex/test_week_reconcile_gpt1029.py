"""research/weex/week_reconcile.py и exec_calib/calib_1s.py — остатки разбора GPT 29.10
(docs/WEEX_GPT_CRITICAL_REPLY_RECHECK_2026-10-29.md §2, P1): при непустой позиции стоящий вход терял свой объём; курсор
cum_qty стартовал пустым и второй раз учитывал исполнение, уже лежащее в стартовом снимке."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wr = _module("week_reconcile", ROOT / "research/weex/week_reconcile.py")
sys.modules["week_reconcile"] = wr                      # calib_1s импортирует его по имени — тот же модуль
calib = _module("calib_1s_gpt1029", ROOT / "research/weex/exec_calib/calib_1s.py")


def _run(engine, name, g, cfg, times, points):
    if engine == "sim":
        return wr.sim(name, g, cfg, times, points, [points[-1][-1]], {})
    return calib.run(name, g, cfg, times, points, None)


# ── P1: стоящий вход при непустой позиции ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("engine", ["sim", "calib"])
def test_existing_order_keeps_quantity_when_inventory_is_not_empty(monkeypatch, engine):
    """Контрпример GPT: лот 1, стоящий вход 2, новое расписание 1 → позиция 3 (было 2)."""
    monkeypatch.setitem(wr.SCHEDULE, "SYN", [(wr.T0, "1", 10000, 50)])
    g = {"sides": {"LONG": {"lots": [{"entry": 100, "qty": 1, "tp": 200}],
                            "entry_order": {"price": 99, "qty": 2}}}}
    cfg = {"step_pct": 1, "target_pct": 100, "price_tick": 0.01}
    got = _run(engine, "SYN", g, cfg, [wr.W0], [[100, 99, 100, 100]])
    assert got["ent"] == 1
    assert got["qty"] == pytest.approx(3), got


@pytest.mark.parametrize("engine", ["sim", "calib"])
def test_standing_order_is_replaced_when_its_level_moves(monkeypatch, engine):
    """Явная отмена: тейк единственного лота — опора тянется за ценой, уровень уходит дальше trail_min_move_pct →
    движок переставляет вход объёмом расписания (старый код держал устаревшую цену 99 вечно)."""
    monkeypatch.setitem(wr.SCHEDULE, "SYN", [(wr.T0, "1", 10000, 50)])
    g = {"sides": {"LONG": {"lots": [{"entry": 100, "qty": 1, "tp": 101}],
                            "entry_order": {"price": 99, "qty": 2}}}}
    cfg = {"step_pct": 1, "target_pct": 10, "price_tick": 0.01, "trail_min_move_pct": 0.05}
    got = _run(engine, "SYN", g, cfg, [wr.W0, wr.W0 + 60], [[101, 101, 101, 101], [101, 99.99, 101, 101]])
    assert got["tk"] == 1 and got["ent"] == 1, got
    assert got["qty"] == pytest.approx(1), got           # новый вход 99.99 × 1, а не стоящий 99 × 2


@pytest.mark.parametrize("engine", ["sim", "calib"])
def test_standing_order_is_replaced_when_size_changes(monkeypatch, engine):
    """Явная отмена: смена размера по расписанию — движок ставит вход заново новым объёмом (same_qty)."""
    monkeypatch.setitem(wr.SCHEDULE, "SYN", [(wr.T0, "2", 10000, 50), (wr.W0 + 60, "1", 10000, 50)])
    g = {"sides": {"LONG": {"lots": [{"entry": 100, "qty": 1, "tp": 200}],
                            "entry_order": {"price": 99, "qty": 2}}}}
    cfg = {"step_pct": 1, "target_pct": 100, "price_tick": 0.01}
    got = _run(engine, "SYN", g, cfg, [wr.W0, wr.W0 + 60], [[100, 100, 100, 100], [100, 99, 100, 100]])
    assert got["ent"] == 1 and got["qty"] == pytest.approx(2), got


@pytest.mark.parametrize("engine", ["sim", "calib"])
def test_standing_order_without_lots_keeps_its_price_and_quantity(monkeypatch, engine):
    """Контроль 28.10: пустая позиция, стоящий вход 99 × 2 исполняется своим объёмом."""
    monkeypatch.setitem(wr.SCHEDULE, "SYN", [(wr.T0, "1", 10000, 50)])
    g = {"sides": {"LONG": {"lots": [], "entry_order": {"price": 99, "qty": 2}}}}
    cfg = {"step_pct": 1, "target_pct": 10, "price_tick": 0.01, "trail_min_move_pct": 0.05}
    got = _run(engine, "SYN", g, cfg, [wr.W0], [[100, 99, 100, 100]])
    assert got["ent"] == 1 and got["qty"] == pytest.approx(2), got


# ── P1: курсор cum_qty на границе снимка ───────────────────────────────────────────────────────────────────────────

def _journal(tmp_path, monkeypatch, rows):
    monkeypatch.setattr(wr, "ST", str(tmp_path) + "/")
    (tmp_path / wr.JOURNAL["BTC"]).write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")


def test_cumulative_cursor_excludes_fill_already_in_start_snapshot(tmp_path, monkeypatch):
    """Контрпример GPT: e1 исполнен на 1 до T0 (уже в снимке), в окне cum_qty 2 → позиция 2, оборот 100 (было 3/200)."""
    g = {"sides": {"LONG": {"lots": [{"entry": 100, "qty": 1}]}}}
    _journal(tmp_path, monkeypatch, [
        {"ts": "2026-10-18T16:14:00+00:00", "side": "LONG", "kind": "вход", "qty": 1,
         "price": 100, "fee": .016, "order_id": "e1", "cum_qty": 1},
        {"ts": "2026-10-18T17:00:00+00:00", "side": "LONG", "kind": "вход", "qty": 1,
         "price": 100, "fee": .016, "order_id": "e1", "cum_qty": 2},
    ])
    got = wr.live("BTC", g, wr.T0 + 3600, 100)
    assert got["qty"] == 2, got
    assert got["vol"] == 100


def test_unknown_cursor_base_is_refused_not_zero(tmp_path, monkeypatch):
    """Строк заявки до окна нет, а первая строка окна уже cum_qty 2 при qty 1 — база неизвестна: отказ, не ноль."""
    g = {"sides": {"LONG": {"lots": [{"entry": 100, "qty": 1}]}}}
    _journal(tmp_path, monkeypatch, [
        {"ts": "2026-10-18T17:00:00+00:00", "side": "LONG", "kind": "вход", "qty": 1,
         "price": 100, "fee": .016, "order_id": "e1", "cum_qty": 2},
    ])
    with pytest.raises(ValueError, match="e1"):
        wr.live("BTC", g, wr.T0 + 3600, 100)


def test_cursor_base_without_cum_qty_before_window_is_refused(tmp_path, monkeypatch):
    g = {"sides": {"LONG": {"lots": [{"entry": 100, "qty": 1}]}}}
    _journal(tmp_path, monkeypatch, [
        {"ts": "2026-10-18T16:10:00+00:00", "side": "LONG", "kind": "вход", "qty": 1,
         "price": 100, "fee": .016, "order_id": "e1"},
        {"ts": "2026-10-18T17:00:00+00:00", "side": "LONG", "kind": "вход", "qty": 1,
         "price": 100, "fee": .016, "order_id": "e1", "cum_qty": 2},
    ])
    with pytest.raises(ValueError, match="без cum_qty"):
        wr.live("BTC", g, wr.T0 + 3600, 100)


def test_duplicate_cumulative_fill_within_window_is_idempotent(tmp_path, monkeypatch):
    """Контроль GPT: повтор того же cum_qty в окне учитывается один раз."""
    g = {"sides": {"LONG": {"lots": [{"entry": 100, "qty": 2}]}}}
    r = {"ts": "2026-10-18T17:00:00+00:00", "side": "LONG", "kind": "тейк", "qty": 1,
         "price": 101, "entry": 100, "pnl": 1, "fee": .01616, "order_id": "t1", "cum_qty": 1}
    _journal(tmp_path, monkeypatch, [r, r])
    got = wr.live("BTC", g, wr.T0 + 3600, 100)
    assert got["qty"] == 1 and got["tk"] == 1 and got["real"] == 1
    assert got["fee"] == pytest.approx(.01616)


def test_partial_entry_rows_are_the_same_order(tmp_path, monkeypatch):
    """Движок пишет второй прирост входа как «вход (часть)» — это тот же вход: +2 к позиции, одна заявка."""
    g = {"sides": {"LONG": {"lots": []}}}
    _journal(tmp_path, monkeypatch, [
        {"ts": "2026-10-18T17:00:00+00:00", "side": "LONG", "kind": "вход", "qty": 1,
         "price": 100, "fee": .016, "order_id": "e2", "cum_qty": 1},
        {"ts": "2026-10-18T17:01:00+00:00", "side": "LONG", "kind": "вход (часть)", "qty": 1,
         "price": 100, "fee": .016, "order_id": "e2", "cum_qty": 2},
    ])
    got = wr.live("BTC", g, wr.T0 + 3600, 100)
    assert got["qty"] == 2 and got["ent"] == 1, got
