"""Offline metrics and prospective closed-bar outcomes for archived daily context."""
from __future__ import annotations

import argparse
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import uuid4

SCHEMA = "daily-context-analytics-v1"
STEP = 900000
HORIZONS = (15, 60, 240, 1440)
BAR_IDS = ("binance_spot_15m", "binance_perp_15m")
STABLE = {"symbol", "exchange", "exchanges", "model", "mode", "window", "windows_hours", "interval",
          "bar_interval", "timeframe", "threshold", "merge", "range_percent", "currency", "units",
          "delta_formula", "CVD_level_used_as_flow", "closure_clock", "clock_role", "timestamp_semantics",
          "requested_closed_bars", "expected_points", "settlement_interval_assumed", "liquidation_map",
          "cross_market_clock_alignment_unmeasured"}


def utc(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def digest(body):
    return hashlib.sha256(body).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def dec(value, nonnegative=False):
    if isinstance(value, bool) or value is None:
        raise ValueError("invalid number")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid number") from exc
    if not result.is_finite() or (nonnegative and result < 0):
        raise ValueError("nonfinite or negative amount")
    return result


def integer(value):
    if type(value) is not int or value < 0:
        raise ValueError("timestamp must be nonnegative integer")
    return value


def val(value):
    return None if value is None else str(value)


def fraction(a, b):
    return a / b if b else None


def change(current, previous):
    a, b = dec(current), dec(previous)
    return {"absolute": val(a - b), "relative_fraction": val(fraction(a - b, b))}


def semantics(source):
    settings = source.get("settings", {})
    parts = urlsplit(source.get("url") or "")
    return {"source_id": source["id"], "source_path": f"{parts.scheme}://{parts.netloc}{parts.path}",
            "market_scope": source.get("market_scope"), "aggregation": source.get("aggregation"),
            "settings": {k: settings[k] for k in sorted(STABLE) if k in settings}}


def semantic_hash(source):
    return digest(encoded(semantics(source)))


def observations(source):
    for value in source.get("values") or []:
        if value.get("name") == "observations" and value.get("type") == "json" and isinstance(value.get("value"), list):
            return value["value"]
    return []


def parse_bars(source, asof_ms):
    bars, conflicts, rejected = {}, set(), []
    for row in observations(source):
        try:
            start, end = integer(row["bar_start_ms"]), integer(row["bar_end_ms"])
            if row.get("closed") is not True or start % STEP or end != start + STEP or end > asof_ms:
                raise ValueError("forming/future/non-grid bar")
            parsed = {"start": start, "end": end}
            for key in ("open", "high", "low", "close", "base_volume", "quote_volume", "taker_buy_base", "taker_buy_quote"):
                parsed[key] = dec(row[key], nonnegative=True)
            if min(parsed[k] for k in ("open", "high", "low", "close")) <= 0:
                raise ValueError("nonpositive price")
            if parsed["high"] < max(parsed["open"], parsed["close"]) or parsed["low"] > min(parsed["open"], parsed["close"]) or parsed["low"] > parsed["high"]:
                raise ValueError("invalid OHLC range")
            if parsed["taker_buy_base"] > parsed["base_volume"] or parsed["taker_buy_quote"] > parsed["quote_volume"]:
                raise ValueError("taker volume exceeds total")
            if start in bars and bars[start] != parsed:
                conflicts.add(start)
            bars[start] = parsed
        except (ValueError, KeyError, TypeError) as exc:
            rejected.append(str(exc))
    for start in conflicts:
        bars.pop(start, None)
    return bars, {"raw_rows": len(observations(source)), "valid_unique_rows": len(bars),
                  "conflicting_timestamps": sorted(conflicts), "rejected_rows": rejected}


def metric(name, value, unit, definition=None):
    return {"name": name, "value": val(value), "unit": unit, "definition": definition or name}


def flow_stats(rows):
    base = sum(r["base_volume"] for r in rows)
    quote_volume = sum(r["quote_volume"] for r in rows)
    buy_base = sum(r["taker_buy_base"] for r in rows)
    buy_quote = sum(r["taker_buy_quote"] for r in rows)
    return {"open_USDT": rows[0]["open"], "close_USDT": rows[-1]["close"],
            "return_pct": (rows[-1]["close"] / rows[0]["open"] - 1) * 100,
            "base_volume_BTC": base, "quote_volume_USDT": quote_volume,
            "taker_buy_base_BTC": buy_base, "taker_sell_base_BTC": base - buy_base,
            "delta_base_BTC": 2 * buy_base - base,
            "taker_buy_quote_USDT": buy_quote, "taker_sell_quote_USDT": quote_volume - buy_quote,
            "delta_quote_USDT": 2 * buy_quote - quote_volume,
            "F_volume_weighted_fraction": fraction(2 * buy_base - base, base)}


def market_metrics(source, asof_ms):
    bars, quality = parse_bars(source, asof_ms)
    settings = source.get("settings", {})
    start, end = settings.get("start_ms_inclusive"), settings.get("end_ms_exclusive")
    valid_window = (settings.get("symbol") == "BTCUSDT" and settings.get("interval") == "15m" and
                    type(start) is int and type(end) is int and start % STEP == 0 and end - start == 96 * STEP)
    expected = list(range(start, end, STEP)) if valid_window else []
    missing = [t for t in expected if t not in bars]
    extra = [t for t in bars if t not in expected]
    complete = valid_window and not missing and not extra and len(bars) == 96 and not quality["rejected_rows"] and not quality["conflicting_timestamps"]
    quality.update(expected_closed_bars=96, missing_timestamps=missing, extra_timestamps=sorted(extra),
                   declared_window_valid=valid_window, complete_96_closed=complete)
    result = {"source_id": source["id"], "semantic_hash": semantic_hash(source), "semantics": semantics(source),
              "status": "OK" if complete else "MISSING", "window_start_ms": start, "window_end_ms": end,
              "coverage": quality, "metrics": []}
    if not complete:
        return result, bars
    rows = [bars[t] for t in expected]
    first, last = rows[0], rows[-1]
    base = sum(r["base_volume"] for r in rows)
    quote = sum(r["quote_volume"] for r in rows)
    buy_base = sum(r["taker_buy_base"] for r in rows)
    buy_quote = sum(r["taker_buy_quote"] for r in rows)
    delta_base, delta_quote = 2 * buy_base - base, 2 * buy_quote - quote
    result["metrics"] = [metric("first_open", first["open"], "USDT"), metric("last_close", last["close"], "USDT"),
                         metric("high_24h", max(r["high"] for r in rows), "USDT"),
                         metric("low_24h", min(r["low"] for r in rows), "USDT"),
                         metric("return_24h_pct", (last["close"] / first["open"] - 1) * 100, "percent", "96 closed bars first-open to last-close"),
                         metric("return_1h_pct", (last["close"] / rows[-4]["open"] - 1) * 100, "percent", "last4 closed bars first-open to last-close"),
                         metric("return_4h_pct", (last["close"] / rows[-16]["open"] - 1) * 100, "percent", "last16 closed bars first-open to last-close"),
                         metric("base_volume_24h", base, "BTC"), metric("quote_volume_24h", quote, "USDT"),
                         metric("taker_buy_base_24h", buy_base, "BTC"), metric("taker_sell_base_24h", base - buy_base, "BTC"),
                         metric("delta_base_24h", delta_base, "BTC", "2*sum(taker_buy_base)-sum(base_volume)"),
                         metric("taker_buy_quote_24h", buy_quote, "USDT"), metric("taker_sell_quote_24h", quote - buy_quote, "USDT"),
                         metric("delta_quote_24h", delta_quote, "USDT", "2*sum(taker_buy_quote)-sum(quote_volume)"),
                         metric("F_volume_weighted", fraction(delta_base, base), "fraction", "sum(delta_base)/sum(base_volume)")]
    for hours, count in ((1, 4), (4, 16)):
        current_stats, previous_stats = flow_stats(rows[-count:]), flow_stats(rows[-2 * count:-count])
        for name, key, unit in (("base_volume", "base_volume_BTC", "BTC"), ("quote_volume", "quote_volume_USDT", "USDT"),
                                ("delta_base", "delta_base_BTC", "BTC"), ("delta_quote", "delta_quote_USDT", "USDT"),
                                ("taker_buy_base", "taker_buy_base_BTC", "BTC"), ("taker_sell_base", "taker_sell_base_BTC", "BTC"),
                                ("taker_buy_quote", "taker_buy_quote_USDT", "USDT"), ("taker_sell_quote", "taker_sell_quote_USDT", "USDT"),
                                ("F_volume_weighted", "F_volume_weighted_fraction", "fraction")):
            result["metrics"].append(metric(f"{name}_{hours}h", current_stats[key], unit))
        for name, key, unit in (("base_volume", "base_volume_BTC", "BTC"), ("quote_volume", "quote_volume_USDT", "USDT")):
            current_value, old_value = current_stats[key], previous_stats[key]
            result["metrics"] += [metric(f"{name}_{hours}h_vs_previous_{hours}h_change", current_value - old_value, unit),
                                  metric(f"{name}_{hours}h_vs_previous_{hours}h_change_pct", fraction((current_value - old_value) * 100, old_value), "percent")]
    result["hourly_blocks_last4h"] = [{"start_ms": rows[start]["start"], "end_ms": rows[start + 3]["end"],
                                        **{k: val(v) for k, v in flow_stats(rows[start:start + 4]).items()}}
                                       for start in range(80, 96, 4)]
    return result, bars


def parse_oi(source, asof_ms):
    points, conflicts, rejected = {}, set(), []
    for row in observations(source):
        try:
            t = integer(row["timestamp_ms"])
            point = {"quantity": dec(row["sum_open_interest"], True), "value": dec(row["sum_open_interest_value"], True),
                     "quantity_unit": row["quantity_unit"], "value_unit": row["value_unit"]}
            if (t > asof_ms or t % STEP or not isinstance(point["quantity_unit"], str) or not point["quantity_unit"] or
                    not isinstance(point["value_unit"], str) or not point["value_unit"]):
                raise ValueError("invalid OI grid/unit")
            if t in points and points[t] != point:
                conflicts.add(t)
            points[t] = point
        except (ValueError, KeyError, TypeError) as exc:
            rejected.append(str(exc))
    for t in conflicts:
        points.pop(t, None)
    return points, conflicts, rejected


def oi_metrics(source, perp, asof_ms):
    points, conflicts, rejected = parse_oi(source, asof_ms)
    settings = source.get("settings", {})
    start, end = settings.get("start_ms_inclusive"), settings.get("end_ms_inclusive")
    declared = type(start) is int and type(end) is int and start % STEP == 0 and end - start == 96 * STEP
    expected = list(range(start, end + STEP, STEP)) if declared else []
    missing = [t for t in expected if t not in points]
    units = {(p["quantity_unit"], p["value_unit"]) for p in points.values()}
    usable = declared and start in points and end in points and len(units) == 1
    aligned = bool(perp and perp["window_start_ms"] == start and perp["window_end_ms"] == end and perp["coverage"]["complete_96_closed"])
    definition = {**semantics(source), "row_units": sorted(units)}
    result = {"source_id": source["id"], "semantic_hash": digest(encoded(definition)), "semantics": definition,
              "status": "OK" if usable and not missing and not rejected and not conflicts and aligned else "PARTIAL",
              "window_start_ms": start, "window_end_ms": end, "perp_window_alignment": "matched" if aligned else "MISMATCH_OR_UNAVAILABLE",
              "coverage": {"expected_points": 97, "valid_points": len(points), "missing_timestamps": missing,
                           "conflicting_timestamps": sorted(conflicts), "rejected_rows": rejected}, "metrics": []}
    if usable:
        for key, unit_key in (("quantity", "quantity_unit"), ("value", "value_unit")):
            a, b = points[start][key], points[end][key]
            result["metrics"] += [metric(f"oi_{key}_first", a, points[start][unit_key]),
                                  metric(f"oi_{key}_last", b, points[start][unit_key]),
                                  metric(f"oi_{key}_change", b - a, points[start][unit_key]),
                                  metric(f"oi_{key}_change_pct", fraction((b - a) * 100, a), "percent", f"OI {key} endpoints; not directional positions")]
        for hours, count in ((1, 4), (4, 16)):
            t = end - count * STEP
            if t in points:
                for key, unit_key in (("quantity", "quantity_unit"), ("value", "value_unit")):
                    old, current = points[t][key], points[end][key]
                    result["metrics"] += [metric(f"oi_{key}_change_{hours}h", current - old, points[t][unit_key]),
                                          metric(f"oi_{key}_change_{hours}h_pct", fraction((current - old) * 100, old), "percent")]
        result["hourly_blocks_last4h"] = []
        for t in range(end - 16 * STEP, end, 4 * STEP):
            if t in points and t + 4 * STEP in points:
                block = {"start_ms": t, "end_ms": t + 4 * STEP}
                for key, unit_key in (("quantity", "quantity_unit"), ("value", "value_unit")):
                    old, current = points[t][key], points[t + 4 * STEP][key]
                    block[f"oi_{key}_change"] = str(current - old)
                    block[f"oi_{key}_change_pct"] = val(fraction((current - old) * 100, old))
                    block[f"oi_{key}_unit"] = points[t][unit_key]
                result["hourly_blocks_last4h"].append(block)
    return result


def funding_metrics(source, now_ms):
    events, rejected, conflicts = {}, [], set()
    settings = source.get("settings", {})
    for row in observations(source):
        try:
            t = integer(row["funding_time_ms"])
            rate = dec(row["funding_rate_fraction"])
            rate_type = row.get("rate_type")
            if rate_type is not None and not isinstance(rate_type, str):
                raise ValueError("invalid rate_type")
            key = (t, rate_type)
            if t > now_ms or t < settings.get("start_ms_inclusive", 0) or t > settings.get("end_ms_inclusive", now_ms):
                raise ValueError("future/out-of-window funding event")
            if key in events and events[key]["rate"] != rate:
                conflicts.add(key)
                raise ValueError("conflicting funding event")
            events[key] = {"rate": rate, "rate_type": rate_type}
        except (ValueError, KeyError, TypeError) as exc:
            rejected.append(str(exc))
    for key in conflicts:
        events.pop(key, None)
    ordered = sorted(events, key=lambda item: (item[0], item[1] or ""))
    total = sum((events[key]["rate"] for key in ordered), Decimal(0))
    return {"source_id": source["id"], "semantic_hash": semantic_hash(source), "semantics": semantics(source),
            "status": ("OK" if not rejected else "PARTIAL") if ordered else "MISSING",
            "comparison_eligible": bool(ordered) and not rejected and not conflicts, "settlement_interval_assumed": False,
            "events": [{"timestamp_ms": key[0], "timestamp_utc": utc(key[0]), "rate_fraction": str(events[key]["rate"]), "rate_type": key[1]} for key in ordered],
            "observed_intervals_ms": [b[0] - aa[0] for aa, b in zip(ordered, ordered[1:])], "rejected_rows": rejected,
            "conflicting_event_keys": [{"timestamp_ms": key[0], "rate_type": key[1]} for key in sorted(conflicts, key=lambda item: (item[0], item[1] or ""))],
            "metrics": [metric("funding_observed_event_count", len(ordered), "events"),
                        metric("funding_observed_signed_sum", total if ordered else None, "rate_fraction", "sum of observed events; no interval assumption"),
                        metric("funding_latest_observed_rate", events[ordered[-1]]["rate"] if ordered else None, "rate_fraction")]}


def simple_metrics(source):
    values = []
    for item in source.get("values") or []:
        if item.get("type") == "number":
            try:
                value = dec(item["value"]) if item.get("value") is not None else None
                values.append(metric(item["name"], value, item.get("unit")))
            except ValueError:
                values.append(metric(item["name"], None, item.get("unit")))
    return {"source_id": source["id"], "semantic_hash": semantic_hash(source), "semantics": semantics(source),
            "status": source.get("status"), "metrics": values}


def analyze_run(run, now_ms):
    report = run["report"]
    sources = {s["id"]: s for s in report.get("sources", [])}
    groups, bar_sets = {}, {}
    for sid in BAR_IDS:
        if sid in sources:
            groups[sid], bar_sets[sid] = market_metrics(sources[sid], min(now_ms, report["archived_at_ms"]))
    for sid, source in sources.items():
        if sid == "binance_oi_15m":
            groups[sid] = oi_metrics(source, groups.get("binance_perp_15m"), min(now_ms, report["archived_at_ms"]))
        elif sid == "binance_funding_24h":
            groups[sid] = funding_metrics(source, min(now_ms, report["archived_at_ms"]))
        elif sid not in BAR_IDS:
            groups[sid] = simple_metrics(source)
    return groups, bar_sets


def compare_groups(current, previous):
    comparisons = []
    for sid, group in current.items():
        prior = previous.get(sid) if previous else None
        old = {m["name"]: m for m in prior["metrics"]} if prior else {}
        items = {m["name"]: m for m in group["metrics"]}
        for name in dict.fromkeys([*items, *old]):
            before = old.get(name)
            item = items.get(name) or {**before, "value": None}
            status = "COMPARABLE"
            if prior is None:
                status = "NO_PREVIOUS_REAL_RUN" if previous is None else "PREVIOUS_SOURCE_MISSING"
            elif (group.get("status") in ("MISSING", "FAILED") or prior.get("status") in ("MISSING", "FAILED") or
                  group.get("comparison_eligible") is False or prior.get("comparison_eligible") is False):
                status = "INCOMPARABLE_SOURCE_STATUS"
            elif group["semantic_hash"] != prior["semantic_hash"] or before is None or before["unit"] != item["unit"] or before["definition"] != item["definition"]:
                status = "INCOMPARABLE_SEMANTICS_OR_UNIT"
            elif item["value"] is None or before["value"] is None:
                status = "MISSING_VALUE"
            comparisons.append({"source_id": sid, "metric": item["name"], "unit": item["unit"], "status": status,
                                "reason": (f"current_status={group.get('status')}; previous_status={prior.get('status')}; comparison_eligibility_required" if status == "INCOMPARABLE_SOURCE_STATUS" else status.lower()),
                                "current": item["value"], "previous": before["value"] if before else None,
                                **(change(item["value"], before["value"]) if status == "COMPARABLE" else {"absolute": None, "relative_fraction": None})})
    return comparisons


def merge_history(runs, now_ms):
    merged, conflicts = defaultdict(dict), defaultdict(set)
    for run in runs:
        groups, sets = analyze_run(run, now_ms)
        for sid, bars in sets.items():
            key = groups[sid]["semantic_hash"]
            conflicts[key].update(groups[sid]["coverage"]["conflicting_timestamps"])
            for t, bar in bars.items():
                if t in merged[key] and merged[key][t] != bar:
                    conflicts[key].add(t)
                merged[key][t] = bar
    for key, times in conflicts.items():
        for t in times:
            merged[key].pop(t, None)
    return merged, conflicts


def merge_oi_history(runs, now_ms):
    merged, conflicts = defaultdict(dict), defaultdict(set)
    for run in runs:
        for source in run["report"].get("sources", []):
            if source.get("id") != "binance_oi_15m":
                continue
            asof = min(now_ms, run["report"]["archived_at_ms"])
            points, local_conflicts, _ = parse_oi(source, asof)
            key = oi_metrics(source, None, asof)["semantic_hash"]
            conflicts[key].update(local_conflicts)
            for t, point in points.items():
                if t in merged[key] and merged[key][t] != point:
                    conflicts[key].add(t)
                merged[key][t] = point
    for key, times in conflicts.items():
        for t in times:
            merged[key].pop(t, None)
    return merged, conflicts


def anchor_at(created_ms):
    return ((created_ms + STEP - 1) // STEP) * STEP


def outcome(plan, minutes, bars, conflicts, now_ms, refreshes=()):
    anchor = plan["anchor_start_ms"]
    end = anchor + minutes * 60000
    expected = list(range(anchor, end, STEP))
    available_end = max((b["end"] for b in bars.values()), default=None)
    missing = [t for t in expected if t not in bars or t in conflicts]
    refreshed = any(r.get("collected_at_ms", -1) >= end + STEP and
                    r.get("finished_at_ms", -1) >= r.get("collected_at_ms", -1) for r in refreshes)
    elapsed = now_ms >= end
    complete = not missing
    result = {"source_id": plan["source_id"], "semantic_hash": plan["semantic_hash"], "horizon_minutes": minutes,
              "anchor_start_ms": anchor, "target_end_ms": end, "latest_local_closed_end_ms": available_end,
              "expected_bars": len(expected), "available_bars": len(expected) - len(missing), "missing_timestamps": missing,
              "conflicting_timestamps": sorted(set(expected) & conflicts), "status": "PENDING",
              "horizon_elapsed": elapsed, "refresh_after_target": refreshed, "refresh_boundary_grace_ms": STEP,
              "data_coverage_complete": complete,
              "baseline_open": None, "end_close": None, "return_pct": None, "high_excursion_pct": None, "low_excursion_pct": None}
    if not elapsed:
        result["reason"] = "horizon_not_elapsed"
    elif missing and not refreshed:
        result["reason"] = "awaiting_next_refresh_or_boundary_grace"
    elif missing:
        result.update(status="MISSING", reason="refreshed_but_missing_or_incompatible_closed_coverage")
    else:
        rows = [bars[t] for t in expected]
        baseline, close = rows[0]["open"], rows[-1]["close"]
        result.update(status="MATURE", reason="exact_closed_grid", baseline_open=str(baseline), end_close=str(close),
                      return_pct=str((close / baseline - 1) * 100),
                      high_excursion_pct=str((max(b["high"] for b in rows) / baseline - 1) * 100),
                      low_excursion_pct=str((min(b["low"] for b in rows) / baseline - 1) * 100))
    return result


def aligned_context(previous, anchor, end, merged_bars, bar_conflicts, merged_oi, oi_conflicts):
    expected = list(range(anchor, end, STEP))
    result = {"window_start_ms": anchor, "window_end_ms": end, "causal_claim": False}
    frozen = {p["source_id"]: p for p in previous.get("prospective_plan", [])}
    for sid, label in ((BAR_IDS[0], "spot"), (BAR_IDS[1], "perpetual")):
        plan = frozen.get(sid)
        key = plan["semantic_hash"] if plan else None
        bars = merged_bars.get(key, {})
        missing = [t for t in expected if t not in bars or t in bar_conflicts.get(key, set())]
        result[label] = {"source_id": sid, "semantic_hash": key, "status": "AVAILABLE" if plan and not missing else "MISSING",
                         "missing_timestamps": missing, "metrics": None,
                         "reason": "exact_same_window_closed_grid" if plan and not missing else "frozen_definition_or_exact_grid_missing"}
        if plan and not missing:
            result[label]["metrics"] = {k: val(v) for k, v in flow_stats([bars[t] for t in expected]).items()}
    oi_group = previous.get("current_sources", {}).get("binance_oi_15m")
    key = oi_group["semantic_hash"] if oi_group else None
    points = merged_oi.get(key, {})
    missing = [t for t in (anchor, end) if t not in points or t in oi_conflicts.get(key, set())]
    result["oi"] = {"source_id": "binance_oi_15m", "semantic_hash": key,
                    "status": "AVAILABLE" if oi_group and not missing else "MISSING", "metrics": None,
                    "missing_endpoint_timestamps": missing,
                    "reason": "exact_same_window_endpoints" if oi_group and not missing else "frozen_definition_or_exact_endpoints_missing"}
    if oi_group and not missing:
        first, last = points[anchor], points[end]
        if (first["quantity_unit"], first["value_unit"]) != (last["quantity_unit"], last["value_unit"]):
            result["oi"].update(status="MISSING", reason="endpoint_units_differ")
        else:
            metrics = {}
            for name, unit in (("quantity", "quantity_unit"), ("value", "value_unit")):
                metrics[f"{name}_unit"] = first[unit]
                metrics[f"{name}_first"] = str(first[name]); metrics[f"{name}_last"] = str(last[name])
                metrics[f"{name}_change"] = str(last[name] - first[name])
                metrics[f"{name}_change_pct"] = val(fraction((last[name] - first[name]) * 100, first[name]))
            result["oi"]["metrics"] = metrics
    return result


def discover_runs(root, now_ms):
    result = []
    for day in sorted(root.iterdir()):
        if not day.is_dir() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day.name):
            continue
        for folder in day.iterdir():
            match = re.fullmatch(r"run_(\d+)", folder.name)
            path = folder / "report.json"
            if not match or not path.is_file() or not path.resolve().is_relative_to(root):
                continue
            body = path.read_bytes(); report = json.loads(body)
            if report.get("schema") != "daily-as-seen-v1" or report.get("synthetic") is not False:
                continue
            actual = integer(report.get("archived_at_ms"))
            if actual != int(match[1]) or actual > now_ms or report.get("order_permission") is not False:
                raise ValueError("archive identity/time/order-permission integrity failure")
            result.append({"id": f"{day.name}/{folder.name}", "sha256": digest(body), "report": report})
    return sorted(result, key=lambda r: (r["report"]["archived_at_ms"], r["id"]))


def discover_analyses(root, synthetic_test=False):
    result = []
    if not root.exists():
        return result
    for folder in root.iterdir():
        match = re.fullmatch(r"analysis_(\d+)", folder.name)
        path = folder / "report.json"
        if not match or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            continue
        report = json.loads(path.read_bytes())
        if report.get("schema") != SCHEMA or (report.get("synthetic") and not synthetic_test):
            continue
        if report.get("created_at_ms") != int(match[1]):
            raise ValueError("analysis creation identity mismatch")
        result.append((folder, report))
    return sorted(result, key=lambda pair: pair[1]["created_at_ms"])


def compute(runs, prior_analyses, now_ms, synthetic=False):
    if not runs:
        raise ValueError("no real archived daily runs")
    current = runs[-1]
    current_groups, _ = analyze_run(current, now_ms)
    previous_groups = analyze_run(runs[-2], now_ms)[0] if len(runs) > 1 else None
    merged, conflicts = merge_history(runs, now_ms)
    merged_oi, oi_conflicts = merge_oi_history(runs, now_ms)
    plans = [{"source_id": sid, "semantic_hash": group["semantic_hash"], "created_at_ms": now_ms,
              "anchor_start_ms": anchor_at(now_ms), "baseline_definition": "first full bar open at/after actual analysis creation",
              "horizons_minutes": list(HORIZONS)} for sid, group in current_groups.items() if sid in BAR_IDS]
    evaluations, assessments = [], []
    for previous in prior_analyses:
        prior_outcomes = []
        for plan in previous.get("prospective_plan", []):
            if plan["anchor_start_ms"] != anchor_at(previous["created_at_ms"]) or plan.get("created_at_ms") != previous["created_at_ms"]:
                raise ValueError("prior prospective anchor is not frozen to actual creation")
            for minutes in HORIZONS:
                record = outcome(plan, minutes, merged.get(plan["semantic_hash"], {}), conflicts.get(plan["semantic_hash"], set()), now_ms,
                                 [r["report"] for r in runs if r["report"]["archived_at_ms"] > previous["created_at_ms"]])
                record["prior_analysis_created_at_ms"] = previous["created_at_ms"]
                record["aligned_context"] = (aligned_context(previous, record["anchor_start_ms"], record["target_end_ms"], merged, conflicts, merged_oi, oi_conflicts)
                                             if record["status"] == "MATURE" else None)
                evaluations.append(record)
                prior_outcomes.append(record)
        assessments.append({"prior_analysis_created_at_ms": previous["created_at_ms"], "outcomes": prior_outcomes,
                            "related_current_indicator_changes": compare_groups(current_groups, previous.get("current_sources", {})),
                            "causal_claim": False})
    aligned = (all(sid in current_groups and current_groups[sid]["coverage"]["complete_96_closed"] for sid in BAR_IDS) and
               current_groups[BAR_IDS[0]]["window_start_ms"] == current_groups[BAR_IDS[1]]["window_start_ms"] and
               current_groups[BAR_IDS[0]]["window_end_ms"] == current_groups[BAR_IDS[1]]["window_end_ms"])
    hourly = []
    if aligned:
        for spot_block, perp_block in zip(current_groups[BAR_IDS[0]]["hourly_blocks_last4h"], current_groups[BAR_IDS[1]]["hourly_blocks_last4h"]):
            oi_block = next((b for b in current_groups.get("binance_oi_15m", {}).get("hourly_blocks_last4h", [])
                             if b["start_ms"] == spot_block["start_ms"] and b["end_ms"] == spot_block["end_ms"]), None)
            hourly.append({"start_ms": spot_block["start_ms"], "end_ms": spot_block["end_ms"], "spot": spot_block,
                           "perpetual": perp_block, "oi": oi_block, "causal_claim": False})
    return {"schema": SCHEMA, "synthetic": synthetic, "created_at_ms": now_ms, "created_at_utc": utc(now_ms),
            "input_run_id": current["id"], "input_report_sha256": current["sha256"],
            "previous_run_id": runs[-2]["id"] if len(runs) > 1 else None,
            "current_sources": current_groups, "changes_from_previous_real_run": compare_groups(current_groups, previous_groups),
            "prospective_plan": plans, "evaluations_of_prior_analyses": evaluations,
            "prior_assessments": assessments, "spot_perp_window_alignment": "matched" if aligned else "MISMATCH_OR_UNAVAILABLE",
            "hourly_blocks_last4h": hourly,
            "history_run_ids": [r["id"] for r in runs], "history_inputs": [{"id": r["id"], "sha256": r["sha256"]} for r in runs],
            "order_permission": False,
            "predictions_created": False, "trade_primary_labels_created": False,
            "quality_flags": ["descriptive_public_context_only", "provider_lag_not_inferred_from_asof_age"]}


def summary(report):
    lines = ["# Ежедневная аналитика сохранённого контекста", "", f"Создано фактически: {report['created_at_utc']}",
             f"Пакет: {report['input_run_id']}; предыдущий: {report['previous_run_id'] or 'ещё нет'}.",
             "Только наблюдаемые изменения. Прогнозы/PnL/разрешения на ордера не создаются.", "",
             "| Рынок | Закрытые 15m бары | 24h, % | 1h, % | 4h, % | Объём BTC | Дельта BTC | F взвешенный |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    def shown(value):
        return "нет данных" if value is None else f"{Decimal(value):.6f}"
    for sid in BAR_IDS:
        group = report["current_sources"].get(sid)
        if not group:
            continue
        values = {m["name"]: m["value"] for m in group["metrics"]}
        lines.append(f"| {sid} | {group['coverage']['valid_unique_rows']}/96; {group['status']} | " + " | ".join(shown(values.get(k)) for k in ("return_24h_pct", "return_1h_pct", "return_4h_pct", "base_volume_24h", "delta_base_24h", "F_volume_weighted")) + " |")
    lines += ["", "## OI и funding", ""]
    for sid in ("binance_oi_15m", "binance_funding_24h"):
        group = report["current_sources"].get(sid)
        if group:
            lines.append(f"{sid}: {group['status']}; " + (f"совпадение времени с perp: {group['perp_window_alignment']}." if sid == "binance_oi_15m" else f"наблюдаемых событий: {len(group['events'])}; интервал расчёта не предполагается."))
            for m in group["metrics"]:
                lines.append(f"- {m['name']}: {shown(m['value'])} {m['unit']}")
            lines.append("")
    lines += ["## Четыре закрытых часа последнего 4h окна", "",
              "| Начало UTC | Spot return, % | Perp return, % | Spot quote volume, USDT | Perp quote volume, USDT | OI quantity change, % |",
              "|---|---:|---:|---:|---:|---:|"]
    for block in report["hourly_blocks_last4h"]:
        oi_pct = block["oi"].get("oi_quantity_change_pct") if block["oi"] else None
        lines.append(f"| {utc(block['start_ms'])} | {shown(block['spot']['return_pct'])} | {shown(block['perpetual']['return_pct'])} | {shown(block['spot']['quote_volume_USDT'])} | {shown(block['perpetual']['quote_volume_USDT'])} | {shown(oi_pct)} |")
    changes = report["changes_from_previous_real_run"]
    lines += ["## Изменения относительно предыдущего реального пакета", ""]
    if report["previous_run_id"] is None:
        lines.append("Предыдущего реального пакета нет; изменения не подменяются нулём.")
    else:
        for item in changes:
            if item["status"] == "COMPARABLE":
                lines.append(f"- {item['source_id']} / {item['metric']}: изменение {shown(item['absolute'])} {item['unit']}; относительное {shown(item['relative_fraction'])} (доля).")
            elif item["status"] != "NO_PREVIOUS_REAL_RUN":
                lines.append(f"- {item['source_id']} / {item['metric']}: {item['status']}.")
    lines += ["", "## Что рынок делал после предыдущих анализов", ""]
    if not report["evaluations_of_prior_analyses"]:
        lines.append("Предыдущих анализов нет. Новый baseline заморожен на первом полном 15m баре после фактического создания; исходы пока не наблюдены.")
    for item in report["evaluations_of_prior_analyses"]:
        lines.append(f"- {item['source_id']} после {utc(item['prior_analysis_created_at_ms'])}, +{item['horizon_minutes']}m: {item['status']}; return {shown(item['return_pct'])}%; покрытие {item['available_bars']}/{item['expected_bars']}.")
    lines += ["", "PENDING: горизонт ещё не истёк или ожидается следующий пакет после цели с 15m допуском на границу. MISSING: такой новый пакет уже получен, но точное закрытое покрытие отсутствует. MATURE: вся точная сетка закрытых баров доступна. Связанные изменения индикаторов сохранены в prior_assessments без причинного утверждения. Ничего не скачивается и не достраивается. Старые файлы не переписываются."]
    return "\n".join(lines) + "\n"


def analyze(local_root, *, _clock=None, _synthetic_test=False):
    if _clock is not None and not _synthetic_test:
        raise ValueError("clock injection requires explicit synthetic-test mode")
    root = Path(local_root).resolve()
    now_ms = integer(_clock() if _clock else time.time_ns() // 1000000)
    if not root.is_dir():
        raise ValueError("explicit local root does not exist")
    output = root / "analytics"
    if not output.resolve().is_relative_to(root):
        raise ValueError("analytics directory escapes local root")
    output.mkdir(exist_ok=True)
    lock = output / ".analysis.reserve"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    stage = None
    try:
        runs = discover_runs(root, now_ms)
        if not runs:
            raise ValueError("no eligible real archives")
        previous = discover_analyses(output, _synthetic_test)
        # Every previously frozen input, including historical rows used for
        # outcomes, must remain unchanged before either new computation or reuse.
        current_hashes = {r["id"]: r["sha256"] for r in runs}
        for _, existing in previous:
            recorded = [{"id": existing["input_run_id"], "sha256": existing["input_report_sha256"]},
                        *existing.get("history_inputs", [])]
            if existing["created_at_ms"] > now_ms:
                raise ValueError("previous analysis creation is in the future")
            for item in recorded:
                if current_hashes.get(item["id"]) != item["sha256"]:
                    raise ValueError(f"already analyzed immutable input SHA changed or input missing: {item['id']}")
        for path, existing in previous:
            if existing.get("input_run_id") == runs[-1]["id"]:
                if existing.get("input_report_sha256") != runs[-1]["sha256"]:
                    raise ValueError("already analyzed immutable input SHA changed")
                return path, existing, True
        report = compute(runs, [r for _, r in previous], now_ms, _synthetic_test)
        report["utility_sha256"] = digest(Path(__file__).read_bytes())
        report["assumptions_sha256"] = digest(Path(__file__).with_name("ANALYTICS_ASSUMPTIONS.md").read_bytes())
        target = output / f"analysis_{now_ms}"
        if target.exists():
            raise FileExistsError("analysis millisecond already exists; no overwrite")
        stage = output / f".analysis_{now_ms}.stage_{uuid4().hex}"
        stage.mkdir()
        for name, body in (("report.json", json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")),
                           ("summary.md", summary(report).encode("utf-8"))):
            with (stage / name).open("xb") as handle:
                handle.write(body); handle.flush(); os.fsync(handle.fileno())
        if target.exists():
            raise FileExistsError("analysis destination already exists")
        os.rename(stage, target); stage = None
        return target, report, False
    finally:
        os.close(fd); lock.unlink()
        if stage is not None and stage.exists():
            resolved = stage.resolve()
            if resolved.parent != output.resolve() or ".stage_" not in resolved.name:
                raise RuntimeError("unsafe staging cleanup refused")
            shutil.rmtree(resolved)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-root", required=True, type=Path)
    args = parser.parse_args()
    try:
        path, report, reused = analyze(args.local_root)
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.exit(2, f"analytics refused: {exc}\n")
    print(json.dumps({"analysis": str(path), "input_run": report["input_run_id"], "reused": reused, "order_permission": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
