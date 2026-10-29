"""research/weex/week_reconcile.py — контрпримеры GPT a7d799b (§3, P1): частичный тейк убирал весь лот; стоящий вход
брал объём из нового расписания вместо своего."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("week_reconcile_t", ROOT / "research/weex/week_reconcile.py")
week = importlib.util.module_from_spec(spec)
spec.loader.exec_module(week)


def test_partial_take_keeps_remaining_position(tmp_path, monkeypatch):
    monkeypatch.setattr(week, "ST", str(tmp_path) + "/")
    g = {"sides": {"LONG": {"lots": [{"entry": 100, "qty": 2}]}}}
    r = {"ts": "2026-10-18T17:00:00+00:00", "side": "LONG", "kind": "тейк",
         "qty": 1, "price": 101, "entry": 100, "pnl": 1, "fee": 0.01616}
    (tmp_path / week.JOURNAL["BTC"]).write_text(json.dumps(r), encoding="utf-8")
    got = week.live("BTC", g, week.T0 + 3600, 90)
    assert got["qty"] == 1, got           # было 0: лот снимался целиком
    assert got["bag"] == -10


def test_partial_take_by_order_cursor_counts_fill_once(tmp_path, monkeypatch):
    """Два отчёта одного тейка (cum_qty растёт): исполнено 2 из 2, лот закрыт один раз, тейков — одна заявка."""
    monkeypatch.setattr(week, "ST", str(tmp_path) + "/")
    g = {"sides": {"LONG": {"lots": [{"entry": 100, "qty": 2}, {"entry": 99, "qty": 2}]}}}
    rows = [{"ts": "2026-10-18T17:00:00+00:00", "side": "LONG", "kind": "тейк", "qty": 1, "price": 101, "entry": 100,
             "pnl": 1, "fee": 0.01, "order_id": "t1", "cum_qty": 1},
            {"ts": "2026-10-18T17:01:00+00:00", "side": "LONG", "kind": "тейк", "qty": 1, "price": 101, "entry": 100,
             "pnl": 1, "fee": 0.01, "order_id": "t1", "cum_qty": 2}]
    (tmp_path / week.JOURNAL["BTC"]).write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    got = week.live("BTC", g, week.T0 + 7200, 90)
    assert got["qty"] == 2 and got["lots"] == 1, got
    assert got["tk"] == 1, got            # одна заявка-тейк, а не две строки


def test_existing_entry_keeps_its_original_quantity(monkeypatch):
    monkeypatch.setitem(week.SCHEDULE, "BTC", [(week.T0, "1", 10000, 50)])
    g = {"sides": {"LONG": {"lots": [], "entry_order": {"price": 99, "qty": 2}}}}
    cfg = {"step_pct": 1, "target_pct": 10, "price_tick": 0.01}
    got = week.sim("BTC", g, cfg, [week.T0 + 60], [[100, 99, 100, 100]], [100], {})
    assert got["qty"] == 2, got           # было 1: стоящая заявка брала объём из нового расписания
