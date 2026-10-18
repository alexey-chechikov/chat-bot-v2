"""Offline append-only public-price outcomes. No network/account/CoinGlass evidence reads."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

STEP = 900_000
HORIZONS = (15, 60, 240, 1440)
SCHEMA = "coinglass-outcome-supplement-v1"
HISTORY_SCHEMA = "coinglass-outcome-history-v1"
BAR_IDS = ("binance_spot_15m", "binance_perp_15m")
OI_ID = "binance_oi_15m"
MAX_BYTES = 32 * 1024 * 1024
STABLE = {"symbol", "exchange", "exchanges", "model", "mode", "window", "windows_hours", "interval",
          "bar_interval", "timeframe", "threshold", "merge", "range_percent", "currency", "units",
          "delta_formula", "CVD_level_used_as_flow", "closure_clock", "clock_role", "timestamp_semantics",
          "requested_closed_bars", "expected_points", "settlement_interval_assumed", "liquidation_map",
          "cross_market_clock_alignment_unmeasured"}


def encoded(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(body):
    return hashlib.sha256(body).hexdigest()


def integer(value):
    if type(value) is not int or value < 0:
        raise ValueError("nonnegative integer timestamp required")
    return value


def decimal(value):
    if value is None or isinstance(value, bool):
        raise ValueError("finite number required")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("finite number required") from exc
    if not result.is_finite():
        raise ValueError("nonfinite number")
    return result


def utc(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def anchor_at(ms):
    return (integer(ms) + STEP - 1) // STEP * STEP


def expected_definitions():
    shared = {"symbol": "BTCUSDT", "interval": "15m", "requested_closed_bars": 96,
              "closure_clock": "futures_public_serverTime",
              "units": "OHLC/quote USDT; base/delta BTC; F/shares fraction",
              "delta_formula": "2*taker_buy_base-base_volume", "CVD_level_used_as_flow": False}
    definitions = {}
    for sid, host, product in ((BAR_IDS[0], "https://api.binance.com/api/v3/klines", "spot"),
                               (BAR_IDS[1], "https://fapi.binance.com/fapi/v1/klines", "futures")):
        settings = dict(shared)
        if product == "spot":
            settings["cross_market_clock_alignment_unmeasured"] = True
        definitions[sid] = {"source_id": sid, "source_path": host, "market_scope": product,
                            "aggregation": "single_exchange_public_REST", "settings": settings}
    definitions[OI_ID] = {"source_id": OI_ID, "source_path": "https://fapi.binance.com/futures/data/openInterestHist",
                          "market_scope": "futures", "aggregation": "single_exchange_public_REST",
                          "settings": {"symbol": "BTCUSDT", "interval": "15m", "expected_points": 97,
                                       "timestamp_semantics": "provider_period_end",
                                       "units": "provider-native OI quantity and reported notional kept separate"},
                          "row_units": [["provider_native_open_interest_units", "provider_reported_notional_value"]]}
    return definitions


DEFINITIONS = expected_definitions()
HASHES = {sid: sha(encoded(value)) for sid, value in DEFINITIONS.items()}


def observed_rows(source):
    for item in source.get("values") or []:
        if item.get("name") == "observations" and item.get("type") == "json" and isinstance(item.get("value"), list):
            return item["value"]
    return []


def series_definition(source, extended=False):
    sid = source.get("id")
    if sid not in DEFINITIONS:
        raise ValueError("unsupported series")
    uri = urlsplit(source.get("url") or "")
    path = f"{uri.scheme}://{uri.netloc}{uri.path}"
    if uri.username or uri.password or path != DEFINITIONS[sid]["source_path"]:
        raise ValueError("wrong public source path")
    if (source.get("market_scope"), source.get("aggregation")) != (
            DEFINITIONS[sid]["market_scope"], DEFINITIONS[sid]["aggregation"]):
        raise ValueError("wrong product or aggregation")
    query = parse_qs(uri.query, keep_blank_values=True)
    required_query = {"symbol": "BTCUSDT", "period" if sid == OI_ID else "interval": "15m"}
    for key,value in required_query.items():
        if key in query and query[key] != [value]:
            raise ValueError("request query contradicts the primary series")
    if extended:
        actual = source.get("settings", {})
        expected = dict(DEFINITIONS[sid]["settings"])
        expected["expected_points" if sid == OI_ID else "requested_closed_bars"] = 385 if sid == OI_ID else 384
        if any(actual.get(k) != v for k,v in expected.items()):
            raise ValueError("extended source settings contradict declared legacy definition")
        definition = source.get("legacy_definition")
    else:
        settings = source.get("settings", {})
        definition = {"source_id": sid, "source_path": path, "market_scope": source.get("market_scope"),
                      "aggregation": source.get("aggregation"),
                      "settings": {k: settings[k] for k in sorted(STABLE) if k in settings}}
        if sid == OI_ID:
            definition["row_units"] = sorted({(r.get("quantity_unit"), r.get("value_unit")) for r in observed_rows(source)})
            definition["row_units"] = [list(pair) for pair in definition["row_units"]]
    if encoded(definition) != encoded(DEFINITIONS[sid]):
        raise ValueError("legacy definition is incompatible; no implicit migration")
    return HASHES[sid]


def no_links(path):
    path = Path(path).absolute()
    for node in (path, *path.parents):
        try:
            info = node.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise ValueError("symlink/junction/reparse input or output refused")
    return path


def read_json(path, root):
    path, root = no_links(path), no_links(root)
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("input file outside selected root, missing, or too large")
    raw = path.read_bytes()
    obj = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    if not isinstance(obj, dict):
        raise ValueError("JSON object required")
    return obj, {"path": str(path.resolve()), "sha256": sha(raw), "bytes": len(raw)}


def collect_inputs(local_root, history_roots, now_ms):
    root = no_links(local_root).resolve()
    if not root.is_dir():
        raise ValueError("explicit daily local root required")
    runs, analyses, notes, histories, inputs, run_index = [], [], [], [], [], {}
    for day in sorted(root.iterdir()):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day.name) and day.is_dir():
            no_links(day)
            for folder in sorted(day.iterdir()):
                if not re.fullmatch(r"run_\d+", folder.name) or not folder.is_dir():
                    continue
                body, rec = read_json(folder / "report.json", root)
                if body.get("schema") != "daily-as-seen-v1" or body.get("synthetic") is not False:
                    continue
                created = integer(body["archived_at_ms"])
                if created != int(folder.name[4:]) or created > now_ms or body.get("order_permission") is not False:
                    raise ValueError("daily archive time/identity/permission invalid")
                rec["kind"] = "daily_report"; inputs.append(rec)
                run_index[day.name+"/"+folder.name] = {"sha256":rec["sha256"],"archived_at_ms":created}
                runs.append(body)
    for dirname, prefix, schema, target in (("analytics", "analysis", "daily-context-analytics-v1", analyses),
                                            ("analyst_notes", "note", "analyst-note-v1", notes)):
        parent = root / dirname
        if not parent.exists():
            continue
        no_links(parent)
        for folder in sorted(parent.iterdir()):
            if not re.fullmatch(prefix + r"_\d+", folder.name) or not folder.is_dir():
                continue
            body, rec = read_json(folder / ("report.json" if prefix == "analysis" else "note.json"), root)
            if body.get("schema") != schema:
                raise ValueError("unknown analysis/note schema")
            created = integer(body["created_at_ms"])
            if created != int(folder.name.split("_", 1)[1]) or created > now_ms:
                raise ValueError("analysis/note actual time/identity invalid")
            if body.get("order_permission") is not False or body.get("synthetic") is True:
                raise ValueError("non-research or synthetic analysis/note refused")
            rec["kind"] = prefix; inputs.append(rec)
            target.append({"id": folder.name, "body": body, "input": rec})
    for selected in history_roots:
        selected = no_links(selected).resolve()
        if not selected.is_dir():
            raise ValueError("history root must be a directory")
        candidates = [selected / "history.json"] if (selected / "history.json").exists() else [
            p / "history.json" for p in sorted(selected.iterdir()) if p.is_dir() and
            re.fullmatch(r"(?:history|preflight|run)_\d+", p.name) and (p / "history.json").is_file()]
        for path in candidates:
            body, rec = read_json(path, selected)
            if body.get("schema") != HISTORY_SCHEMA or body.get("synthetic") is not False:
                raise ValueError("only real public history inputs admitted")
            integer(body["collected_at_ms"]); integer(body["finished_at_ms"])
            if body["cutoff_ms"] is not None:
                integer(body["cutoff_ms"])
            if body["collected_at_ms"] > body["finished_at_ms"] or (body["cutoff_ms"] is not None and body["cutoff_ms"] > body["finished_at_ms"]):
                raise ValueError("history time contract invalid")
            rec["kind"] = "history"; inputs.append(rec)
            histories.append(body)
    for analysis in analyses:
        body=analysis["body"]
        refs=[{"id":body.get("input_run_id"),"sha256":body.get("input_report_sha256")},*body.get("history_inputs",[])]
        for ref in refs:
            found=run_index.get(ref.get("id"))
            if (found is None or ref.get("sha256") != found["sha256"] or found["archived_at_ms"] > body["created_at_ms"]):
                raise ValueError("frozen analysis daily input SHA/identity/time mismatch")
    paths = [i["path"] for i in inputs]
    if len(paths) != len(set(paths)):
        raise ValueError("duplicate explicit input paths")
    return runs, analyses, notes, histories, sorted(inputs, key=lambda i: i["path"])


def parse_bar(row, asof):
    ts, end = integer(row["bar_start_ms"]), integer(row["bar_end_ms"])
    if row.get("closed") is not True or ts % STEP or end != ts + STEP or end > asof:
        raise ValueError("forming/future/non-grid candle")
    result = {"start": ts, "end": end}
    for key in ("open", "high", "low", "close"):
        result[key] = decimal(row[key])
    if min(result[k] for k in ("open", "high", "low", "close")) <= 0 or result["low"] > min(result["open"], result["close"]) or result["high"] < max(result["open"], result["close"]) or result["low"] > result["high"]:
        raise ValueError("invalid OHLC")
    try:
        flow = {k: decimal(row[k]) for k in ("base_volume", "quote_volume", "taker_buy_base", "taker_buy_quote")}
        if min(flow.values()) < 0 or flow["taker_buy_base"] > flow["base_volume"] or flow["taker_buy_quote"] > flow["quote_volume"]:
            raise ValueError("invalid flow")
        result["flow"] = flow
    except (KeyError, ValueError):
        result["flow"] = None
    result["flow_conflict"] = False
    return ts, result


def parse_oi(row, asof):
    ts = integer(row["timestamp_ms"])
    if ts % STEP or ts > asof or [row.get("quantity_unit"), row.get("value_unit")] != DEFINITIONS[OI_ID]["row_units"][0]:
        raise ValueError("invalid OI timestamp/units")
    result = {"quantity": decimal(row["sum_open_interest"]), "value": decimal(row["sum_open_interest_value"])}
    if min(result.values()) < 0:
        raise ValueError("negative OI")
    return ts, result


def merged_series(runs, histories, now_ms):
    data = {sid: {} for sid in DEFINITIONS}; conflicts = {sid: set() for sid in DEFINITIONS}
    refreshed = {sid: 0 for sid in DEFINITIONS}; issues = []; admissions = []
    documents = [(r, False, r["archived_at_ms"]) for r in runs] + [(h, True, h["finished_at_ms"]) for h in histories]
    for document, extended, available in documents:
        if available > now_ms or (extended and document.get("cutoff_ms") is None):
            admissions.append({"available_at_ms": available, "admitted": False,
                               "reason":"future_receipt" if available > now_ms else "clock_dependency_unavailable"}); continue
        admissions.append({"available_at_ms": available, "admitted": True})
        for source in document.get("sources", []):
            sid = source.get("id")
            if sid not in DEFINITIONS:
                continue
            try:
                series_definition(source, extended)
                request = source.get("settings", {}).get("request", {})
                received = integer(source.get("received_at_ms", request.get("received_at_ms", available)))
                if request.get("received_at_ms") is not None and received != request["received_at_ms"]:
                    raise ValueError("contradictory receipt timestamps")
                if received > now_ms:
                    continue
                cutoff = document.get("cutoff_ms",received)
                if cutoff is None:
                    raise ValueError("history clock dependency unavailable")
                asof = min(now_ms, received,cutoff)
                refreshed[sid] = max(refreshed[sid], received)
                declared = set(source.get("conflicting_timestamps",[])) | set(source.get("settings",{}).get("validation",{}).get("conflicting_timestamps",[]))
                for ts in declared:
                    integer(ts)
                    if ts % STEP or ts > asof:
                        raise ValueError("invalid declared conflict timestamp")
                    conflicts[sid].add(ts); data[sid].pop(ts,None)
                for row in observed_rows(source):
                    try:
                        ts, parsed = parse_oi(row, asof) if sid == OI_ID else parse_bar(row, asof)
                        if ts in conflicts[sid]:
                            continue
                        previous = data[sid].get(ts)
                        if previous is not None and sid != OI_ID:
                            core = ("start","end","open","high","low","close")
                            if any(previous[k] != parsed[k] for k in core):
                                conflicts[sid].add(ts); data[sid].pop(ts,None)
                            elif previous["flow_conflict"]:
                                pass
                            elif previous["flow"] is None:
                                previous["flow"] = parsed["flow"]
                            elif parsed["flow"] is not None and previous["flow"] != parsed["flow"]:
                                previous["flow"] = None; previous["flow_conflict"] = True
                        elif previous is not None and previous != parsed:
                            conflicts[sid].add(ts); data[sid].pop(ts,None)
                        else:
                            data[sid][ts] = parsed
                    except (KeyError, ValueError, TypeError) as exc:
                        issues.append({"source_id": sid, "reason": str(exc), "row_start_ms": row.get("bar_start_ms", row.get("timestamp_ms"))})
            except (KeyError, ValueError, TypeError) as exc:
                issues.append({"source_id": sid, "reason": str(exc), "available_at_ms": available})
    return data, conflicts, refreshed, issues, admissions


def record_targets(analyses, notes):
    analyses = sorted(analyses, key=lambda a: (a["body"]["created_at_ms"], a["id"]))
    notes = sorted(notes, key=lambda n: (n["body"]["created_at_ms"], n["id"]))
    indexed = {a["id"]: a for a in analyses}
    if len(indexed) != len(analyses) or len({n["id"] for n in notes}) != len(notes):
        raise ValueError("duplicate analysis/note identities")
    targets = []
    for analysis in analyses:
        body = analysis["body"]
        plans = {p["source_id"]: p for p in body.get("prospective_plan", [])}
        targets.append({"id": analysis["id"], "kind": "machine_analysis", "created_at_ms": body["created_at_ms"],
                        "anchor_ms": anchor_at(body["created_at_ms"]), "analysis_id": analysis["id"],
                        "analysis": body, "plans": plans, "binding": "explicit_analysis", "previous_note_id": None})
    for index, note in enumerate(notes):
        body = note["body"]; claimed = body.get("analysis_id")
        candidates = [indexed[claimed]] if claimed in indexed else []
        if claimed is None:
            candidates = [a for a in analyses if a["body"].get("input_run_id") == body.get("input_run")]
        binding = "explicit_analysis" if claimed is not None else "unique_input_run"
        analysis = candidates[0] if len(candidates) == 1 else None
        if analysis and body.get("analysis_report_sha256") not in (None, analysis["input"]["sha256"]):
            raise ValueError("note bound analysis SHA mismatch")
        if analysis and body.get("input_run") != analysis["body"].get("input_run_id"):
            raise ValueError("note and bound analysis run disagree")
        created = max(body["created_at_ms"], analysis["body"]["created_at_ms"]) if analysis else body["created_at_ms"]
        anchor = anchor_at(created)
        if analysis and body.get("earliest_forward_anchor_ms") not in (None, anchor):
            raise ValueError("note claimed anchor differs from max actual creation rule")
        targets.append({"id": note["id"], "kind": "human_note", "created_at_ms": body["created_at_ms"],
                        "anchor_ms": anchor, "analysis_id": analysis["id"] if analysis else None,
                        "analysis": analysis["body"] if analysis else None,
                        "plans": {p["source_id"]: p for p in analysis["body"].get("prospective_plan", [])} if analysis else {},
                        "binding": binding if analysis else "MISSING_OR_AMBIGUOUS_ANALYSIS",
                        "previous_note_id": notes[index-1]["id"] if index else None,
                        "text_conditions": {"status": "NOT_AUTOMATICALLY_ASSESSED", "reason": "price path is separate from narrative; no registered typed predicate evaluator"}})
    return sorted(targets, key=lambda t: (t["created_at_ms"], t["kind"], t["id"]))


def flow_context(rows):
    if any(r["flow_conflict"] for r in rows):
        return {"status":"CONFLICT", "metrics":None, "reason":"contradictory_flow_versions_price_unchanged"}
    if any(r["flow"] is None for r in rows):
        return {"status": "MISSING", "metrics": None, "reason": "flow_fields_unavailable"}
    base = sum((r["flow"]["base_volume"] for r in rows), Decimal(0))
    quote = sum((r["flow"]["quote_volume"] for r in rows), Decimal(0))
    buy = sum((r["flow"]["taker_buy_base"] for r in rows), Decimal(0))
    delta = 2 * buy - base
    return {"status": "AVAILABLE", "metrics": {"base_volume_BTC": str(base), "quote_volume_USDT": str(quote),
            "delta_base_BTC": str(delta), "F_volume_weighted_fraction": str(delta/base) if base else None}, "reason": "exact_same_closed_interval"}


def frozen_series_compatible(analysis, sid):
    group = (analysis or {}).get("current_sources",{}).get(sid,{})
    definition = group.get("semantics")
    return (group.get("semantic_hash") == HASHES[sid] and encoded(definition) == encoded(DEFINITIONS[sid]) and
            sha(encoded(definition)) == HASHES[sid])


def assess(target, sid, minutes, data, conflicts, refreshed, now_ms):
    anchor = target["anchor_ms"]; end = anchor + minutes*60_000
    expected = list(range(anchor, end, STEP)); bars = data[sid]
    plan = target["plans"].get(sid)
    valid_plan = (target["analysis"] is not None and plan is not None and plan.get("semantic_hash") == HASHES[sid] and
                  frozen_series_compatible(target["analysis"],sid) and
                  plan.get("anchor_start_ms") == anchor_at(target["analysis"]["created_at_ms"]) and
                  plan.get("created_at_ms") == target["analysis"]["created_at_ms"])
    bad = sorted(set(expected) & conflicts[sid])
    missing = [t for t in expected if t not in bars]
    elapsed = now_ms >= end
    if not valid_plan:
        status, reason = "MISSING", "missing_or_incompatible_frozen_analysis_binding"
    elif not elapsed:
        status, reason = "PENDING", "horizon_not_elapsed"
    elif bad:
        status, reason = "CONFLICT", "contradictory_closed_candle_versions"
    elif not missing:
        status, reason = "MATURE", "exact_closed_grid"
    elif refreshed[sid] < end + STEP:
        status, reason = "PENDING", "awaiting_post_target_refresh_with_15m_boundary_grace"
    else:
        status, reason = "MISSING", "refreshed_but_exact_closed_grid_missing"
    result = {"record_id": target["id"], "record_kind": target["kind"], "analysis_id": target["analysis_id"],
              "source_id": sid, "market": "spot" if sid == BAR_IDS[0] else "perpetual", "anchor_ms": anchor,
              "anchor_utc": utc(anchor), "horizon_minutes": minutes, "target_end_ms": end,
              "status": status, "reason": reason, "expected_bars": len(expected),
              "available_bars": sum(t in bars for t in expected), "missing_timestamps": missing,
              "conflicting_timestamps": bad, "baseline_open": None, "end_close": None, "return_pct": None,
              "high_excursion_pct": None, "low_excursion_pct": None, "flow": {"status": "MISSING", "metrics": None},
              "oi": {"status": "MISSING", "metrics": None}, "PnL": False, "forecast_probability": False}
    if status == "MATURE":
        rows = [bars[t] for t in expected]; baseline = rows[0]["open"]; last = rows[-1]["close"]
        result.update(baseline_open=str(baseline), end_close=str(last), return_pct=str((last/baseline-1)*100),
                      high_excursion_pct=str((max(r["high"] for r in rows)/baseline-1)*100),
                      low_excursion_pct=str((min(r["low"] for r in rows)/baseline-1)*100), flow=flow_context(rows))
        oi = data[OI_ID]
        oi_bad = sorted({anchor, end} & conflicts[OI_ID]); oi_missing = [t for t in (anchor,end) if t not in oi]
        result["oi"].update(missing_endpoint_timestamps=oi_missing, conflicting_endpoint_timestamps=oi_bad)
        if oi_bad:
            result["oi"].update(status="CONFLICT", reason="contradictory_OI_endpoint")
        elif not frozen_series_compatible(target["analysis"],OI_ID):
            result["oi"]["reason"] = "frozen_OI_definition_unavailable_or_incompatible"
        elif not oi_missing:
            first, final = oi[anchor], oi[end]
            metrics = {}
            for key in ("quantity", "value"):
                metrics[key+"_first"] = str(first[key]); metrics[key+"_last"] = str(final[key])
                metrics[key+"_change"] = str(final[key]-first[key])
                metrics[key+"_change_pct"] = str((final[key]/first[key]-1)*100) if first[key] else None
            result["oi"].update(status="AVAILABLE", metrics=metrics, reason="exact_same_interval_endpoints")
        else:
            result["oi"]["reason"] = "exact_OI_endpoints_missing"
    return result


def compute(runs, analyses, notes, histories, now_ms):
    integer(now_ms)
    targets = record_targets(analyses, notes)
    data, conflicts, refreshed, issues, admissions = merged_series(runs, histories, now_ms)
    records = [assess(t,sid,h,data,conflicts,refreshed,now_ms) for t in targets for sid in BAR_IDS for h in HORIZONS]
    human = [t for t in targets if t["kind"] == "human_note"]
    return {"schema": SCHEMA, "created_at_ms": now_ms, "created_at_utc": utc(now_ms),
            "records": records, "targets": [{k:v for k,v in t.items() if k not in ("analysis","plans")} for t in targets],
            "latest_note_id": human[-1]["id"] if human else None,
            "immediately_previous_note_id": human[-2]["id"] if len(human)>1 else None,
            "source_issues": issues, "history_admissions": admissions,
            "status_counts": {s:sum(r["status"]==s for r in records) for s in ("PENDING","MISSING","CONFLICT","MATURE")},
            "legacy_adapter": {"id":"fixed-public-BTCUSDT-15m-v1", "allowed_hashes": HASHES},
            "human_conditions_automatically_assessed": False, "order_permission": False,
            "market_hypothesis_scored": False, "missed_CoinGlass_snapshots_created": False}


def summary(report):
    lines = ["# Отдельная досверка исходов", "", "Создано: "+report["created_at_utc"],
             "Последняя человеческая заметка: "+str(report["latest_note_id"]),
             "Непосредственно предыдущая: "+str(report["immediately_previous_note_id"]), "",
             "Числовые пути и человеческий текст разделены. Условия текста автоматически не оценены. PnL не рассчитывается.", "",
             "| Запись | Тип | Рынок | Anchor UTC | Минут | Статус | Изменение цены, % | Покрытие |",
             "|---|---|---|---|---:|---|---:|---|"]
    for r in report["records"]:
        lines.append(f"| {r['record_id']} | {r['record_kind']} | {r['market']} | {r['anchor_utc']} | {r['horizon_minutes']} | {r['status']} | {r['return_pct'] if r['return_pct'] is not None else 'нет данных'} | {r['available_bars']}/{r['expected_bars']} |")
    return "\n".join(lines)+"\n"


def verify_existing(folder):
    report, _ = read_json(folder/"report.json", folder)
    integrity, _ = read_json(folder/"integrity.json", folder)
    for name in ("report.json", "summary.md"):
        path = no_links(folder/name)
        if path.stat().st_size > MAX_BYTES or sha(path.read_bytes()) != integrity.get(name):
            raise ValueError("existing immutable supplement was modified")
    return report


def publish_stage(stage, target):
    # Bounded retry for transient Windows file handles only; no permission changes,
    # replacement, destination deletion, network retries or fallback write mode.
    for attempt in range(5):
        if target.exists():
            raise FileExistsError("immutable supplement destination already exists")
        try:
            os.rename(stage,target)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(.05*(attempt+1))


def evaluate(local_root, history_roots, outroot, *, _now_ms=None):
    now_ms = integer(time.time_ns()//1_000_000 if _now_ms is None else _now_ms)
    local_root = no_links(local_root).resolve(); outroot = no_links(outroot).resolve()
    relative = outroot.relative_to(local_root).parts if outroot.is_relative_to(local_root) else ()
    if (outroot == local_root or any(outroot.is_relative_to(local_root/name) for name in ("analytics","analyst_notes")) or
            relative and re.fullmatch(r"\d{4}-\d{2}-\d{2}",relative[0])):
        raise ValueError("supplements cannot be written into original archives/notes")
    runs, analyses, notes, histories, inputs = collect_inputs(local_root,history_roots,now_ms)
    if not analyses and not notes:
        raise ValueError("no frozen analyses or human notes")
    outroot.mkdir(parents=True,exist_ok=True)
    lock = outroot/".supplement.reserve"
    fd = os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    stage = None
    try:
        current = {i["path"]:i["sha256"] for i in inputs}
        for folder in outroot.iterdir():
            if folder.is_dir() and re.fullmatch(r"supplement_[a-f0-9]{24}",folder.name):
                prior = verify_existing(folder)
                for old in prior.get("inputs",[]):
                    if current.get(old["path"]) != old["sha256"]:
                        raise ValueError("previously frozen input modified or omitted")
        report = compute(runs,analyses,notes,histories,now_ms)
        code_sha = sha(Path(__file__).read_bytes())
        identity = {"schema":SCHEMA,"code_sha256":code_sha,"inputs":inputs,
                    "phase":[[r["record_id"],r["source_id"],r["horizon_minutes"],now_ms>=r["target_end_ms"],r["status"]] for r in report["records"]],
                    "history_admissions":report["history_admissions"]}
        key = sha(encoded(identity)); target = outroot/("supplement_"+key[:24])
        if target.exists():
            prior = verify_existing(target)
            if prior.get("identity_sha256") != key:
                raise ValueError("supplement identity collision")
            return target,prior,True
        report.update(inputs=inputs,code_sha256=code_sha,identity_sha256=key,supplement_id=target.name,
                      historical_price_fetch_is_not_historical_CoinGlass_capture=True)
        stage = outroot/(".stage_"+uuid4().hex); stage.mkdir()
        bodies = {"report.json":json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False).encode()+b"\n",
                  "summary.md":summary(report).encode()}
        bodies["integrity.json"] = encoded({name:sha(body) for name,body in bodies.items()})+b"\n"
        for name,body in bodies.items():
            with (stage/name).open("xb") as handle:
                handle.write(body); handle.flush(); os.fsync(handle.fileno())
        publish_stage(stage,target); stage=None
        return target,report,False
    finally:
        os.close(fd); lock.unlink()
        if stage is not None and stage.exists():
            for name in ("report.json","summary.md","integrity.json"):
                if (stage/name).exists(): (stage/name).unlink()
            stage.rmdir()


def verification_export(report):
    return {"schema":"public-price-independent-check-v1","created_at_ms":time.time_ns()//1_000_000,
            "supplement_id":report["supplement_id"],"code_sha256":report["code_sha256"],
            "input_sha256":sorted({i["sha256"] for i in report["inputs"]}),
            "records":[{k:r[k] for k in ("record_id","record_kind","market","anchor_ms","anchor_utc","horizon_minutes",
                                         "status","baseline_open","end_close","return_pct","expected_bars","available_bars")}
                       for r in report["records"]],"raw_CoinGlass_included":False,"account_data_included":False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-root",required=True,type=Path)
    parser.add_argument("--history-root",action="append",default=[],type=Path)
    parser.add_argument("--outroot",required=True,type=Path)
    parser.add_argument("--public-export",type=Path,help="Explicit new JSON path; contains public-price check aggregates only")
    args=parser.parse_args()
    path,report,reused=evaluate(args.local_root,args.history_root,args.outroot)
    if args.public_export:
        output=no_links(args.public_export); output.parent.mkdir(parents=True,exist_ok=True)
        with output.open("xb") as handle:
            handle.write(json.dumps(verification_export(report),ensure_ascii=False,indent=2).encode()+b"\n")
    print(json.dumps({"path":str(path),"reused":reused,"status_counts":report["status_counts"],"network_requests":0},ensure_ascii=False))


if __name__ == "__main__":
    main()
