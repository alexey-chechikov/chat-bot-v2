"""Finite, offline verification of the public WEEX release. No fills, PnL or network."""
from __future__ import annotations

import argparse
import collections
import copy
import csv
import hashlib
import json
import math
import re
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ARCHIVE = "weex_book_v2_20261015_20261018.tar.xz"
MANIFEST = "weex_book_v2_manifest.json"
ARCHIVE_SHA = "a6c4585ec59aa12e5d4cb27d0b747b8b258b0efb2644afb055677c26834b5191"
MANIFEST_SHA = "193b9516761b164c7fbe05610c1d6306de42be475461d9901a0cea7b22486c08"
HEADERS = {
    "depth": ["kind", "U", "u", "E", "recv_ms", "session", "applied", "b", "a"],
    "trades2": ["t", "T", "E", "recv_ms", "session", "p", "q", "m_raw"],
    "events": ["recv_ms", "session", "event", "detail"],
}
STALE_AFTER_MS = 2000  # Conservative quality exclusion, not an exchange SLA.


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="milliseconds")


def epoch(text):
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp() * 1000)


def merge_span(spans, a, b):
    if b <= a:
        return
    if spans and spans[-1][0] <= a <= spans[-1][1]:
        spans[-1][1] = max(spans[-1][1], b)
    else:
        spans.append([a, b])


def clip(spans, a, b):
    return [[max(a, x), min(b, y)] for x, y in spans if max(a, x) < min(b, y)]


def complement(spans, a, b):
    out, cursor = [], a
    for x, y in clip(spans, a, b):
        if x > cursor:
            out.append([cursor, x])
        cursor = max(cursor, y)
    if cursor < b:
        out.append([cursor, b])
    return out


def pretty_spans(spans):
    return [{"start_utc": iso(a), "end_utc_exclusive": iso(b), "duration_ms": b-a} for a, b in spans]


def quantiles(counter):
    n = sum(counter.values())
    if not n:
        return {"count": 0}
    result = {"count": n, "min": min(counter), "max": max(counter)}
    ordered = sorted(counter.items())
    for label, p in (("p50", .5), ("p90", .9), ("p95", .95), ("p99", .99)):
        rank, cumulative = max(1, math.ceil(n*p)), 0
        for value, count in ordered:
            cumulative += count
            if cumulative >= rank:
                result[label] = value
                break
    return result


def extract_verified(local):
    """Stream only named regular files; no extractall, links, traversal or device entries."""
    manifest_path, archive_path = local / MANIFEST, local / ARCHIVE
    if sha256(manifest_path) != MANIFEST_SHA or sha256(archive_path) != ARCHIVE_SHA:
        raise ValueError("Release asset SHA256 mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {entry["file"]: entry for entry in manifest["files"]}
    if len(expected) != 24 or any(not re.fullmatch(r"(BTCUSDT|ETHUSDT)_202610(15|16|17|18)_(depth|trades2|events)\.csv", n) for n in expected):
        raise ValueError("Unexpected external manifest file inventory")
    target = local / "verified_members"
    target.mkdir(exist_ok=True)
    if target.is_symlink():
        raise ValueError("Symlink target folder")
    members, internal, verified = [], None, []
    with tarfile.open(archive_path, mode="r|xz") as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or "\\" in member.name or ":" in member.name:
                raise ValueError("Unsafe archive member path")
            members.append({"name": member.name, "bytes": member.size, "type": member.type.decode("ascii", errors="replace")})
            if len(members) > 40:
                raise ValueError("Too many archive members")
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError("Non-regular archive member")
            basename = name.name
            if basename == "manifest.json":
                if internal is not None or member.size > 100_000:
                    raise ValueError("Duplicate/oversized internal manifest")
                internal = json.loads(archive.extractfile(member).read().decode("utf-8"))
                continue
            if basename not in expected or basename in {r["file"] for r in verified}:
                raise ValueError("Unexpected/duplicate archive file")
            info = expected[basename]
            if member.size != info["bytes"]:
                raise ValueError("File size mismatch")
            path = target / basename
            if path.is_symlink():
                raise ValueError("Symlink output file")
            h, n = hashlib.sha256(), 0
            source = archive.extractfile(member)
            with path.open("wb") as output:
                while chunk := source.read(1024 * 1024):
                    n += len(chunk)
                    h.update(chunk)
                    output.write(chunk)
            if n != info["bytes"] or h.hexdigest() != info["sha256"]:
                raise ValueError("Internal CSV hash mismatch")
            verified.append({"file": basename, "bytes": n, "sha256": h.hexdigest()})
            print("verified", basename, flush=True)
    if internal is None or internal != manifest or len(verified) != 24:
        raise ValueError("Internal/external manifests differ or inventory incomplete")
    return manifest, members, verified, target


def checked_rows(path, kind, file_stats, declared):
    stats = {"file": path.name, "kind": kind, "declared_rows": declared, "rows": 0,
             "header_exact": False, "last_line_terminated": False, "parse_errors": 0}
    with path.open("rb") as f:
        f.seek(-1, 2)
        stats["last_line_terminated"] = f.read(1) == b"\n"
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = csv.reader(f, strict=True)
        stats["header_exact"] = next(rows) == HEADERS[kind]
        if not stats["header_exact"]:
            raise ValueError("CSV header mismatch: " + path.name)
        try:
            for values in rows:
                stats["rows"] += 1
                if len(values) != len(HEADERS[kind]):
                    stats["parse_errors"] += 1
                    raise ValueError("CSV field count mismatch: " + path.name)
                yield dict(zip(HEADERS[kind], values))
        except csv.Error:
            stats["parse_errors"] += 1
            raise
    stats["row_count_matches"] = stats["rows"] == declared
    file_stats.append(stats)
    if not stats["row_count_matches"]:
        raise ValueError("CSV row count mismatch: " + path.name)


def level_rows(text):
    rows = json.loads(text)
    if not isinstance(rows, list):
        raise ValueError("Depth side must be a JSON list")
    out = []
    for row in rows:
        if not isinstance(row, list) or len(row) != 2:
            raise ValueError("Malformed depth level")
        p, q = map(float, row)
        if not math.isfinite(p) or not math.isfinite(q) or p <= 0 or q < 0:
            raise ValueError("Invalid depth price or quantity")
        out.append((p, q))
    return out


def audit_symbol(sym, entries, target, file_stats):
    by_kind = {kind: sorted([e for e in entries if e["symbol"] == sym and e["kind"] == kind], key=lambda e:e["utc_day"]) for kind in HEADERS}
    events = []
    for e in by_kind["events"]:
        for row in checked_rows(target/e["file"], "events", file_stats, e["rows"]):
            events.append({**row, "recv_ms": int(row["recv_ms"])})
    event_source_backwards = sum(a["recv_ms"] > b["recv_ms"] for a, b in zip(events, events[1:]))
    events.sort(key=lambda r:r["recv_ms"])
    counts = collections.Counter()
    depth = {"rows": 0, "snapshots": 0, "delta_rows": 0, "applied_0": 0,
             "applied_1": 0, "applied_flag_disagreements": 0, "sequence_breaks": 0,
             "applied_1_unreplayable_without_snapshot_context": 0,
             "unreplayable_delta_rows": 0,
             "recv_backwards": 0, "event_E_backwards": 0, "nonempty_book_rows": 0,
             "crossed_or_locked_book_rows": 0, "empty_book_rows": 0,
             "max_payload_bid_levels": 0, "max_payload_ask_levels": 0,
             "max_reconstructed_bid_levels": 0, "max_reconstructed_ask_levels": 0,
             "max_recv_gap_ms": 0, "stale_gaps_over_2s": 0,
             "first_snapshot_utc": None, "last_snapshot_utc": None,
             "sessions": [], "sequence_break_examples": []}
    bid, ask, last_u = {}, {}, None
    session, ok, book_valid, previous_recv, previous_E = None, False, False, None, None
    snapshot_in_session = False
    timeline, last_depth_ms, event_index, valid_spans, stale = None, None, 0, [], []
    sequence_spans, event_sequence_spans = [], []
    freshness_spans = {5000: [], 30000: []}
    recv_gaps, event_gaps, clock_differences = collections.Counter(), collections.Counter(), collections.Counter()
    previous_depth_valid, previous_depth_session = False, None
    previous_raw_u, previous_raw_applied = None, None
    depth["raw_delta_chain_breaks_after_applied_row"] = 0
    receive_min = receive_max = event_min = event_max = None
    lag_min = lag_max = None

    def advance(ts):
        nonlocal timeline
        if timeline is not None and ts >= timeline and book_valid and last_depth_ms is not None:
            merge_span(valid_spans, timeline, min(ts, last_depth_ms + STALE_AFTER_MS))
            merge_span(sequence_spans, timeline, ts)
            for limit, spans in freshness_spans.items():
                merge_span(spans, timeline, min(ts, last_depth_ms+limit))
        timeline = ts

    def apply_event(row):
        nonlocal ok, book_valid, last_u, session, snapshot_in_session
        advance(row["recv_ms"])
        counts[row["event"]] += 1
        if row["event"] in {"connect", "disconnect", "gap", "resync"}:
            ok, book_valid, last_u = False, False, None
            bid.clear(); ask.clear()
            session = row["session"]
            if row["event"] in {"connect", "disconnect"}:
                snapshot_in_session = False

    for e in by_kind["depth"]:
        for row in checked_rows(target/e["file"], "depth", file_stats, e["rows"]):
            depth["rows"] += 1
            recv, E = int(row["recv_ms"]), int(row["E"])
            reset_between = False
            while event_index < len(events) and events[event_index]["recv_ms"] <= recv:
                reset_between |= events[event_index]["event"] in {"connect", "disconnect", "gap", "resync"}
                apply_event(events[event_index]); event_index += 1
            if previous_recv is not None:
                gap = recv - previous_recv
                recv_gaps[gap] += 1
                event_gaps[E-previous_E] += 1
                depth["max_recv_gap_ms"] = max(depth["max_recv_gap_ms"], gap)
                if gap < 0:
                    depth["recv_backwards"] += 1
                    ok, book_valid, last_u = False, False, None
                if gap > STALE_AFTER_MS:
                    depth["stale_gaps_over_2s"] += 1
                    stale.append([previous_recv+STALE_AFTER_MS, recv])
            if previous_E is not None and E < previous_E:
                depth["event_E_backwards"] += 1
            advance(recv)
            if row["session"] != session:
                ok, book_valid, last_u = False, False, None
                bid.clear(); ask.clear()
                session = row["session"]
                snapshot_in_session = False
            if session not in depth["sessions"]:
                depth["sessions"].append(session)
            br, ar = level_rows(row["b"]), level_rows(row["a"])
            depth["max_payload_bid_levels"] = max(depth["max_payload_bid_levels"], len(br))
            depth["max_payload_ask_levels"] = max(depth["max_payload_ask_levels"], len(ar))
            u = int(row["u"])
            flag = int(row["applied"])
            if flag not in (0, 1):
                raise ValueError("Invalid applied flag")
            depth["applied_"+str(flag)] += 1
            if row["kind"] == "snapshot":
                depth["snapshots"] += 1
                depth["first_snapshot_utc"] = depth["first_snapshot_utc"] or iso(recv)
                depth["last_snapshot_utc"] = iso(recv)
                bid, ask = {p:q for p,q in br if q > 0}, {p:q for p,q in ar if q > 0}
                last_u, ok, calculated_applied = u, True, 1
                snapshot_in_session = True
            elif row["kind"] == "delta":
                depth["delta_rows"] += 1
                U = int(row["U"])
                if previous_depth_session == session and previous_raw_applied == 1 and previous_raw_u is not None and U != previous_raw_u:
                    depth["raw_delta_chain_breaks_after_applied_row"] += 1
                calculated_applied = int(ok and last_u is not None and U == last_u)
                if calculated_applied:
                    for side, values in ((bid, br), (ask, ar)):
                        for p,q in values:
                            if q > 0: side[p] = q
                            else: side.pop(p, None)
                    last_u = u
                else:
                    depth["unreplayable_delta_rows"] += 1
                    depth["sequence_breaks"] += int(last_u is not None and U != last_u)
                    if len(depth["sequence_break_examples"]) < 10:
                        depth["sequence_break_examples"].append({"recv_utc": iso(recv), "U": U, "previous_u": last_u, "recorded_applied": flag})
                    ok = False
            else:
                raise ValueError("Unknown depth kind")
            if calculated_applied != flag:
                if flag == 1 and not snapshot_in_session:
                    depth["applied_1_unreplayable_without_snapshot_context"] += 1
                else:
                    depth["applied_flag_disagreements"] += 1
            # Never rehabilitate a recorder-rejected delta, even if its IDs look usable.
            if flag == 0:
                ok = False
            depth["max_reconstructed_bid_levels"] = max(depth["max_reconstructed_bid_levels"], len(bid))
            depth["max_reconstructed_ask_levels"] = max(depth["max_reconstructed_ask_levels"], len(ask))
            empty = not bid or not ask
            crossed = not empty and max(bid) >= min(ask)
            if empty: depth["empty_book_rows"] += 1
            elif crossed: depth["crossed_or_locked_book_rows"] += 1
            else: depth["nonempty_book_rows"] += 1
            book_valid = ok and flag == 1 and not empty and not crossed
            if previous_depth_valid and book_valid and not reset_between and previous_depth_session == session and E >= previous_E:
                merge_span(event_sequence_spans, previous_E, E)
            timeline, last_depth_ms = recv, recv
            previous_recv, previous_E = recv, E
            receive_min = recv if receive_min is None else min(receive_min, recv)
            receive_max = recv if receive_max is None else max(receive_max, recv)
            event_min = E if event_min is None else min(event_min, E)
            event_max = E if event_max is None else max(event_max, E)
            lag = recv - E
            clock_differences[lag] += 1
            lag_min = lag if lag_min is None else min(lag_min, lag)
            lag_max = lag if lag_max is None else max(lag_max, lag)
            previous_depth_valid, previous_depth_session = book_valid, session
            previous_raw_u, previous_raw_applied = u, flag
    # The last quote is not extrapolated beyond the last captured depth message.
    while event_index < len(events) and events[event_index]["recv_ms"] <= receive_max:
        apply_event(events[event_index]); event_index += 1
    depth.update({"first_recv_utc": iso(receive_min), "last_recv_utc": iso(receive_max),
                  "first_event_E_utc": iso(event_min), "last_event_E_utc": iso(event_max),
                  "recv_minus_E_ms_min": lag_min, "recv_minus_E_ms_max": lag_max,
                  "clock_difference_is_not_provider_lag": True,
                  "valid_span_count": len(valid_spans), "sequence_only_span_count": len(sequence_spans),
                  "receive_gap_ms": quantiles(recv_gaps), "exchange_E_gap_ms": quantiles(event_gaps),
                  "recv_minus_E_ms_distribution": quantiles(clock_differences),
                  "same_millisecond_receive_pairs": recv_gaps[0]})

    trades = {"rows": 0, "missing_id_rows": 0, "duplicate_id_rows": 0, "duplicate_examples": [],
              "nonpositive_or_nonfinite_price_quantity_rows": 0, "recv_backwards": 0,
              "T_backwards": 0, "T_backwards_with_same_E_recv_session": 0,
              "max_recv_gap_ms": 0, "m_raw_values": {}, "sessions": []}
    seen, m_values = set(), collections.Counter()
    previous_recv = previous_T = previous_trade_E = previous_trade_session = trade_min = trade_max = recv_min = recv_max = None
    for e in by_kind["trades2"]:
        for row in checked_rows(target/e["file"], "trades2", file_stats, e["rows"]):
            trades["rows"] += 1
            tid = row["t"]
            if not tid: trades["missing_id_rows"] += 1
            if tid in seen:
                trades["duplicate_id_rows"] += 1
                if len(trades["duplicate_examples"]) < 10:
                    trades["duplicate_examples"].append({"id": tid, "T": row["T"], "session": row["session"]})
            seen.add(tid)
            T, E, recv = int(row["T"]), int(row["E"]), int(row["recv_ms"])
            p, q = float(row["p"]), float(row["q"])
            if not math.isfinite(p) or not math.isfinite(q) or p <= 0 or q <= 0:
                trades["nonpositive_or_nonfinite_price_quantity_rows"] += 1
            if previous_recv is not None:
                trades["recv_backwards"] += int(recv < previous_recv)
                trades["max_recv_gap_ms"] = max(trades["max_recv_gap_ms"], recv-previous_recv)
                trades["T_backwards"] += int(T < previous_T)
                trades["T_backwards_with_same_E_recv_session"] += int(T < previous_T and E == previous_trade_E and recv == previous_recv and row["session"] == previous_trade_session)
            previous_recv, previous_T = recv, T
            previous_trade_E, previous_trade_session = E, row["session"]
            trade_min = T if trade_min is None else min(trade_min, T)
            trade_max = T if trade_max is None else max(trade_max, T)
            recv_min = recv if recv_min is None else min(recv_min, recv)
            recv_max = recv if recv_max is None else max(recv_max, recv)
            m_values[row["m_raw"]] += 1
            if row["session"] not in trades["sessions"]: trades["sessions"].append(row["session"])
    trades.update({"unique_trade_ids": len(seen), "first_T_utc": iso(trade_min), "last_T_utc": iso(trade_max),
                   "first_recv_utc": iso(recv_min), "last_recv_utc": iso(recv_max), "m_raw_values": dict(m_values),
                   "trade_message_batch_id_not_recorded": True,
                   "aggressor_semantics_independently_verified": False,
                   "trade_id_gaps_do_not_establish_missing_trades": True,
                   "full_trade_feed_completeness_not_proven": True})
    windows = {}
    for day in ("2026-10-16", "2026-10-17"):
        a = epoch(day+"T00:00:00")
        b = a+86400000
        good = clip(valid_spans, a, b)
        missing = complement(valid_spans, a, b)
        post = clip(valid_spans, b, b+1800000)
        windows[day] = {"clock": "unverified recorder receive clock, UTC", "requested_ms": b-a,
            "valid_depth_ms": sum(y-x for x,y in good), "valid_fraction": sum(y-x for x,y in good)/(b-a),
            "valid_span_count": len(good), "exclusions": pretty_spans(missing),
            "max_valid_contiguous_ms": max((y-x for x,y in good), default=0),
            "start_prewarmed": any(x <= a < y for x,y in sequence_spans),
            "start_receive_silence_under_2s": any(x <= a < y for x,y in valid_spans),
            "following_30min_valid_ms": sum(y-x for x,y in post),
            "following_30min_fully_valid": sum(y-x for x,y in post) == 1800000,
            "uninterrupted_full_utc_day": sum(y-x for x,y in good) == b-a,
            "sequence_only_valid_ms": sum(y-x for x,y in clip(sequence_spans, a, b)),
            "sequence_only_exclusions": pretty_spans(complement(sequence_spans, a, b)),
            "sequence_only_following_30min_valid_ms": sum(y-x for x,y in clip(sequence_spans,b,b+1800000)),
            "freshness_sensitivity_valid_ms": {str(limit):sum(y-x for x,y in clip(spans,a,b)) for limit,spans in freshness_spans.items()},
            "exchange_event_E_sequence_ms": sum(y-x for x,y in clip(event_sequence_spans,a,b)),
            "exchange_event_E_sequence_exclusions": pretty_spans(complement(event_sequence_spans,a,b)),
            "exchange_event_E_is_not_receive_time_coverage": True}
    return {"symbol": sym, "events": {"rows": len(events), "counts": dict(collections.Counter(r["event"] for r in events)),
        "receive_time_backwards_in_source_order": event_source_backwards,
        "timeline": [{"recv_utc": iso(r["recv_ms"]), "session": r["session"], "event": r["event"], "detail": r["detail"]} for r in events]},
        "depth": depth, "trades": trades, "primary_windows": windows,
        "valid_depth_spans": pretty_spans(valid_spans), "sequence_only_spans": pretty_spans(sequence_spans),
        "exchange_event_E_sequence_spans": pretty_spans(event_sequence_spans), "stale_gaps": pretty_spans(stale)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-root", type=Path, default=Path(__file__).parent/"local")
    parser.add_argument("--out-root", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    args.out_root.mkdir(parents=True, exist_ok=True)
    manifest, members, verified, target = extract_verified(args.local_root)
    stats, symbols = [], []
    for sym in ("BTCUSDT", "ETHUSDT"):
        print("audit", sym, flush=True)
        symbols.append(audit_symbol(sym, manifest["files"], target, stats))
    report = {"schema": "weex-public-replay-quality-v1", "created_utc": datetime.now(timezone.utc).isoformat(),
        "release_url": "https://github.com/alexey-chechikov/chat-bot-v2/releases/tag/data-weex-book-20261015-20261018",
        "archive": {"file": ARCHIVE, "bytes": (args.local_root/ARCHIVE).stat().st_size, "sha256": ARCHIVE_SHA, "hash_verified": True},
        "external_manifest": {"file": MANIFEST, "sha256": MANIFEST_SHA, "hash_verified": True},
        "internal_manifest_equals_external": True, "all_24_internal_csv_hashes_verified": True,
        "safe_stream_extraction": True, "archive_members": members, "verified_files": verified,
        "csv_files": sorted(stats, key=lambda r:r["file"]), "symbols": symbols,
        "recorder_commit_declared": manifest["recorder_commit"],
        "quality_policy": {"max_time_since_last_received_depth_ms": STALE_AFTER_MS, "sequence": "U == previous u, recorder applied=0 always excluded; snapshot required after session/event reset",
            "resets": ["connect", "disconnect", "gap", "resync", "session change", "sequence break"],
            "coverage_clock": "recorder receive clock (accuracy not measured); no inferred provider lag", "last_quote_extrapolated": False,
            "invalid_rows_preserved_in_raw": True, "two_days_are_not_two_independent_market_regimes": True},
        "limitations": ["No exchange confirmation of contract quantity unit/multiplier, tick or quantity step; exported specs came from bot configs.",
            "m_raw buyer-is-maker interpretation is declared by recorder but not independently confirmed in this audit.",
            "Depth15 is partial L2, not an order-level queue. No order acknowledgements, cancellations or queue position are observed.",
            "Capture connection windows and valid depth do not prove a complete trades census.",
            "Receive clock NTP error is unmeasured; receive minus exchange timestamp mixes clock difference and transport.",
            "The 2/5/30-second receive-silence tests limit time since a depth row arrived, not the true age of its market state; buffered rows may already describe an older market.",
            "Messages arrive in bursts, with substantial receive-time silence even when exchange E advances regularly. Event-time continuity is not executable receive-time freshness.",
            "No global receive ordinal/message batch identifier is stored. Cross-stream ties and exchange-time ordering within recorded trade batches cannot be resolved into an observed execution queue.",
            "Day 18 is an intraday copy while capture continued; end-of-file is administrative censoring, not a disconnect.",
            "No new fills, probabilities, trading/PnL result or live-state/deployment verification is calculated."]}
    (args.local_root/"quality_details.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    public_report = copy.deepcopy(report)
    public_report["full_interval_details_local_only"] = "local/quality_details.json"
    for symbol in public_report["symbols"]:
        symbol.pop("valid_depth_spans")
        stale = symbol.pop("stale_gaps")
        symbol["largest_10_stale_gaps"] = sorted(stale, key=lambda x:x["duration_ms"], reverse=True)[:10]
        for window in symbol["primary_windows"].values():
            exclusions = window.pop("exclusions")
            window["freshness_2s_exclusion_count"] = len(exclusions)
            window["largest_10_freshness_2s_exclusions"] = sorted(exclusions,key=lambda x:x["duration_ms"],reverse=True)[:10]
    (args.out_root/"report.json").write_text(json.dumps(public_report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    lines = ["# WEEX public replay: finite quality audit", "", "This is a data-quality result, not a maker-profitability result.", "",
        "Both Release asset SHA256 values and all 24 internal CSV hashes match. Internal and external manifests are identical. CSV schemas, row counts and newline termination were checked. Raw files remain local.", "",
        "| Symbol | UTC day | Sequence coverage, receive clock | Receive silence <=2s | <=5s | <=30s | Start snapshot prewarmed |", "|---|---|---:|---:|---:|---:|---|"]
    for s in symbols:
        for day,w in s["primary_windows"].items():
            lines.append(f"| {s['symbol']} | {day} | {w['sequence_only_valid_ms']/86400000:.8%} | {w['valid_fraction']:.8%} | {w['freshness_sensitivity_valid_ms']['5000']/86400000:.8%} | {w['freshness_sensitivity_valid_ms']['30000']/86400000:.8%} | {w['start_prewarmed']} |")
    lines += ["", "Sequence coverage is structural book availability between valid snapshot/updates and resets. It does not establish current quotes. Receive-silence columns additionally exclude quotes after 2/5/30 seconds without another depth update; these are explicit audit sensitivities, not exchange SLAs, true market-state age, or percentages of lost exchange messages. Buffered rows may already be old when received. Connection failures and a missing initial snapshot are excluded independently. report.json has compact exclusions and clock distributions; full intervals are local/quality_details.json only.", "", "| Symbol | Depth rows | Applied=0 | Sequence/replay disagreements | Crossed/locked rows | Trades | Duplicate IDs |", "|---|---:|---:|---:|---:|---:|---:|"]
    for s in symbols:
        d,t=s["depth"],s["trades"]
        lines.append(f"| {s['symbol']} | {d['rows']} | {d['applied_0']} | {d['applied_flag_disagreements']} | {d['crossed_or_locked_book_rows']} | {t['rows']} | {t['duplicate_id_rows']} |")
    lines += ["", "## Receive timing and event ordering", ""]
    for s in symbols:
        d,t=s["depth"],s["trades"]
        lines += [f"- {s['symbol']}: receive-gap p50/p95/p99/max = {d['receive_gap_ms']['p50']}/{d['receive_gap_ms']['p95']}/{d['receive_gap_ms']['p99']}/{d['receive_gap_ms']['max']} ms; recv minus E min/median/p99/max = {d['recv_minus_E_ms_distribution']['min']}/{d['recv_minus_E_ms_distribution']['p50']}/{d['recv_minus_E_ms_distribution']['p99']}/{d['recv_minus_E_ms_distribution']['max']} ms. This combines transport/backlog and unmeasured clocks; it is not provider lag.",
            f"- {s['symbol']}: {t['T_backwards']} trade timestamp decreases, {t['T_backwards_with_same_E_recv_session']} with identical E/recv/session. Preserve source order and availability; do not globally sort by trade T and pretend earlier availability. The initial {d['applied_1_unreplayable_without_snapshot_context']} applied rows cannot be replayed without the missing pre-export snapshot; first available snapshot {d['first_snapshot_utc']}."]
    lines += ["", "## Limits before maker replay", ""] + ["- "+x for x in report["limitations"]]
    lines += ["", "## Reproduce (Python standard library, offline)", "", "Download the two pinned assets from the linked Release into local/ using the approved public download path. Run:", "", "```text", "python -X utf8 -B verify_replay.py --local-root local --out-root .", "python -X utf8 -B -m unittest -v test_verify_replay", "```", "", "No production imports, Mac access, API calls, account access or model fitting are performed by the verifier. Synthetic tests cover gaps/resync, stale quotes, cross-day prewarm, missing snapshot, invalid level values and interval boundaries."]
    (args.out_root/"README.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print("DONE", str(args.out_root/"report.json"), flush=True)


if __name__ == "__main__":
    main()
