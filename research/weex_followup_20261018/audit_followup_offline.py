"""Pure offline audit of pinned public WEEX source at 2959c7a.

Only selected AST methods are compiled; production imports and modules are never run.
All state, orders, fees and clients below are synthetic. No network or account access.
"""
from __future__ import annotations

import ast
import hashlib
import json
import logging
import math
import re
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
COMMIT = "2959c7acae99d06d9274578f931a6e35a20785c6"
RESULTS: list[dict] = []


class WeexIncomplete(RuntimeError):
    pass


class ConfigError(RuntimeError):
    pass


def verified_sources() -> dict[str, str]:
    manifest = json.loads((ROOT / "VERIFIED_SOURCES.json").read_text(encoding="utf-8"))
    assert manifest["commit"] == COMMIT
    contents = {}
    for entry in manifest["sources"]:
        raw = (ROOT / "sources" / entry["filename"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"], entry["path"]
        assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == entry["git_blob_sha1"]
        contents[entry["path"]] = raw.decode("utf-8")
    return contents


SOURCES = verified_sources()
ENGINE = ast.parse(SOURCES["services/weex_grid/engine.py"])
METHOD_NAMES = {
    "_fee_delta", "_settle_fees", "_slots", "may_add", "_entry_res", "_standing_res", "_pending_res",
    "_place", "_referenced", "_history_window", "_window_trades", "_find_by_trades", "_resolve_pending",
    "_orphans", "_take_entry_fill", "_qty_str", "_tiny", "_with_cursor", "_mark_fills", "_orders_list",
}
grid_ast = next(n for n in ENGINE.body if isinstance(n, ast.ClassDef) and n.name == "Grid")
methods = [n for n in grid_ast.body if isinstance(n, ast.FunctionDef) and n.name in METHOD_NAMES]
assert {n.name for n in methods} == METHOD_NAMES
needed_constants = {
    "DIR", "OPEN_SIDE", "CLOSE_SIDE", "TAG_RE", "PENDING_TTL", "PENDING_ABSENT_READS", "PENDING_RECHECK",
    "FEE_POLL", "FEE_BATCH", "FEE_WINDOW", "TRADES_DETAILS", "TRADES_SPLIT_BUDGET",
}
constants = []
for n in ENGINE.body:
    if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
        if n.targets[0].id in needed_constants:
            constants.append(n)
functions = [n for n in ENGINE.body if isinstance(n, ast.FunctionDef) and n.name in {"cid_tag", "round_tick", "fmt_px"}]
assert len(functions) == 3
module = ast.Module(body=constants + functions + [ast.ClassDef(name="AuditGrid", bases=[], keywords=[], body=methods, decorator_list=[])], type_ignores=[])
ns = {"math": math, "re": re, "logger": logging.getLogger("offline_audit"), "ConfigError": ConfigError, "WeexIncomplete": WeexIncomplete}
ns["logger"].addHandler(logging.NullHandler())
ns["logger"].propagate = False
exec(compile(ast.fix_missing_locations(module), "<pinned selected engine AST>", "exec"), ns)
AuditGrid = ns["AuditGrid"]


def fixture() -> object:
    g = AuditGrid()
    g.cfg = {"symbol": "BTCUSDT", "order_qty": "1", "price_tick": 0.1, "qty_step": 0.0001,
             "max_lots_per_side": 50, "max_notional_usd": 10000, "stress_budget_frac": 0,
             "portfolio_free_usd": 10000, "target_pct": 1}
    g.st = {"halted": False, "halt_reason": "", "fee_checked": 0}
    for side in ("LONG", "SHORT"):
        g.st[side] = {"lots": [], "entry": None, "pending": None, "strays": [], "fee_book": {},
                      "order_fills": {}, "fees": 0, "turnover": 0, "n_entries": 0}
    g.clock = 1000.0
    g.now = lambda: g.clock
    g._room_used = 0.0
    g.issues, g.journal, g.notifications = [], [], []
    g._issue = g.issues.append
    g._journal = g.journal.append
    g._notify = g.notifications.append
    g.save = lambda: None
    g._cid = lambda side, kind: "b7gB" + side[0] + kind + "audit"
    g._cancel = lambda order: None
    g._to_stray = lambda *args: (_ for _ in ()).throw(AssertionError("unexpected stray in fixture"))
    g.c = SimpleNamespace(user_trades=lambda *args, **kw: [], _offset_ms=0)
    g.open = {}
    g.label = "SYNTHETIC"
    return g


def record(name: str, classification: str, details: dict) -> None:
    RESULTS.append({"name": name, "classification": classification, "details": details})


def check_place_shapes() -> None:
    unknown = [None, {}, [], "garbage", {"orderId": "accepted"}, {"success": True}, {"success": "true", "orderId": "accepted"}]
    for response in unknown:
        g = fixture()
        g.c.place_limit = lambda *a, **kw: response
        out = g._place("LONG", "e", 100, False, 99.9, 100.1)
        assert out is None and g.st["LONG"]["pending"] is not None
        assert g._room_used == 100
    g = fixture()
    g.c.place_limit = lambda *a, **kw: {"success": False}
    assert g._place("LONG", "e", 100, False, 99.9, 100.1) is None
    assert g.st["LONG"]["pending"] is None and g._room_used == 0
    g.c.place_limit = lambda *a, **kw: {"success": True, "orderId": "ok"}
    assert g._place("LONG", "e", 100, False, 99.9, 100.1)["id"] == "ok"
    assert g.st["LONG"]["pending"] is None
    record("place_shape_guard", "FIX_VERIFIED", {"unknown_shapes_kept_pending": len(unknown), "explicit_false_releases": True})


def check_missing_trade_oid() -> None:
    g = fixture()
    g.c.user_trades = lambda *a, **kw: [{"id": "t1", "positionSide": "LONG", "side": "BUY", "price": "100", "qty": "1", "time": 800000}]
    found, complete = g._find_by_trades("b7gBLePending", 800, side="LONG", want="BUY", book={})
    assert found is None and complete is False
    g.st["LONG"]["pending"] = {"cid": "b7gBLePending", "kind": "e", "t": 800, "srv": 800, "absent": [900]}
    g._find_by_cid = lambda *a, **kw: (None, True)
    assert g._resolve_pending("LONG") is False
    assert g.st["LONG"]["pending"] is not None
    record("missing_trade_order_id", "FIX_VERIFIED", {"complete": complete, "pending_retained_after_TTL": True})


def check_fees() -> None:
    rows = [{"id": "t-own", "orderId": "OWN", "symbol": "BTCUSDT", "commission": "0.01", "maker": True},
            {"id": "t-other", "orderId": "OTHER", "symbol": "BTCUSDT", "commission": "7", "maker": True}]
    g = fixture()
    g.c.user_trades = lambda *a, **kw: rows
    delta, _ = g._fee_delta("LONG", "OWN")
    assert delta == 0.01
    g.st["LONG"]["fees"] = delta
    g.clock += 61
    g._settle_fees()
    assert math.isclose(g.st["LONG"]["fees"], 7.01)
    assert g.st["LONG"]["fee_book"]["OWN"]["done"] == 7.01
    record("foreign_fee_reenters_late_settlement", "REMAINING_DEFECT", {"correct_immediate_fee": delta, "after_late_settlement": g.st["LONG"]["fees"], "foreign_fee": 7})

    g = fixture()
    g.st["LONG"]["fee_book"]["OLD"] = {"done": 0.01, "t": 1, "t0": 1}
    g.clock = 5000
    g.c.user_trades = lambda *a, **kw: None
    g._settle_fees()
    assert "OLD" not in g.st["LONG"]["fee_book"] and not g.issues
    record("null_late_fee_response_prunes_cursor", "REMAINING_DEFECT", {"cursor_pruned": True, "issue_count": 0, "partial_fee_previously_known": 0.01})

    g = fixture()
    g.c.user_trades = lambda *a, **kw: [{"id": str(i), "orderId": "OWN", "symbol": "BTCUSDT", "commission": "1"} for i in range(100)]
    fee, _ = g._fee_delta("LONG", "OWN")
    assert fee == 100 and not g.issues
    record("fee_100_row_cap_not_detected", "REMAINING_LIMIT", {"returned_fee": fee, "possible_true_101_fill_fee": 101, "issue_count": 0, "actual_live_truncation_not_observed": True})


def check_tag_and_history() -> None:
    for tag in ("L", "S", "l", "s"):
        try:
            ns["cid_tag"]({"symbol": "BTCUSDT", "cid_tag": tag})
        except ConfigError:
            pass
        else:
            raise AssertionError(tag)
    record("reserved_explicit_tags", "FIX_VERIFIED", {"rejected": ["L", "S", "l", "s"]})

    g = fixture()
    a, b, m = 1000000, 1600000, 1300000
    rows = [{"orderId": str(i), "clientOrderId": f"foreign{i}", "time": a+i*4000} for i in range(150)]
    rows.append({"orderId": "own", "clientOrderId": "b7gBLe9", "time": m})
    g.c.order_history = lambda symbol, limit=100, page=0, start_ms=None, end_ms=None: sorted([r for r in rows if start_ms <= r["time"] < end_ms], key=lambda r: -r["time"])[:limit]
    found, _ = g._history_window("b7gBLe9", a, b, m, [8], split=True)
    assert found["orderId"] == "own"
    record("history_end_exclusive_midpoint", "FIX_VERIFIED", {"found_midpoint_order": True, "live_endpoint_contract_not_checked": True})


def check_fair_cursor() -> None:
    g = fixture()
    g._window_trades = lambda *a: ([{"id": str(i), "orderId": str(i)} for i in range(21)], True)
    called = []
    def detail(oid):
        called.append(oid)
        return ("live", {"orderId": oid, "clientOrderId": "b7gBLeWanted"}) if oid == "20" else ("unknown", {})
    g._detail = detail
    book = {}
    for _ in range(10):
        found, complete = g._find_by_trades("b7gBLeWanted", 800, book=book)
        assert found is None and complete is False
    assert len(called) == 200 and "20" not in called
    record("fair_cursor_open", "ACKNOWLEDGED_REMAINING_DEFECT", {"attempts": 10, "detail_requests": len(called), "own_21st_visited": False, "foreign_cache_size": len(book)})


def check_orphan_same_grid_sides() -> None:
    g = fixture()
    g.cfg["portfolio_free_usd"] = 350
    order = {"orderId": "old", "clientOrderId": "b7gBLeOld", "positionSide": "LONG", "price": "100", "origQty": "3", "executedQty": "1", "avgPrice": "100", "reduceOnly": False}
    g.open = {"old": order}
    g._orphans()
    assert g._room_used == 200
    assert g._take_entry_fill("LONG", g.st["LONG"]["entry"], order)
    assert len(g.st["LONG"]["lots"]) == 1 and g._room_used == 200
    g.c.place_limit = lambda *a, **kw: {"success": True, "orderId": "new-short"}
    new = g._place("SHORT", "e", 100, False, 99.9, 100)
    assert new is not None
    actual_obligation = 3*100 + 1*100
    assert actual_obligation > 350
    record("orphan_filled_mass_missing_within_same_grid", "REMAINING_DEFECT", {"scope": "generic_grid_with_both_sides_enabled_without_regime_closure", "cap": 350, "old_order_total": 300, "recorded_old_remaining_room_used": 200, "adopted_old_fill_lot": 100, "new_other_side_order": 100, "actual_total": actual_obligation, "live_occurrence_not_checked": True})


def check_sequential_runner() -> None:
    tree = ast.parse(SOURCES["services/weex_grid/loop.py"])
    runner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Runner")
    tick = next(n for n in runner.body if isinstance(n, ast.FunctionDef) and n.name == "tick")
    module = ast.Module(body=[ast.ClassDef(name="AuditRunner", bases=[], keywords=[], body=[tick], decorator_list=[])], type_ignores=[])
    glob = {"eg": SimpleNamespace(GRIDS=("A", "B", "C"), GridHalt=RuntimeError), "STATE_LOCK": threading.RLock(), "time": time, "logger": ns["logger"]}
    exec(compile(ast.fix_missing_locations(module), "<selected pinned runner AST>", "exec"), glob)
    r = glob["AuditRunner"]()
    free = iter([300, 200, 100])
    r._portfolio_free = lambda: next(free)
    r.trend = SimpleNamespace(tick=lambda **kw: None)
    got = []
    r.tick_one = lambda name, room: got.append([name, room])
    r.tick()
    assert got == [["A",300],["B",200],["C",100]]
    record("runner_sequential_free_refresh", "FIX_VERIFIED", {"calls": got, "parallel_counterexample_removed": True, "all_orphan_risk_not_proved_closed": True})


def main() -> None:
    check_place_shapes()
    check_missing_trade_oid()
    check_fees()
    check_tag_and_history()
    check_fair_cursor()
    check_orphan_same_grid_sides()
    check_sequential_runner()
    result = {"source_commit": COMMIT, "mode": "synthetic_selected_AST_only", "production_imports": 0, "network_calls": 0, "account_access": False, "cases": RESULTS}
    (ROOT / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"cases":len(RESULTS), "all_assertions_passed":True, "results":"results.json", "production_imports":0, "network_calls":0}))


if __name__ == "__main__":
    main()
