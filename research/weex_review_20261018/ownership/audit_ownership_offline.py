"""Pure offline reproductions; never imports production modules or instantiates an API client.

Reads pinned inert GitHub source text, verifies SHA256 and Git blob IDs, extracts ONLY
allowlisted function definitions via AST, and runs them against synthetic objects.
The only writes are results.json inside this research directory.
"""
from __future__ import annotations

import ast
import hashlib
import json
import logging
import math
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPOSITORY = "alexey-chechikov/chat-bot-v2"
REF = "1d0da80863226acda8fdf57d07eee087fc08ef2c"


def sources():
    manifest = json.loads((ROOT / "VERIFIED_SOURCES.json").read_text("utf-8"))
    assert manifest["repository"] == REPOSITORY and manifest["ref"] == REF
    trees, hashes = {}, []
    for rec in manifest["sources"]:
        path = (ROOT / rec["local_path"]).resolve()
        assert ROOT in path.parents
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        assert sha == rec["sha256"] and blob == rec["blob_sha"], rec["key"]
        trees[rec["key"]] = ast.parse(raw.decode("utf-8"))
        hashes.append({**rec, "verified": True})
    return trees, hashes


def extract(tree, names, namespace, class_name=None):
    if class_name is not None:
        node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
        available = node.body
    else:
        available = tree.body
    functions = [n for n in available if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in functions} == set(names)
    # No import statements or module/class initializers from source are executed.
    for function in functions:
        assert not any(isinstance(n, (ast.Import, ast.ImportFrom)) for n in ast.walk(function))
        assert not function.decorator_list
    exec(compile(ast.Module(body=functions, type_ignores=[]), "<pinned-synthetic-functions>", "exec"), namespace)
    return {n.name: {"start_line": n.lineno, "end_line": n.end_lineno} for n in functions}


def run():
    trees, hashes = sources()
    logger = logging.getLogger("ownership.synthetic")
    logger.handlers[:] = [logging.NullHandler()]
    logger.propagate = False
    ns = {
        "math": math, "re": re, "logger": logger,
        "DIR": {"LONG": 1, "SHORT": -1},
        "TRADES_DETAILS": 20, "TRADES_SPLIT_BUDGET": 8,
        "PENDING_TTL": 120.0, "PENDING_RECHECK": 30.0, "PENDING_ABSENT_READS": 2,
        "OPEN_SIDE": {"LONG": "BUY", "SHORT": "SELL"},
        "CLOSE_SIDE": {"LONG": "SELL", "SHORT": "BUY"},
        "FEE_POLL": 60.0, "FEE_BATCH": 5, "FEE_WINDOW": 3600.0,
        "TAG_RE": re.compile(r"[A-Za-z0-9]"),
        "BOT": "bot", "MANUAL": "manual", "OTHER": "other",
        "LEGACY_BTC": re.compile(r"b7g[LS][a-z]\d"),
        "FUTURES": "SYNTHETIC_NO_NETWORK",
        "WeexIncomplete": type("WeexIncomplete", (Exception,), {}),
        "ConfigError": type("ConfigError", (Exception,), {}),
    }
    engine_functions = [
        "_find_by_trades", "_window_trades", "_resolve_pending",
        "_history_window", "_fee_delta", "_settle_fees",
    ]
    lines = extract(trees["engine"], engine_functions, ns, "Grid")
    lines.update(extract(trees["engine"], ["cid_tag"], ns))
    lines.update(extract(trees["monitor"], ["cid_owner"], ns))
    client_class = next(
        n.name for n in trees["client"].body if isinstance(n, ast.ClassDef)
        and any(isinstance(x, ast.FunctionDef) and x.name == "user_trades" for x in n.body)
    )
    lines["client.user_trades"] = extract(trees["client"], ["user_trades"], ns, client_class)["user_trades"]
    cases = []

    class MissingOID:
        _find_by_trades = ns["_find_by_trades"]
        _window_trades = ns["_window_trades"]
        _resolve_pending = ns["_resolve_pending"]
        cfg = {"symbol": "BTCUSDT"}
        label = "B34 BTCUSDT"

        def __init__(self):
            self.c = self
            self.messages = []
            self.st = {"LONG": {"pending": {
                "cid": "b7g3LeOWN", "t": 800.0, "srv": 800.0,
                "kind": "e", "price": 100.0, "absent": [950.0],
            }}}

        def now(self):
            return 1000.0

        def user_trades(self, *args, **kwargs):
            return [{
                "id": "synthetic-t1", "positionSide": "LONG", "side": "BUY",
                "price": "100", "qty": "0.0012", "time": 800000,
                # Deliberately malformed provider response: orderId is absent.
            }]

        def _referenced(self, side):
            return set()

        def _find_by_cid(self, *args):
            return None, True

        def _notify(self, msg):
            self.messages.append(msg)

        def _issue(self, *args):
            pass

        def save(self):
            pass

    malformed = MissingOID()
    row, complete = malformed._find_by_trades("b7g3LeOWN", 800.0, side="LONG", want="BUY")
    resolved = malformed._resolve_pending("LONG")
    assert row is None and complete is True
    assert resolved is True and malformed.st["LONG"]["pending"] is None
    cases.append({
        "id": "P1_malformed_trade_false_absence", "reproduced": True,
        "scope": "conditional_on_malformed_provider_input; no evidence provider currently returns this",
        "trade_search_complete": complete, "resolve_return": resolved, "pending_after": None,
        "risk": "pending released; the next normal pass can permit a second entry",
        "source": ["engine.py:828-833", "engine.py:787-789", "engine.py:894-914"],
    })

    class Search:
        _find_by_trades = ns["_find_by_trades"]

        def __init__(self, broken=False):
            self.calls, self.broken = [], broken

        def _window_trades(self, *args):
            return ([{
                "orderId": str(i), "positionSide": "LONG", "side": "BUY"
            } for i in range(1, 22)], True)

        def _referenced(self, side):
            return set()

        def _detail(self, oid):
            self.calls.append(oid)
            if self.broken and int(oid) <= 20:
                return "unknown", {}
            return "terminal", {"orderId": oid, "clientOrderId": "own" if oid == "21" else "other"}

    search_results = []
    for broken in [False, True]:
        instance, book, found = Search(broken), {}, None
        for attempt in range(1, 101):
            found, complete = instance._find_by_trades("own", 1.0, side="LONG", want="BUY", book=book)
            if found:
                break
        search_results.append({
            "broken_first20": broken, "attempts": attempt, "found": found is not None,
            "detail_requests": len(instance.calls), "own21_requested": "21" in instance.calls,
            "foreign_cached": len(book), "complete": complete,
        })
    assert search_results[0]["attempts"] == 2 and search_results[0]["found"]
    assert not search_results[1]["found"] and not search_results[1]["own21_requested"]
    cases.append({
        "id": "P2_unknown20_starvation", "reproduced": True, "runs": search_results,
        "scope": "conditional_on_persistent_unknown_or_CIDless_neighbour_details",
        "risk": "fails closed but own filled entry can remain unaccounted and without its take profit",
        "source": ["engine.py:785-811"],
    })

    class LimitClient:
        user_trades = ns["user_trades"]

        def get(self, base, path, params):
            assert base == "SYNTHETIC_NO_NETWORK" and path == "/capi/v3/userTrades"
            self.requests.append(dict(params))
            return list(self.response_rows[-int(params["limit"]):])

    class Fees(LimitClient):
        _fee_delta = ns["_fee_delta"]
        _settle_fees = ns["_settle_fees"]

        def __init__(self, rows):
            self.c, self.cfg = self, {"symbol": "BTCUSDT"}
            self.requests, self.response_rows = [], rows
            self.clock, self.events = 1000.0, []
            self.st = {
                "LONG": {"fee_book": {}, "fees": 0.0},
                "SHORT": {"fee_book": {}, "fees": 0.0},
            }

        def now(self):
            return self.clock

        def _issue(self, *args):
            self.events.append(args)

        def _journal(self, record):
            self.events.append(record)

        def _referenced(self, side):
            return set()

    foreign = Fees([{"id": "foreign-fill", "orderId": "NEIGHBOUR", "commission": "7.0", "maker": True}])
    foreign_fee, _ = foreign._fee_delta("LONG", "OWN")
    assert foreign_fee == 7.0 and foreign.requests[0]["orderId"] == "OWN"
    cases.append({
        "id": "P2_foreign_trade_fee", "reproduced": True,
        "scope": "preexisting_robustness_gap_conditional_on_wrong_order_rows_from_provider",
        "requested_order": "OWN", "returned_order": "NEIGHBOUR", "fee_charged_to_OWN": foreign_fee,
        "source": ["engine.py:476-492", "engine.py:541-553"],
    })

    rows101 = [{
        "id": str(i), "orderId": "OWN", "commission": "0.01", "maker": True,
    } for i in range(101)]
    dense = Fees(rows101)
    charged, _ = dense._fee_delta("LONG", "OWN")
    dense.st["LONG"]["fees"] += charged
    dense.clock = 5000.0  # Past fee cursor expiry; repeat returns the same latest 100 fills.
    dense._settle_fees()
    actual_sum = sum(float(row["commission"]) for row in rows101)
    assert math.isclose(actual_sum, 1.01) and math.isclose(charged, 1.0)
    assert "OWN" not in dense.st["LONG"]["fee_book"]
    assert not any(isinstance(ev, dict) and ev.get("kind") == "комиссия не найдена за час" for ev in dense.events)
    cases.append({
        "id": "P2_101_fills_fee_cap100", "reproduced": True,
        "scope": "preexisting_gap_conditional_on_more_than_100_fills_for_one_order",
        "true_fill_count": 101, "api_limit": dense.requests[0]["limit"],
        "true_commission": actual_sum, "charged_commission": dense.st["LONG"]["fees"],
        "fee_cursor_expired": True, "incompleteness_warning": False,
        "source": ["client.py:196-206", "engine.py:476-492", "engine.py:526-560"],
    })

    tag = ns["cid_tag"]({"symbol": "BTCUSDT", "cid_tag": "L"})
    legacy = "b7gLe17600002"
    owner = ns["cid_owner"](legacy, "old", "b7gB", set(), ("b7gL",), "b7g")
    assert tag == "L" and legacy.startswith("b7g" + tag) and owner == "other"
    cases.append({
        "id": "P2_reserved_legacy_tag", "reproduced": True,
        "scope": "configuration_guard_gap; current_tags_3_4_8_unaffected",
        "accepted_tag": tag, "legacy_cid": legacy,
        "new_L_grid_prefix_owns_legacy": True, "BTC_monitor_with_L_peer": owner,
        "source": ["engine.py:132-146", "engine.py:181-191", "monitor.py:174-179"],
    })

    class History:
        _history_window = ns["_history_window"]
        cfg = {"symbol": "BTCUSDT"}

        def __init__(self, exclusive, target):
            self.exclusive, self.target = exclusive, target
            self.c, self.calls = self, []

        @staticmethod
        def _orders_list(rows, what):
            return rows

        def order_history(self, symbol, limit, page, start_ms, end_ms):
            self.calls.append([start_ms, end_ms])
            covered = start_ms <= self.target and (
                self.target < end_ms if self.exclusive else self.target <= end_ms
            )
            return [{"orderId": "target", "clientOrderId": "own"}] if covered else []

    history_results = []
    for exclusive in [False, True]:
        for target in [0, 2000, 2001, 4000]:
            hist = History(exclusive, target)
            row, complete = hist._history_window("own", 0, 4000, 2000, [8], split=True)
            history_results.append({
                "end_exclusive": exclusive, "target_ms": target,
                "found": row is not None, "complete": complete, "requests": hist.calls,
            })
    assert all(r["found"] for r in history_results if not r["end_exclusive"])
    assert any(r["end_exclusive"] and r["target_ms"] == 2000 and not r["found"] and r["complete"]
               for r in history_results)
    cases.append({
        "id": "CONDITIONAL_history_boundary_contract", "reproduced": True,
        "scope": "arithmetic_correct_for_inclusive_integer_ms; actual_WEEX_boundary_contract_NOT_verified",
        "not_a_confirmed_live_provider_bug": True, "runs": history_results,
        "source": ["engine.py:739-766", "client.py:134-148"],
    })
    result = {
        "schema": "weex-ownership-offline-audit-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository": REPOSITORY, "ref": REF,
        "network_requests": 0, "production_imports": 0, "real_account_inputs": 0,
        "live_deployment_verified": False,
        "source_integrity": hashes, "extracted_function_lines": lines,
        "all_reproductions_asserted": True, "cases": cases,
    }
    target = ROOT / "results.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "reproduced", "cases": len(cases), "verified_sources": len(hashes),
        "results_path": str(target), "network_requests": 0,
    }, ensure_ascii=False))


if __name__ == "__main__":
    run()
