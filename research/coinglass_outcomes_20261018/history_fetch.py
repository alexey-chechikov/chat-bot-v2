"""Finite 96h public history plus compatible 24h tail. No network on import.

Standalone stdlib parsers derive from fetch_public_context.py SHA256
74c979e12c7ac095053120be5b71a000650ab58dcb29f652e6c9b19fed495e98.
New collection is review-only until separately activated.
"""
from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import stat
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

STEP = 900_000
DAY = 86_400_000
HISTORY = 4 * DAY
HISTORY_BARS = 384
MAX_GETS = 6
TIMEOUT_SECONDS = 8
MAX_BODY_BYTES = 2 * 1024 * 1024
FUTURES = "https://fapi.binance.com"
SPOT = "https://api.binance.com"
ALLOWED = {
    ("fapi.binance.com", "/fapi/v1/time"),
    ("api.binance.com", "/api/v3/klines"),
    ("fapi.binance.com", "/fapi/v1/klines"),
    ("fapi.binance.com", "/futures/data/openInterestHist"),
    ("fapi.binance.com", "/fapi/v1/fundingRate"),
    ("fapi.binance.com", "/fapi/v1/premiumIndex"),
}


def now_ms():
    return time.time_ns() // 1_000_000


def stamp(value):
    if type(value) is not int or value < 0:
        raise ValueError("timestamp must be nonnegative integer UTC milliseconds")
    return value


def dec(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("expected finite decimal")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("expected finite decimal") from exc
    if not result.is_finite():
        raise ValueError("non-finite decimal")
    return result


def url(base, path, **query):
    return base + path + ("?" + urlencode(query) if query else "")


def dumps(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


@dataclass(frozen=True)
class Reply:
    status: int | None
    body: bytes
    error: str | None = None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PublicClient:
    """Only fixed public paths. No credentials/proxies/redirects/retry loops."""
    def __init__(self):
        self.get_count = 0
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def get(self, target):
        parsed = urlsplit(target)
        if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port or parsed.fragment
                or (parsed.hostname, parsed.path) not in ALLOWED):
            raise ValueError("only the fixed public Binance endpoint allowlist is permitted")
        if self.get_count >= MAX_GETS:
            raise ValueError("finite GET budget exhausted")
        self.get_count += 1
        request = Request(target, method="GET", headers={"Accept": "application/json", "User-Agent": "finite-public-outcome-history/1.0"})
        try:
            with self.opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                body = response.read(MAX_BODY_BYTES + 1)
                if len(body) > MAX_BODY_BYTES:
                    return Reply(response.status, body[:MAX_BODY_BYTES], "response_body_truncated_at_2MiB")
                return Reply(response.status, body)
        except HTTPError as exc:
            body = exc.read(MAX_BODY_BYTES + 1)
            suffix = "; response_body_truncated_at_2MiB" if len(body) > MAX_BODY_BYTES else ""
            return Reply(exc.code, body[:MAX_BODY_BYTES], f"HTTP_{exc.code}{suffix}")
        except (URLError, TimeoutError, OSError) as exc:
            return Reply(None, b"", f"{type(exc).__name__}: {exc}")


def _row_equal(left, right):
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) == set(right) and all(_row_equal(left[k], right[k]) for k in left)
    if isinstance(left, str) and isinstance(right, str):
        try:
            return dec(left) == dec(right)
        except ValueError:
            return left == right
    return left == right


def select_rows(payload, convert, expected=None):
    """Dedup equivalent rows; exclude all conflicting copies and expose their keys."""
    if not isinstance(payload, list):
        raise ValueError("expected JSON array, not an error/object response")
    selected, conflicts, errors, duplicates, order = {}, set(), [], [], []
    for index, raw in enumerate(payload):
        try:
            key, row = convert(raw)
            order.append(key)
            if key in conflicts:
                continue
            if key in selected:
                if _row_equal(selected[key], row):
                    duplicates.append(key)
                else:
                    conflicts.add(key)
                    selected.pop(key)
                    errors.append({"row": index, "reason": "conflicting_duplicate_all_copies_excluded", "key": key})
            else:
                selected[key] = row
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            errors.append({"row": index, "reason": str(exc)})
    quality = []
    if errors:
        quality.append("rows_rejected_or_ambiguous")
    if conflicts:
        quality.append("conflicting_duplicate_timestamps")
    if duplicates:
        quality.append("equivalent_duplicates_deduplicated")
    if order != sorted(order):
        quality.append("response_out_of_order")
    missing = sorted(set(expected or []) - set(selected))
    if missing:
        quality.append("missing_expected_grid_points")
    details = {"raw_row_count": len(payload), "usable_row_count": len(selected),
               "rejected_rows": errors, "missing_timestamps": missing,
               "conflicting_timestamps": sorted(conflicts), "equivalent_duplicate_keys": duplicates}
    return [selected[key] for key in sorted(selected)], quality, details


def parse_klines(payload, start, end, server_ms):
    def convert(raw):
        if not isinstance(raw, list) or len(raw) < 11:
            raise ValueError("malformed_kline_array")
        ts, close_time = stamp(raw[0]), stamp(raw[6])
        if ts % STEP or close_time != ts + STEP - 1:
            raise ValueError("misaligned_or_wrong_close_time")
        if not start <= ts < end or ts + STEP > end or close_time >= server_ms:
            raise ValueError("forming_or_out_of_requested_closed_window")
        o, h, l, c = [dec(raw[i]) for i in (1, 2, 3, 4)]
        volume, quote, buy, buy_quote = [dec(raw[i]) for i in (5, 7, 9, 10)]
        if min(o, h, l, c) <= 0 or l > min(o, c) or h < max(o, c) or l > h:
            raise ValueError("invalid_OHLC")
        if min(volume, quote, buy, buy_quote) < 0 or buy > volume or buy_quote > quote:
            raise ValueError("invalid_volume_or_taker_fields")
        trades = stamp(raw[8])
        delta = 2 * buy - volume
        return ts, {"bar_start_ms": ts, "bar_end_ms": ts + STEP, "provider_close_time_ms": close_time,
                    "open": str(o), "high": str(h), "low": str(l), "close": str(c),
                    "base_volume": str(volume), "quote_volume": str(quote), "trade_count": trades,
                    "taker_buy_base": str(buy), "taker_buy_quote": str(buy_quote), "delta_base": str(delta),
                    "F": str(delta / volume) if volume else None,
                    "buy_share": str(buy / volume) if volume else None,
                    "sell_share": str((volume - buy) / volume) if volume else None, "closed": True}
    rows, quality, details = select_rows(payload, convert, range(start, end, STEP))
    if any(row["F"] is None for row in rows):
        quality.append("zero_volume_F_and_shares_null")
    return rows, quality, details, max((row["bar_end_ms"] for row in rows), default=None)


def parse_oi(payload, start, end):
    def convert(raw):
        if raw["symbol"] != "BTCUSDT":
            raise ValueError("wrong_OI_symbol")
        ts = stamp(raw["timestamp"])
        if ts % STEP or not start <= ts <= end:
            raise ValueError("OI_outside_expected_period_end_grid")
        quantity, value = dec(raw["sumOpenInterest"]), dec(raw["sumOpenInterestValue"])
        if min(quantity, value) < 0:
            raise ValueError("negative_OI")
        return ts, {"timestamp_ms": ts, "sum_open_interest": str(quantity), "sum_open_interest_value": str(value),
                    "quantity_unit": "provider_native_open_interest_units", "value_unit": "provider_reported_notional_value",
                    "historical_received_ms": None, "provider_lag_ms": None}
    rows, quality, details = select_rows(payload, convert, range(start, end + STEP, STEP))
    return rows, quality, details, max((row["timestamp_ms"] for row in rows), default=None)


def parse_funding(payload, start, end):
    def convert(raw):
        if raw["symbol"] != "BTCUSDT":
            raise ValueError("wrong_funding_symbol")
        ts = stamp(raw["fundingTime"])
        if not start <= ts <= end:
            raise ValueError("funding_outside_requested_window")
        rate = dec(raw["fundingRate"])
        mark = None if raw.get("markPrice") is None else dec(raw["markPrice"])
        if mark is not None and mark <= 0:
            raise ValueError("invalid_funding_mark_price")
        rate_type = raw.get("rateType")
        if rate_type is not None and not isinstance(rate_type, str):
            raise ValueError("invalid_rate_type")
        # The API permits regular/special events at a common fundingTime.
        return (ts, rate_type or ""), {"funding_time_ms": ts, "funding_rate_fraction": str(rate),
                                      "rate_type": rate_type, "mark_price_USDT": str(mark) if mark is not None else None}
    rows, quality, details = select_rows(payload, convert)
    if any(row["mark_price_USDT"] is None for row in rows):
        quality.append("funding_mark_price_missing")
    if not rows:
        quality.append("no_observed_funding_events_not_zero_cost")
    if isinstance(payload, list) and len(payload) >= 1000:
        quality.append("funding_limit_saturated_coverage_unknown_no_pagination")
    quality.append("settlement_interval_not_assumed")
    return rows, quality, details, max((row["funding_time_ms"] for row in rows), default=None)


def parse_premium(payload):
    if not isinstance(payload, dict) or payload.get("symbol") != "BTCUSDT":
        raise ValueError("wrong_premium_symbol_or_payload")
    ts = stamp(payload["time"])
    mark, index = dec(payload["markPrice"]), dec(payload["indexPrice"])
    if min(mark, index) <= 0:
        raise ValueError("invalid_mark_or_index")
    row = {"timestamp_ms": ts, "mark_price_USDT": str(mark), "index_price_USDT": str(index),
           "latest_funding_rate_fraction": str(dec(payload["lastFundingRate"])),
           "next_funding_time_ms": stamp(payload["nextFundingTime"])}
    return [row], ["current_snapshot_not_closed_bar_not_executable_quote"], {}, ts


LEGACY_STABLE = {"symbol", "exchange", "exchanges", "model", "mode", "window", "windows_hours", "interval",
                 "bar_interval", "timeframe", "threshold", "merge", "range_percent", "currency", "units",
                 "delta_formula", "CVD_level_used_as_flow", "closure_clock", "clock_role", "timestamp_semantics",
                 "requested_closed_bars", "expected_points", "settlement_interval_assumed", "liquidation_map",
                 "cross_market_clock_alignment_unmeasured"}


def legacy_definition(source):
    """Exact old semantics, including the OI row-unit enrichment used by oi_metrics."""
    parts = urlsplit(source["url"])
    definition = {"source_id": source["id"], "source_path": f"{parts.scheme}://{parts.netloc}{parts.path}",
                  "market_scope": source["market_scope"], "aggregation": source["aggregation"],
                  "settings": {k: source["settings"][k] for k in sorted(LEGACY_STABLE) if k in source["settings"]}}
    if source["id"] == "binance_oi_15m":
        definition["row_units"] = [["provider_native_open_interest_units", "provider_reported_notional_value"]]
    return definition


def _legacy_settings(sid, daily_start, end, server):
    if sid in ("binance_spot_15m", "binance_perp_15m"):
        result = {"symbol": "BTCUSDT", "interval": "15m", "requested_closed_bars": 96,
                  "start_ms_inclusive": daily_start, "end_ms_exclusive": end,
                  "closure_clock": "futures_public_serverTime", "units": "OHLC/quote USDT; base/delta BTC; F/shares fraction",
                  "delta_formula": "2*taker_buy_base-base_volume", "CVD_level_used_as_flow": False}
        if sid == "binance_spot_15m":
            result["cross_market_clock_alignment_unmeasured"] = True
        return result
    if sid == "binance_oi_15m":
        return {"symbol": "BTCUSDT", "interval": "15m", "start_ms_inclusive": daily_start, "end_ms_inclusive": end,
                "expected_points": 97, "timestamp_semantics": "provider_period_end",
                "units": "provider-native OI quantity and reported notional kept separate"}
    if sid == "binance_funding_24h":
        return {"symbol": "BTCUSDT", "start_ms_inclusive": server - DAY if server is not None else None,
                "end_ms_inclusive": server, "settlement_interval_assumed": False,
                "units": "rate fraction; associated mark USDT"}
    if sid == "binance_premium_current":
        return {"symbol": "BTCUSDT", "units": "mark/index USDT; funding fraction; UTC_ms"}
    return {"clock_role": "common_futures_UTC_anchor_for_both_markets", "units": "UTC_ms"}


def _daily_view(source, settings, rows, daily_start, end):
    daily = copy.deepcopy(source)
    daily.pop("legacy_definition", None)
    daily["settings"] = copy.deepcopy(settings)
    for field in ("request", "transport", "validation_error"):
        if field in source["settings"]:
            daily["settings"][field] = copy.deepcopy(source["settings"][field])
    if rows is None:
        return daily
    sid = source["id"]
    if sid in ("binance_spot_15m", "binance_perp_15m"):
        kept = [r for r in rows if daily_start <= r["bar_start_ms"] < end]
        expected = list(range(daily_start, end, STEP))
        present = {r["bar_start_ms"] for r in kept}
        event = max((r["bar_end_ms"] for r in kept), default=None)
    elif sid == "binance_oi_15m":
        kept = [r for r in rows if daily_start <= r["timestamp_ms"] <= end]
        expected = list(range(daily_start, end + STEP, STEP))
        present = {r["timestamp_ms"] for r in kept}
        event = max((r["timestamp_ms"] for r in kept), default=None)
    else:
        return daily
    details = source["settings"].get("validation", {})
    conflicts = [t for t in details.get("conflicting_timestamps", []) if t in expected]
    missing = sorted(set(expected) - present)
    daily["settings"]["validation"] = {"raw_extended_response_row_count": details.get("raw_row_count"),
        "usable_row_count": len(kept), "expected_points": len(expected), "missing_timestamps": missing,
        "conflicting_timestamps": conflicts, "tail_of_finite_96h_request": True,
        "extended_response_rejected_rows": details.get("rejected_rows", [])}
    daily["conflicting_timestamps"] = conflicts
    # A gap in the older part of extended history does not spoil a complete current 24h tail.
    daily["quality_flags"] = [q for q in daily["quality_flags"] if q not in
                              ("missing_expected_grid_points", "conflicting_duplicate_timestamps", "rows_rejected_or_ambiguous")]
    if missing:
        daily["quality_flags"].append("missing_expected_grid_points")
    if conflicts:
        daily["quality_flags"].append("conflicting_duplicate_timestamps")
    daily["event_asof_ms"] = event
    daily["values"] = [{"name": "observations", "type": "json", "value": kept, "unit": settings["units"]}] if kept else None
    daily["status"] = ("PARTIAL" if missing or conflicts else "OK") if kept else "MISSING"
    return daily


def collect(client, *, include_premium=True, clock=now_ms, synthetic=False):
    """Finite fixed plan. A fake client and clock are sufficient for every offline test."""
    if type(synthetic) is not bool or type(include_premium) is not bool:
        raise ValueError("explicit boolean flags required")
    collected = stamp(clock())
    evidence, history_sources, daily_sources = {}, [], []
    count = 0

    def request_source(sid, target, market, settings, parser):
        nonlocal count
        if count >= MAX_GETS:
            raise ValueError("finite six-GET collection budget exhausted")
        requested = stamp(clock())
        count += 1
        try:
            response = client.get(target)
        except Exception as exc:
            response = Reply(None, b"", f"{type(exc).__name__}: {exc}")
        received = stamp(clock())
        if not isinstance(response.body, bytes) or len(response.body) > MAX_BODY_BYTES:
            response = Reply(response.status, b"", "invalid_or_oversized_client_body")
        audit = {"method": "GET", "url": target, "requested_at_ms": requested, "received_at_ms": received,
                 "http_status": response.status, "error": response.error,
                 "body_sha256": hashlib.sha256(response.body).hexdigest(),
                 "provider_lag_ms": None, "provider_lag_status": "unknown"}
        flags = ["provider_lag_unknown", "current_fetch_receive_not_historical_availability"]
        if received < requested:
            audit["error"] = "local_wall_clock_non_monotonic"
            flags.append("local_wall_clock_non_monotonic")
        try:
            payload = json.loads(response.body.decode("utf-8"))
            is_json = True
        except (ValueError, UnicodeDecodeError):
            payload, is_json = None, False
        stem = f"evidence/history_{sid}_{requested}"
        body_path = stem + (".raw.json" if is_json else ".raw.body")
        audit_path = stem + ".request.json"
        evidence[body_path] = response.body
        source = {"id": sid, "status": "FAILED", "url": target, "event_asof_ms": None,
                  "received_at_ms": received, "lag_status": "unknown", "provider_lag_ms": None,
                  "stale_after_ms": DAY, "market_scope": market, "aggregation": "single_exchange_public_REST",
                  "forming_bar": False if settings.get("interval") == "15m" else None,
                  "settings": dict(settings, request=audit), "values": None,
                  "evidence": [{"kind": "site_export", "path": body_path, "sha256": audit["body_sha256"]}],
                  "quality_flags": flags}
        rows = None
        if audit["error"] is not None or response.status is None or not 200 <= response.status < 300:
            flags.append("request_failed")
        elif not is_json:
            flags.append("response_not_valid_JSON")
        else:
            try:
                rows, quality, details, event = parser(payload)
                source["settings"]["validation"] = details
                source["conflicting_timestamps"] = details.get("conflicting_timestamps", [])
                source["event_asof_ms"] = event
                flags.extend(quality)
                source["status"] = ("PARTIAL" if quality else "OK") if rows else "MISSING"
                if rows:
                    source["values"] = [{"name": "observations", "type": "json", "value": rows,
                                          "unit": settings.get("units", "fields_explicitly_named")}]
                else:
                    flags.append("no_usable_observed_values")
            except (ValueError, KeyError, TypeError, IndexError) as exc:
                source["settings"]["validation_error"] = str(exc)
                flags.append("response_schema_invalid")
        evidence[audit_path] = dumps(audit)
        source["evidence"].append({"kind": "site_export", "path": audit_path,
                                   "sha256": hashlib.sha256(evidence[audit_path]).hexdigest()})
        return source, rows

    def parse_clock(payload):
        server_ms = stamp(payload["serverTime"])
        if abs(server_ms - collected) > 300_000:
            raise ValueError("provider_clock_differs_from_local_by_over_5min")
        return [{"server_time_ms": server_ms}], [], {}, server_ms

    clock_settings = _legacy_settings("binance_public_clock", None, None, None)
    clock_source, clock_rows = request_source("binance_public_clock", url(FUTURES, "/fapi/v1/time"), "public_clock",
                                               clock_settings, parse_clock)
    clock_source["legacy_definition"] = legacy_definition(clock_source)
    history_sources.append(clock_source)
    daily_sources.append(copy.deepcopy(clock_source))
    daily_sources[-1].pop("legacy_definition")
    server = clock_rows[0]["server_time_ms"] if clock_rows else None
    closure_ms = min(collected, server) if server is not None else None
    end = closure_ms // STEP * STEP if closure_ms is not None else None
    start = end - HISTORY if end is not None else None
    daily_start = end - DAY if end is not None else None
    transport = {"history_hours": 96, "history_start_ms_inclusive": start, "history_end_ms": end,
                 "actual_closure_policy": "floor_to_15m(min(actual_collection_start,public_server_time))",
                 "actual_local_collection_start_ms": collected, "server_time_ms": server,
                 "known_clock_skew_server_minus_local_ms": server - collected if server is not None else None,
                 "skew_is_not_provider_lag": True}
    plans = [
        ("binance_spot_15m", SPOT, "/api/v3/klines", "spot",
         {"symbol": "BTCUSDT", "interval": "15m", "limit": HISTORY_BARS, "startTime": start, "endTime": end - 1 if end is not None else None},
         lambda p: parse_klines(p, start, end, closure_ms)),
        ("binance_perp_15m", FUTURES, "/fapi/v1/klines", "futures",
         {"symbol": "BTCUSDT", "interval": "15m", "limit": HISTORY_BARS, "startTime": start, "endTime": end - 1 if end is not None else None},
         lambda p: parse_klines(p, start, end, closure_ms)),
        ("binance_oi_15m", FUTURES, "/futures/data/openInterestHist", "futures",
         {"symbol": "BTCUSDT", "period": "15m", "limit": HISTORY_BARS + 1, "startTime": start, "endTime": end},
         lambda p: parse_oi(p, start, end)),
        ("binance_funding_24h", FUTURES, "/fapi/v1/fundingRate", "futures",
         {"symbol": "BTCUSDT", "limit": 1000, "startTime": server - DAY if server is not None else None, "endTime": server},
         lambda p: parse_funding(p, server - DAY, server)),
    ]
    if include_premium:
        plans.append(("binance_premium_current", FUTURES, "/fapi/v1/premiumIndex", "futures", {"symbol": "BTCUSDT"}, parse_premium))
    for sid, base, path, market, query, parser in plans:
        legacy_settings = _legacy_settings(sid, daily_start, end, server)
        extended_settings = copy.deepcopy(legacy_settings)
        if sid in ("binance_spot_15m", "binance_perp_15m"):
            extended_settings.update(requested_closed_bars=HISTORY_BARS, start_ms_inclusive=start)
        elif sid == "binance_oi_15m":
            extended_settings.update(expected_points=HISTORY_BARS + 1, start_ms_inclusive=start)
        extended_settings["transport"] = copy.deepcopy(transport)
        if server is None:
            source = {"id": sid, "status": "MISSING", "url": url(base, path, symbol="BTCUSDT"),
                      "event_asof_ms": None, "received_at_ms": None, "lag_status": "unknown", "provider_lag_ms": None,
                      "stale_after_ms": DAY, "market_scope": market, "aggregation": "single_exchange_public_REST",
                      "forming_bar": None, "settings": dict(extended_settings, request_not_attempted=True),
                      "values": None, "evidence": [], "quality_flags": ["clock_dependency_unavailable_no_local_time_fallback"]}
            rows = None
        else:
            source, rows = request_source(sid, url(base, path, **query), market, extended_settings, parser)
        identity_source = dict(source, settings=legacy_settings)
        source["legacy_definition"] = legacy_definition(identity_source)
        history_sources.append(source)
        daily = _daily_view(source, legacy_settings, rows, daily_start, end)
        if server is None:
            daily["settings"]["request_not_attempted"] = True
        daily_sources.append(daily)
    finished = stamp(clock())
    if finished < collected:
        raise ValueError("local collection finish precedes start; no successful bundle")
    fetch_summary = {"attempted_GETs": count, "maximum_GETs": MAX_GETS, "retries": 0,
                     "redirects_allowed": False, "continuous_collection": False, "history_hours": 96}
    common = {"timezone": "Europe/Warsaw", "synthetic": synthetic, "collected_at_ms": collected,
              "finished_at_ms": finished, "order_permission": False, "trade_primary": False,
              "auto_allowed_primary": False, "fetch_summary": fetch_summary}
    history = dict(common, schema="coinglass-outcome-history-v1", cutoff_ms=end, sources=history_sources,
                   utility_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   quality_flags=["finite_public_history_received_now_not_past_availability",
                                  "more_than_96h_absence_not_repaired", "not_a_CoinGlass_snapshot"])
    daily = dict(common, schema="daily-as-seen-v1", sources=daily_sources,
                 quality_flags=["public_Binance_context_not_CoinGlass_API", "independent_request_times_not_synchronized_snapshot",
                                "legacy_24h_tail_of_finite_96h_history"])
    return history, daily, evidence


def _reject_reparse_ancestors(path):
    for candidate in (path, *path.parents):
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise ValueError("output or ancestor is a symlink/junction/reparse point")


def validate_output(outdir, relatives=()):
    outdir = Path(outdir)
    if not outdir.is_absolute() or outdir.parent == outdir:
        raise ValueError("an explicit absolute non-root outdir is required")
    _reject_reparse_ancestors(outdir)
    root = outdir.resolve()
    if root != outdir.absolute() or (root.exists() and not root.is_dir()):
        raise ValueError("outdir redirect or non-directory refused")
    paths = [root / "history.json", root / "public_sources.json", root / "evidence",
             root / ".history.reserve", root / ".collection.reserve"]
    for given in relatives:
        rel = Path(given.replace("\\", "/"))
        if rel.is_absolute() or rel.drive or ".." in rel.parts or ":" in given or len(rel.parts) != 2 or rel.parts[0] != "evidence":
            raise ValueError("evidence path must be a plain child under evidence/")
        paths.append(root / rel)
    for path in paths:
        _reject_reparse_ancestors(path)
        if not path.resolve().is_relative_to(root):
            raise ValueError("output path escapes outdir")
    if (root / "evidence").exists() and not (root / "evidence").is_dir():
        raise ValueError("evidence must be a directory")
    return root


def _write_new(path, body):
    with path.open("xb") as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())


def write_bundle(outdir, history, daily, evidence):
    """Commit history.json last; never overwrite. A failed partial directory is not a successful collection."""
    root = validate_output(outdir, evidence)
    targets = [root / "history.json", root / "public_sources.json", *(root / rel for rel in evidence)]
    if any(path.exists() for path in targets):
        raise FileExistsError("refuse overwrite of bundle or own evidence")
    root.mkdir(parents=True, exist_ok=True)
    validate_output(root, evidence)
    lock = root / ".history.reserve"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        for rel, body in evidence.items():
            validate_output(root, [rel])
            path = root / rel
            path.parent.mkdir(exist_ok=True)
            validate_output(root, [rel])
            _write_new(path, body)
        validate_output(root, evidence)
        _write_new(root / "public_sources.json", dumps(daily))
        _write_new(root / "history.json", dumps(history))
    finally:
        os.close(fd)
        lock.unlink()
    return root / "history.json"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--run-network", action="store_true")
    parser.add_argument("--include-premium", action="store_true")
    args = parser.parse_args(argv)
    if not args.run_network:
        parser.error("no network performed: --run-network requires separate activation after review")
    try:
        root = validate_output(args.outdir)
        if any((root / name).exists() for name in ("history.json", "public_sources.json", ".history.reserve", ".collection.reserve")):
            parser.error("bundle already exists or busy; no requests performed")
        root.mkdir(parents=True, exist_ok=True)
        validate_output(root)
        # Reserve before constructing the HTTP client; a concurrent invocation
        # for the same namespace does not spend another six requests.
        collection_lock = root / ".collection.reserve"
        fd = os.open(collection_lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            if any((root / name).exists() for name in ("history.json", "public_sources.json", ".history.reserve")):
                raise FileExistsError("bundle appeared during reservation; no requests performed")
            history, daily, evidence = collect(PublicClient(), include_premium=args.include_premium)
            target = write_bundle(root, history, daily, evidence)
        finally:
            os.close(fd)
            collection_lock.unlink()
        print(json.dumps({"history": str(target), "daily_fragment": str(root / "public_sources.json"),
                          "GETs": history["fetch_summary"]["attempted_GETs"], "cutoff_ms": history["cutoff_ms"]}))
        return 0
    except (ValueError, OSError) as exc:
        parser.exit(2, f"collection refused: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())


