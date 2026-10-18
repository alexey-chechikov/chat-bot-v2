"""Finite public Binance BTCUSDT context. Network requires explicit --run-network.

Five GETs, or six with premium; no retries/redirects, auth, account, WS or daemon.
Returns a separate daily-as-seen-v1 input fragment, not a trade signal.
"""
from __future__ import annotations

import argparse
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
        request = Request(target, method="GET", headers={"Accept": "application/json", "User-Agent": "finite-public-context/1.0"})
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


def select_rows(payload, convert, expected=None):
    """Retain valid rows, expose gaps/rejections; conflicting duplicates are all excluded."""
    if not isinstance(payload, list):
        raise ValueError("expected JSON array, not an error/object response")
    selected, duplicates, errors = {}, set(), []
    observed_order = []
    for index, raw in enumerate(payload):
        try:
            key, row = convert(raw)
            observed_order.append(key)
            if key in selected or key in duplicates:
                duplicates.add(key)
                selected.pop(key, None)
                errors.append({"row": index, "reason": "duplicate_key_all_copies_excluded"})
            else:
                selected[key] = row
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            errors.append({"row": index, "reason": str(exc)})
    quality = []
    if errors:
        quality.append("rows_rejected_or_ambiguous")
    if observed_order != sorted(observed_order):
        quality.append("response_out_of_order")
    missing = sorted(set(expected or []) - set(selected))
    if missing:
        quality.append("missing_expected_grid_points")
    rows = [selected[key] for key in sorted(selected)]
    details = {"raw_row_count": len(payload), "usable_row_count": len(rows),
               "rejected_rows": errors, "missing_timestamps": missing}
    return rows, quality, details


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


def collect_context(client, *, include_premium=False, clock=now_ms, synthetic=False):
    """One finite fetch. Injected client/clock allow offline tests without a socket."""
    collected = stamp(clock())
    sources, evidence = [], {}
    count = 0

    def request_source(sid, target, market, settings, parser):
        nonlocal count
        request_ms = stamp(clock())
        count += 1
        if count > MAX_GETS:
            raise ValueError("finite request plan exceeded six GETs")
        try:
            response = client.get(target)
        except Exception as exc:
            # A failed attempt is retained and does not cause retries.
            response = Reply(None, b"", f"{type(exc).__name__}: {exc}")
        receive_ms = stamp(clock())
        audit = {"method": "GET", "url": target, "requested_at_ms": request_ms,
                 "received_at_ms": receive_ms, "http_status": response.status,
                 "error": response.error, "body_sha256": hashlib.sha256(response.body).hexdigest(),
                 "provider_lag_ms": None, "provider_lag_status": "unknown"}
        sf = ["provider_lag_unknown", "current_fetch_receive_not_historical_availability"]
        if receive_ms < request_ms:
            sf.append("local_wall_clock_non_monotonic")
        payload = None
        try:
            payload = json.loads(response.body.decode("utf-8"))
            is_json = True
        except (ValueError, UnicodeDecodeError):
            is_json = False
        stem = f"evidence/{sid}_{request_ms}"
        body_path = stem + (".raw.json" if is_json else ".raw.body")
        audit_path = stem + ".request.json"
        evidence[body_path] = response.body
        source = {"id": sid, "status": "FAILED", "url": target, "event_asof_ms": None,
                  "lag_status": "unknown", "provider_lag_ms": None, "stale_after_ms": DAY,
                  "market_scope": market, "aggregation": "single_exchange_public_REST",
                  "forming_bar": False if settings.get("interval") == "15m" else None,
                  "settings": dict(settings, request=audit), "values": None,
                  "evidence": [{"kind": "site_export", "path": body_path, "sha256": audit["body_sha256"]}],
                  "quality_flags": sf}
        result = None
        if response.error is not None or response.status is None or not 200 <= response.status < 300:
            sf.append("request_failed")
        elif not is_json:
            sf.append("response_not_valid_JSON")
        else:
            try:
                rows, quality, details, event_asof = parser(payload)
                sf.extend(quality)
                source["settings"]["validation"] = details
                source["event_asof_ms"] = event_asof
                source["status"] = "PARTIAL" if quality else "OK"
                if rows:
                    source["values"] = [{"name": "observations", "type": "json", "value": rows,
                                          "unit": settings.get("units", "fields_explicitly_named")}]
                else:
                    source["status"] = "MISSING"
                    sf.append("no_usable_observed_values")
                result = rows
            except (ValueError, KeyError, TypeError, IndexError) as exc:
                source["settings"]["validation_error"] = str(exc)
                sf.append("response_schema_invalid")
        evidence[audit_path] = dumps(audit)
        source["evidence"].append({"kind": "site_export", "path": audit_path,
                                   "sha256": hashlib.sha256(evidence[audit_path]).hexdigest()})
        sources.append(source)
        return result

    def clock_parser(payload):
        ts = stamp(payload["serverTime"])
        if abs(ts - collected) > 300_000:
            raise ValueError("provider_clock_differs_from_actual_local_collection_by_over_5min")
        return [{"server_time_ms": ts}], [], {}, ts

    anchor_rows = request_source("binance_public_clock", url(FUTURES, "/fapi/v1/time"), "public_clock",
                                 {"clock_role": "common_futures_UTC_anchor_for_both_markets", "units": "UTC_ms"}, clock_parser)
    server = anchor_rows[0]["server_time_ms"] if anchor_rows else None
    end = server // STEP * STEP if server is not None else None
    start = end - DAY if end is not None else None
    klines_settings = {"symbol": "BTCUSDT", "interval": "15m", "requested_closed_bars": 96,
                       "start_ms_inclusive": start, "end_ms_exclusive": end,
                       "closure_clock": "futures_public_serverTime", "units": "OHLC/quote USDT; base/delta BTC; F/shares fraction",
                       "delta_formula": "2*taker_buy_base-base_volume", "CVD_level_used_as_flow": False}
    plans = [
        ("binance_spot_15m", SPOT, "/api/v3/klines", "spot", dict(klines_settings, cross_market_clock_alignment_unmeasured=True),
         {"symbol": "BTCUSDT", "interval": "15m", "limit": 96, "startTime": start, "endTime": end - 1 if end is not None else None},
         lambda p: parse_klines(p, start, end, server)),
        ("binance_perp_15m", FUTURES, "/fapi/v1/klines", "futures", dict(klines_settings),
         {"symbol": "BTCUSDT", "interval": "15m", "limit": 96, "startTime": start, "endTime": end - 1 if end is not None else None},
         lambda p: parse_klines(p, start, end, server)),
        ("binance_oi_15m", FUTURES, "/futures/data/openInterestHist", "futures",
         {"symbol": "BTCUSDT", "interval": "15m", "start_ms_inclusive": start, "end_ms_inclusive": end,
          "expected_points": 97, "timestamp_semantics": "provider_period_end", "units": "provider-native OI quantity and reported notional kept separate"},
         {"symbol": "BTCUSDT", "period": "15m", "limit": 97, "startTime": start, "endTime": end},
         lambda p: parse_oi(p, start, end)),
        ("binance_funding_24h", FUTURES, "/fapi/v1/fundingRate", "futures",
         {"symbol": "BTCUSDT", "start_ms_inclusive": server - DAY if server is not None else None, "end_ms_inclusive": server,
          "settlement_interval_assumed": False, "units": "rate fraction; associated mark USDT"},
         {"symbol": "BTCUSDT", "limit": 1000, "startTime": server - DAY if server is not None else None, "endTime": server},
         lambda p: parse_funding(p, server - DAY, server)),
    ]
    if include_premium:
        plans.append(("binance_premium_current", FUTURES, "/fapi/v1/premiumIndex", "futures",
                      {"symbol": "BTCUSDT", "units": "mark/index USDT; funding fraction; UTC_ms"},
                      {"symbol": "BTCUSDT"}, parse_premium))
    for sid, base, path, market, settings, query, parser in plans:
        if server is None:
            sources.append({"id": sid, "status": "MISSING", "url": url(base, path, symbol="BTCUSDT"),
                            "event_asof_ms": None, "lag_status": "unknown", "provider_lag_ms": None,
                            "market_scope": market, "aggregation": "single_exchange_public_REST",
                            "forming_bar": None, "settings": dict(settings, request_not_attempted=True),
                            "values": None, "evidence": [], "quality_flags": ["clock_dependency_unavailable_no_local_time_fallback"]})
        else:
            request_source(sid, url(base, path, **query), market, settings, parser)
    finished = stamp(clock())
    fragment = {"schema": "daily-as-seen-v1", "timezone": "Europe/Warsaw", "synthetic": synthetic,
                "collected_at_ms": collected, "finished_at_ms": finished,
                "quality_flags": ["public_Binance_context_not_CoinGlass_API", "independent_request_times_not_synchronized_snapshot"],
                "order_permission": False, "trade_primary": False, "auto_allowed_primary": False,
                "sources": sources, "fetch_summary": {"attempted_GETs": count, "maximum_GETs": MAX_GETS,
                                                        "retries": 0, "redirects_allowed": False, "continuous_collection": False}}
    return fragment, evidence


def _reject_reparse_ancestors(path):
    """Reject symlinks and Windows junction/reparse points, including ancestors."""
    for current in (path, *path.parents):
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise ValueError("output path/ancestor is a symlink, junction or reparse point")


def validate_output_tree(outdir, relatives=()):
    """Read-only preflight; no mkdir, client construction or GET here."""
    root = Path(os.path.abspath(os.fspath(outdir)))
    _reject_reparse_ancestors(root)
    if root.resolve() != root:
        raise ValueError("explicit outdir or an ancestor resolves through a redirect")
    if root.exists() and not root.is_dir():
        raise ValueError("outdir must be a directory")
    evidence_root = root / "evidence"
    paths = [evidence_root, root / "public_sources.json"]
    for rel in relatives:
        candidate = Path(rel.replace("\\", "/"))
        if (candidate.is_absolute() or candidate.drive or ".." in candidate.parts or ":" in rel
                or len(candidate.parts) < 2 or candidate.parts[0] != "evidence"):
            raise ValueError("evidence path must remain under explicit outdir/evidence")
        paths.append(root / candidate)
    for path in paths:
        _reject_reparse_ancestors(path)
        if not path.resolve().is_relative_to(root):
            raise ValueError("resolved output/evidence path escapes explicit outdir")
    if evidence_root.exists() and not evidence_root.is_dir():
        raise ValueError("evidence must be a directory")
    return root


def write_fragment(outdir, fragment, evidence):
    """Add only new own files to an explicit existing or new outdir."""
    outdir = validate_output_tree(outdir, evidence)
    target = outdir / "public_sources.json"
    paths = [target] + [outdir / rel for rel in evidence]
    if any(path.exists() for path in paths):
        raise ValueError("refuse overwrite of public_sources.json or own evidence files")
    outdir.mkdir(parents=True, exist_ok=True)
    for rel, payload in evidence.items():
        validate_output_tree(outdir, [rel])
        path = outdir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        validate_output_tree(outdir, [rel])
        with path.open("xb") as handle:
            handle.write(payload)
    # Publish the fragment last, only after its evidence exists.
    validate_output_tree(outdir)
    with target.open("xb") as handle:
        handle.write(dumps(fragment))
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", required=True, type=Path)
    parser.add_argument("--run-network", action="store_true", help="explicit one-off permission; no network without this flag")
    parser.add_argument("--include-premium", action="store_true", help="sixth and final public GET")
    args = parser.parse_args(argv)
    if not args.run_network:
        parser.error("no network performed: --run-network is required after code review")
    try:
        # Validate the existing root/evidence namespace before constructing a
        # client. Revalidate after GETs and immediately before each write.
        outdir = validate_output_tree(args.outdir)
        if (outdir / "public_sources.json").exists():
            parser.error("public_sources.json already exists; no requests performed")
        fragment, evidence = collect_context(PublicClient(), include_premium=args.include_premium)
        target = write_fragment(outdir, fragment, evidence)
        print(json.dumps({"output": str(target), "GETs": fragment["fetch_summary"]["attempted_GETs"],
                          "sources": [{"id": s["id"], "status": s["status"]} for s in fragment["sources"]]}))
        return 0
    except (ValueError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
