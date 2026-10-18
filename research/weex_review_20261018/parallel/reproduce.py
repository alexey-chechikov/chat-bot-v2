"""Offline counterexamples for pinned WEEX source. Never imports production modules.

Only explicitly selected AST function definitions are compiled. Every exchange,
state read, journal, and persistence operation is a local memory stub. No module
initialization, credentials, network, live state, or command/deployment code runs.
"""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import math
from pathlib import Path
from types import MethodType, SimpleNamespace

ROOT = Path(__file__).resolve().parent
COMMIT = "834887d82626b5c31f546079a2b80730ebf539f2"


def verified_trees():
    manifest = json.loads((ROOT / "PINNED_SOURCES.json").read_text(encoding="utf-8"))
    assert manifest["commit"] == COMMIT
    trees = {}
    for item in manifest["files"]:
        path = ROOT / item["file"]
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == item["sha256"], path
        git_blob = b"blob " + str(len(raw)).encode() + b"\0" + raw
        assert hashlib.sha1(git_blob).hexdigest() == item["git_blob_sha1"], path
        trees[path.name.split(".")[0]] = ast.parse(raw.decode("utf-8"), filename=str(path))
    return trees


def extract(tree, names, class_name=None):
    body = tree.body
    if class_name:
        body = next(x.body for x in body if isinstance(x, ast.ClassDef) and x.name == class_name)
    defs = [x for x in body if isinstance(x, ast.FunctionDef) and x.name in names]
    assert {x.name for x in defs} == set(names), names
    # No imports in any extracted definition. Global module body never executes.
    assert not any(isinstance(x, (ast.Import, ast.ImportFrom)) for d in defs for x in ast.walk(d))
    return defs


def environment(trees, cfgs, states=None):
    log = SimpleNamespace(exception=lambda *a, **kw: None, warning=lambda *a, **kw: None)
    ns = {"math": math, "grid_config": lambda name: cfgs[name],
          "eg": SimpleNamespace(GridHalt=Exception), "logger": log,
          "DIR": {"LONG": 1, "SHORT": -1}, "OPEN_SIDE": {"LONG": "BUY", "SHORT": "SELL"},
          "CLOSE_SIDE": {"LONG": "SELL", "SHORT": "BUY"},
          "PENDING_TTL": 120.0, "PENDING_RECHECK": 60.0, "PENDING_ABSENT_READS": 2,
          "_read": lambda key: (states or {})[key]}
    defs = extract(trees["loop"], {"_room_shares"}, "Runner")
    defs += extract(trees["engine"], {"may_add", "_entry_res", "_standing_res", "_pending_res",
                    "_place", "_with_cursor", "_resolve_pending", "_orphans", "_take_entry_fill", "_side"}, "Grid")
    defs += extract(trees["engine"], {"round_tick", "fmt_px"})
    defs += extract(trees["portfolio"], {"_order_res", "used_usd"})
    module = ast.Module(body=copy.deepcopy(defs), type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, "<pinned-selected-functions>", "exec"), ns)
    return ns


def side_state():
    return {"entry": None, "lots": [], "pending": None, "strays": [], "flatten": None,
            "order_fills": {}, "fees": 0.0, "turnover": 0.0, "n_entries": 0, "ref": None}


def configurations(side="LONG"):
    return {n: {"dry_run": False, "enabled": True, "symbol": "BTCUSDT", "order_qty": "1",
                "sides": [side]} for n in ("A", "B")}


def shares(ns, free):
    runner = SimpleNamespace(_client=lambda: SimpleNamespace(book=lambda symbol: (100.0, 100.0)))
    return ns["_room_shares"](runner, ["A", "B"], free)


def grid(ns, free, side="LONG", exchange=None):
    cfg = {"order_qty": "1", "max_lots_per_side": 100, "max_notional_usd": 10_000,
           "portfolio_free_usd": free, "stress_budget_frac": 0, "price_tick": 0.1,
           "target_pct": 1, "symbol": "BTCUSDT", "step_pct": 0.1, "trail_min_move_pct": 0.05}
    obj = SimpleNamespace(cfg=cfg, st={"halted": False, "LONG": side_state(), "SHORT": side_state()},
                          open={}, _room_used=0.0, save=lambda: None, now=lambda: 1000.0,
                          _fee_delta=lambda *args: (0.0, True), _mark_fills=lambda *args: None,
                          _tiny=lambda: 1e-9, _qty_str=lambda q: str(q), _journal=lambda x: None,
                          _slots=lambda s: len(obj.st[s]["lots"]), _cid=lambda s, k: "b7gALe1000",
                          _issue=lambda msg: None, _notify=lambda msg: None, label="SYNTHETIC",
                          c=exchange or SimpleNamespace(_offset_ms=0))
    for name in ("may_add", "_entry_res", "_standing_res", "_pending_res", "_with_cursor",
                 "_resolve_pending", "_take_entry_fill", "_place"):
        setattr(obj, name, MethodType(ns[name], obj))
    return obj


def orphan_counterexample(trees):
    ns = environment(trees, configurations())
    allocation = shares(ns, 350.0)
    a_transport = MemoryPlacement({"success": True, "orderId": "fake-tp"})
    b_transport = MemoryPlacement({"success": True, "orderId": "fake-B-entry"})
    a = grid(ns, allocation["A"], exchange=a_transport)
    b = grid(ns, allocation["B"], exchange=b_transport)
    a.open = {"orphan": {"positionSide": "LONG", "price": "100", "origQty": "3",
                         "executedQty": "1", "avgPrice": "100", "clientOrderId": "b7gALe0",
                         "reduceOnly": False}}
    ns["_orphans"](a)
    ns["_take_entry_fill"](a, "LONG", a.st["LONG"]["entry"], a.open["orphan"])
    a_ok = a.may_add("LONG", 100.0, 100.0, qty=2.0, parent="orphan")
    b_ok = b.may_add("LONG", 100.0, 100.0)
    assert a_ok[0] and b_ok[0]
    # Execute the actual full _side; a partially filled old-size entry is held.
    ns["_side"](a, "LONG", 99.0, 100.0, 99.5, {"orphan"}, enabled=True)
    assert a.st["LONG"]["entry"]["id"] == "orphan"
    b.st["LONG"]["entry"] = ns["_place"](b, "LONG", "e", 100.0, False, 100.0, 101.0)
    assert b.st["LONG"]["entry"]["id"] == "fake-B-entry"
    assert float(a.st["LONG"]["entry"]["filled"]) > 0
    assert a._room_used == 200.0
    actual_existing = 3.0 * 100.0
    new_b = 100.0
    assert actual_existing + new_b > 350.0
    return {"case": "orphan_old_size_partial_fill", "status": "ISSUE_REPRODUCED",
            "cap": 350.0, "snapshot_recorded_used": 0.0, "actual_preexisting_exposure": actual_existing,
            "shares": allocation, "orphan_original_qty": 3, "current_config_qty": 1,
            "orphan_filled_qty": 1, "A_room_used": a._room_used,
            "A_holds_remaining": a_ok[0], "B_may_add": b_ok[0], "full_side_executed": True,
            "aggregate_after_B_add": 400.0, "overflow": 50.0}


def price_counterexample(trees, side, free, final_price, label):
    ns = environment(trees, configurations(side))
    allocation = shares(ns, free)
    accepted = []
    for name in ("A", "B"):
        transport = MemoryPlacement({"success": True, "orderId": "fake-" + name})
        g = grid(ns, allocation[name], side, exchange=transport)
        ok, reason = g.may_add(side, final_price, final_price)
        bid, ask = (final_price, final_price + 1.0) if side == "LONG" else (99.0, 101.0)
        mid = (bid + ask) / 2
        g.cfg["step_pct"] = (1.0 - final_price / mid) * 100 if side == "LONG" else 5.0
        # The real _side computes desired from ref/step, then calls the real _place.
        ns["_side"](g, side, bid, ask, mid, set(), enabled=True)
        result = g.st[side]["entry"]
        assert result and transport.accepted[0]["price"] == final_price
        accepted.append({"grid": name, "may_add": ok, "reason": reason, "actual_place_returned_id": True,
                         "full_side_executed": True, "step_pct": g.cfg["step_pct"]})
    total = 2 * final_price
    assert all(x["may_add"] for x in accepted) and total > free
    return {"case": label, "status": "ISSUE_REPRODUCED", "side": side,
            "allocation_ask": 100.0, "budget_per_peer": 101.0, "free": free,
            "shares": allocation, "final_price": final_price, "accepted": accepted,
            "aggregate_notional": total, "overflow": total - free}


def existing_pending_control(trees):
    state = {"LONG": side_state(), "SHORT": side_state()}
    state["LONG"]["pending"] = {"kind": "e", "qty": "3", "price": 100.0,
                                 "cid": "b7gALe0", "t": 999.0, "srv": 999.0}
    ns = environment(trees, configurations(), {"A": state})
    used_before = ns["used_usd"](["A"], [])
    a = grid(ns, 50.0)
    a.st.update(state)
    a._find_by_cid = lambda *args: ({"orderId": "existing", "status": "NEW"}, True)
    assert ns["_resolve_pending"](a, "LONG")
    used_after = ns["used_usd"](["A"], [])
    assert used_before == used_after == 300.0
    assert state["LONG"]["pending"] is None and state["LONG"]["entry"]["qty"] == "3"
    return {"case": "existing_pending_recovery", "status": "CONTROL_PASSED",
            "used_before": used_before, "used_after": used_after,
            "cap": 350.0, "free_before_and_after": 50.0,
            "explanation": "Actual pending qty is reserved despite smaller current config qty; recovery preserves it."}


class MemoryPlacement:
    """Fake transport only. Records an accepted intent and supplies a chosen response."""
    _offset_ms = 0

    def __init__(self, response=None, lose=False):
        self.response = response
        self.lose = lose
        self.accepted = []

    def place_limit(self, symbol, side, position_side, qty, price, cid, **kwargs):
        self.accepted.append({"qty": float(qty), "price": float(price), "cid": cid})
        if self.lose:
            raise TimeoutError("synthetic transport loss after exchange acceptance")
        return self.response


def placement_response_case(trees, response, lose=False, label=""):
    ns = environment(trees, configurations())
    exchange = MemoryPlacement(response, lose)
    a = grid(ns, 150.0, exchange=exchange)
    result = ns["_place"](a, "LONG", "e", 99.0, False, 100.0, 101.0)
    assert result is None and len(exchange.accepted) == 1
    ns["_read"] = lambda key: a.st
    recorded_used = ns["used_usd"](["A"], [])
    if lose or (isinstance(response, dict) and response.get("success")):
        assert a.st["LONG"]["pending"] and a._room_used == recorded_used == 99.0
        status = "CONTROL_PASSED"
    else:
        assert a.st["LONG"]["pending"] is None and a._room_used == recorded_used == 0.0
        status = "ISSUE_REPRODUCED"
    return {"case": label, "status": status, "fake_exchange_accepted_notional": 99.0,
            "pending_kept": a.st["LONG"]["pending"] is not None,
            "room_used": a._room_used, "portfolio_recorded_used": recorded_used,
            "scope": "Synthetic response contract; no claim real WEEX returned this response."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="Optional research JSON output; default prints only.")
    args = parser.parse_args()
    trees = verified_trees()
    cases = [orphan_counterexample(trees),
             price_counterexample(trees, "SHORT", 206.0, 105.0, "short_entry_5pct_exceeds_ask_reserve"),
             price_counterexample(trees, "LONG", 203.0, 102.0, "long_price_changes_after_budget_snapshot"),
             existing_pending_control(trees),
             placement_response_case(trees, None, lose=True, label="new_placement_timeout"),
             placement_response_case(trees, {"success": True}, label="success_missing_id"),
             placement_response_case(trees, None, label="null_response_is_not_proven_rejection"),
             placement_response_case(trees, {}, label="empty_object_is_not_proven_rejection")]
    report = {"schema": "weex-parallel-offline-reproduction-v1", "commit": COMMIT,
              "checks_passed": len(cases), "issue_cases": sum(x["status"] == "ISSUE_REPRODUCED" for x in cases),
              "control_cases": sum(x["status"] == "CONTROL_PASSED" for x in cases),
              "source_hashes_verified": True, "production_modules_imported": False,
              "network_requests": 0, "live_state_read": False, "cases": cases}
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        output = args.out.resolve()
        assert output.is_relative_to(ROOT), "Output must stay within this research package."
        output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
