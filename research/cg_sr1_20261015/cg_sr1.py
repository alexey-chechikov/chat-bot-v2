"""CG-SR1 v0: pure, offline, idealized OHLC research simulator.

No network, exchange client, collector, account access or order submission.
All arithmetic uses Decimal; timestamps are UTC bar opens in milliseconds.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
import hashlib
from io import StringIO
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

MINUTE = 60_000
M15 = 15 * MINUTE
SLOT = 6 * 60 * MINUTE
HORIZON = 240 * MINUTE
SERIES = "CG-model1-Binance-BTCUSDT-24h-ui085-forward-v2"
VERSION = "CG-SR1-v0-offline-0.1"
RESERVE = Decimal("0.0008")
RISK = Decimal("25")
CAPITAL = Decimal("10000")


class ValidationError(ValueError):
    """Input cannot establish the declared normalized research contract."""


def number(value: Any, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValidationError(f"{field}: expected finite decimal")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValidationError(f"{field}: expected finite decimal") from exc
    if not result.is_finite():
        raise ValidationError(f"{field}: expected finite decimal")
    return result


def timestamp(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationError(f"{field}: expected nonnegative integer UTC milliseconds")
    return value


def floor_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def ceil_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_CEILING) * step


def effective_t0(capture_ms: int, annotation_lock_ms: int) -> int:
    return (max(capture_ms, annotation_lock_ms) // MINUTE + 1) * MINUTE


@dataclass(frozen=True)
class Bar:
    ts: int
    o: Decimal
    h: Decimal
    l: Decimal
    c: Decimal


def parse_bars(rows: Iterable[Mapping[str, Any]], as_of: int, tick: Decimal) -> dict[int, Bar]:
    bars: dict[int, Bar] = {}
    previous = -1
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValidationError("price row must be a mapping")
        ts = timestamp(row.get("ts_ms"), "price.ts_ms")
        if ts % MINUTE or ts <= previous:
            raise ValidationError("price rows must be unique, increasing UTC 1m opens")
        if ts + MINUTE > as_of:
            raise ValidationError("price row is not closed at metadata.data_as_of_ms")
        values = [number(row.get(key), f"price.{key}") for key in ("open", "high", "low", "close")]
        o, h, l, c = values
        if any(v <= 0 or v % tick for v in values):
            raise ValidationError("OHLC prices must be positive and on the declared tick grid")
        if l > min(o, c) or h < max(o, c) or l > h:
            raise ValidationError("inconsistent OHLC range")
        bars[ts] = Bar(ts, o, h, l, c)
        previous = ts
    return bars


def aggregate_15m(bars: Mapping[int, Bar]) -> dict[int, Bar]:
    """Only full UTC-aligned groups; no resampling across missing minutes."""
    if not bars:
        return {}
    first, last = min(bars) // M15 * M15, max(bars) // M15 * M15
    result = {}
    for start in range(first, last + M15, M15):
        rows = [bars.get(ts) for ts in range(start, start + M15, MINUTE)]
        if all(row is not None for row in rows):
            result[start] = Bar(start, rows[0].o, max(r.h for r in rows), min(r.l for r in rows), rows[-1].c)
    return result


def previous_atr14(bars15: Mapping[int, Bar], seed_start_ms: int) -> dict[int, Decimal]:
    """Map decision time -> ATR using bars closing at or before that time.

    Seed with the arithmetic mean of 14 TRs, each using a real prior close:
    15 complete consecutive bars are needed. Then Wilder (13*ATR+TR)/14.
    A gap invalidates the fixed seed path: no reset/reseed after missing data.
    """
    result: dict[int, Decimal] = {}
    previous: Bar | None = None
    seed: list[Decimal] = []
    atr: Decimal | None = None
    if not bars15:
        return result
    for ts in range(seed_start_ms, max(bars15) + M15, M15):
        bar = bars15.get(ts)
        if bar is None:
            break
        if previous is not None:
            tr = max(bar.h - bar.l, abs(bar.h - previous.c), abs(bar.l - previous.c))
            if atr is None:
                seed.append(tr)
                if len(seed) == 14:
                    atr = sum(seed) / Decimal(14)
            else:
                atr = (Decimal(13) * atr + tr) / Decimal(14)
        if atr is not None:
            result[ts + M15] = atr
        previous = bar
    return result


def validate_metadata(meta: Mapping[str, Any], synthetic: bool) -> tuple[Decimal, Decimal, int, int]:
    if not isinstance(meta, Mapping):
        raise ValidationError("metadata must be an object")
    expected = {"schema_version": "cg-sr1-input-v0", "series_id": SERIES,
                "collection_role": "prospective-forward-v2", "provider": "CoinGlass",
                "model": "model1", "exchange": "Binance", "symbol": "BTCUSDT",
                "instrument": "perpetual", "lookback": "24h"}
    for key, value in expected.items():
        if meta.get(key) != value:
            raise ValidationError(f"metadata.{key}: expected {value!r}; pilot/reference inputs are forbidden")
    if meta.get("synthetic") is not synthetic:
        raise ValidationError("--synthetic and metadata.synthetic must match explicitly")
    if number(meta.get("threshold"), "threshold") != Decimal("0.85"):
        raise ValidationError("threshold must be exactly 0.85")
    source = meta.get("price_source", {})
    if not isinstance(source, Mapping):
        raise ValidationError("price_source must be an object")
    for key, value in {"exchange": "Binance", "symbol": "BTCUSDT", "instrument": "perpetual",
                       "interval": "1m", "timezone": "UTC", "closed_only": True}.items():
        if source.get(key) != value or (key == "closed_only" and source.get(key) is not True):
            raise ValidationError(f"price_source.{key}: expected {value!r}")
    contract = meta.get("contract", {})
    if not isinstance(contract, Mapping):
        raise ValidationError("contract must be an object")
    if contract.get("verified") is not True or not isinstance(contract.get("verification_source"), str) or not contract["verification_source"].strip():
        raise ValidationError("contract requires an explicit verified tick/step source declaration")
    tick, step = number(contract.get("tick_size"), "tick_size"), number(contract.get("quantity_step"), "quantity_step")
    if tick <= 0 or step <= 0:
        raise ValidationError("tick and quantity step must be positive")
    verified_at = timestamp(contract.get("verified_at_ms"), "contract.verified_at_ms")
    as_of = timestamp(meta.get("data_as_of_ms"), "data_as_of_ms")
    seed = timestamp(meta.get("atr_seed_start_ms"), "atr_seed_start_ms")
    if seed % M15:
        raise ValidationError("ATR seed must be a UTC 15m open")
    if seed >= as_of:
        raise ValidationError("ATR seed must precede data_as_of_ms")
    if verified_at > as_of:
        raise ValidationError("contract verification timestamp is after data_as_of_ms")
    return tick, step, as_of, seed


def normalize_snapshot(row: Mapping[str, Any], synthetic: bool) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise ValidationError("snapshot must be an object")
    sid = row.get("snapshot_id")
    if not isinstance(sid, str) or not sid.strip():
        raise ValidationError("snapshot_id must be a nonempty immutable identifier")
    if row.get("series_id") != SERIES or row.get("synthetic") is not synthetic:
        raise ValidationError("snapshot series/synthetic marker mismatch; pilot/reference inputs are forbidden")
    slot = timestamp(row.get("slot_ms"), "snapshot.slot_ms")
    if slot % SLOT:
        raise ValidationError("snapshot.slot_ms must be UTC 00/06/12/18")
    output = {"snapshot_id": sid, "slot_ms": slot, "status": "SKIPPED", "reasons": []}
    if row.get("status") == "missed":
        if not isinstance(row.get("reason"), str) or not row["reason"].strip():
            raise ValidationError("a missed attempt requires a recorded reason")
        output.update(reasons=["OBSERVATION_MISSED"], observation_reason=row["reason"])
        return output
    if row.get("status") != "frozen":
        raise ValidationError("snapshot.status must be frozen or missed")
    capture = timestamp(row.get("capture_ms"), "capture_ms")
    lock = timestamp(row.get("annotation_lock_ms"), "annotation_lock_ms")
    freeze = max(capture, lock)
    t0 = effective_t0(capture, lock)
    output.update(freeze_ms=freeze, t0_ms=t0, deadline_ms=t0 + HORIZON)
    if capture < slot or freeze > slot + 2 * MINUTE:
        output["reasons"].append("FREEZE_OUTSIDE_SLOT_WINDOW")
    for key, reason in (("source_record_complete", "SOURCE_INCOMPLETE"),
                        ("source_record_fresh", "SOURCE_NOT_FRESH"),
                        ("settings_match", "SETTINGS_UNVERIFIED"),
                        ("annotation_frozen", "ANNOTATION_NOT_FROZEN")):
        if row.get(key) is not True:
            output["reasons"].append(reason)
    zones = []
    for key in ("lower_zone", "upper_zone"):
        zone = row.get(key)
        if not isinstance(zone, Mapping) or "low" not in zone or "high" not in zone:
            output["reasons"].append("MISSING_FROZEN_ZONE")
            continue
        low, high = number(zone["low"], key + ".low"), number(zone["high"], key + ".high")
        zones.append((low, high))
    spot = number(row.get("frozen_spot"), "frozen_spot")
    if len(zones) == 2:
        lower, upper = zones
        if not (0 < lower[0] < lower[1] < spot < upper[0] < upper[1]):
            output["reasons"].append("INVALID_FROZEN_ZONE_GEOMETRY")
        output.update(lower_zone=lower, upper_zone=upper, frozen_spot=spot)
    output["reasons"] = list(dict.fromkeys(output["reasons"]))
    return output


def first_candidate(snapshot: dict[str, Any], bars: Mapping[int, Bar], bars15: Mapping[int, Bar],
                    atrs: Mapping[int, Decimal], tick: Decimal, step: Decimal,
                    contract_verified_at_ms: int | None = None) -> dict[str, Any]:
    result = dict(snapshot)
    result["reasons"] = list(snapshot["reasons"])
    start = (snapshot["t0_ms"] + M15 - 1) // M15 * M15
    deadline = snapshot["deadline_ms"]
    lower, upper = snapshot["lower_zone"], snapshot["upper_zone"]
    while start + M15 < deadline:
        bar = bars15.get(start)
        if bar is None:
            result.update(status="CENSORED", reasons=["MISSING_SIGNAL_DATA"], missing_at_ms=start)
            return result
        # Unknown intrabar order across both frozen zones consumes this snapshot.
        if bar.l <= lower[1] and bar.h >= upper[0]:
            result.update(reasons=["BOTH_ZONES_IN_SIGNAL_BAR"], signal_start_ms=start,
                          signal_close_ms=start + M15)
            return result
        side = 1 if bar.l < lower[0] and bar.c > lower[1] else (-1 if bar.h > upper[1] and bar.c < upper[0] else 0)
        if not side:
            start += M15
            continue
        entry_ts = start + M15
        result.update(signal_start_ms=start, signal_close_ms=entry_ts, entry_ms=entry_ts,
                      side="LONG" if side == 1 else "SHORT")
        if contract_verified_at_ms is not None and contract_verified_at_ms > entry_ts:
            result.update(reasons=["CONTRACT_RULES_NOT_AVAILABLE_AT_ENTRY"])
            return result
        atr = atrs.get(start)
        if atr is None:
            result.update(reasons=["MISSING_PREVIOUS_ATR14"])
            return result
        result["previous_atr14"] = atr
        entry_bar = bars.get(entry_ts)
        if entry_bar is None:
            result.update(status="CENSORED", reasons=["MISSING_ENTRY_OPEN"])
            return result
        entry = entry_bar.o
        stop_raw = bar.l - atr / Decimal(10) if side == 1 else bar.h + atr / Decimal(10)
        stop = floor_step(stop_raw, tick) if side == 1 else ceil_step(stop_raw, tick)
        target = upper[0] if side == 1 else lower[1]
        result.update(entry=entry, stop=stop, stop_unrounded=stop_raw, target=target)
        if stop <= 0 or side * (entry - stop) <= 0 or side * (target - entry) <= 0:
            result.update(reasons=["INVALID_SIGNED_TRADE_GEOMETRY"])
            return result
        if target % tick:
            result.update(reasons=["TARGET_NOT_ON_TICK_GRID"])
            return result
        distance, gain = abs(entry - stop), abs(target - entry)
        rr = (gain - RESERVE * entry) / (distance + RESERVE * entry)
        q = floor_step(min(RISK / (distance + RESERVE * entry), CAPITAL / entry), step)
        result.update(net_rr_reserve8bp=rr, quantity=q, entry_notional=q * entry,
                      planned_loss_including_reserve=q * (distance + RESERVE * entry))
        if rr < 2:
            result.update(reasons=["NET_RR_BELOW_2"])
        elif q <= 0:
            result.update(reasons=["QUANTITY_ROUNDED_TO_ZERO"])
        else:
            result.update(status="READY", reasons=[])
        return result
    result.update(reasons=["NO_RECLAIM_BEFORE_DEADLINE"])
    return result


def simulate_exit(trade: Mapping[str, Any], bars: Mapping[int, Bar]) -> dict[str, Any]:
    """Idealized 1m OHLC; known open precedes unordered high/low."""
    side = 1 if trade["side"] == "LONG" else -1
    stop, target = trade["stop"], trade["target"]
    for ts in range(trade["entry_ms"], trade["deadline_ms"] + MINUTE, MINUTE):
        bar = bars.get(ts)
        if bar is None:
            reason = "MISSING_DEADLINE_OPEN" if ts == trade["deadline_ms"] else "MISSING_EXIT_PATH"
            return {"status": "CENSORED", "reasons": [reason], "missing_at_ms": ts,
                    "exit_ms": None, "exit": None, "exit_phase": None, "exit_reason": None}
        if side * (bar.o - stop) <= 0:
            price, reason, phase = bar.o, "STOP_GAP_OPEN", "open"
        elif side * (bar.o - target) >= 0:
            # Conservative limit-target assumption: no favorable gap improvement.
            price, reason, phase = target, "TARGET_GAP_OPEN_CAPPED", "open"
        elif ts == trade["deadline_ms"]:
            # Standing protection/limit target still apply at this known open.
            # Only an open between both barriers becomes a time exit.
            return {"status": "CLOSED", "reasons": [], "exit_ms": ts, "exit": bar.o,
                    "exit_phase": "open", "exit_reason": "DEADLINE"}
        else:
            stop_hit = bar.l <= stop if side == 1 else bar.h >= stop
            target_hit = bar.h >= target if side == 1 else bar.l <= target
            if stop_hit:
                price, reason, phase = stop, "STOP_BOTH_TOUCHED" if target_hit else "STOP", "intrabar"
            elif target_hit:
                price, reason, phase = target, "TARGET", "intrabar"
            else:
                continue
        return {"status": "CLOSED", "reasons": [], "exit_ms": ts, "exit": price,
                "exit_phase": phase, "exit_reason": reason}
    raise AssertionError("unreachable deadline")


def serializable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: serializable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [serializable(item) for item in value]
    return value


def apply_portfolio(results: list[dict[str, Any]], bars: Mapping[int, Bar]) -> list[dict[str, Any]]:
    """Apply one-position policy to internal candidate copies and return entered ledger.

    Intrabar exits release capacity at the next minute open. Known-open exits
    release at that open. Unknown execution blocks subsequent capacity claims.
    Normally 6h slots/4h episodes cannot overlap; unit tests also exercise
    competing internal candidates so the invariant does not rely on spacing.
    """
    # Candidate order is independent of file order. Freeze/id break simultaneous entries.
    ready = sorted((row for row in results if row["status"] == "READY"),
                   key=lambda row: (row["entry_ms"], row["freeze_ms"], row["snapshot_id"]))
    busy_until = -1
    unknown_from: int | None = None
    ledger = []
    for candidate in ready:
        if unknown_from is not None:
            candidate.update(status="SKIPPED", reasons=["PORTFOLIO_STATE_UNKNOWN" if candidate["entry_ms"] >= unknown_from else "PORTFOLIO_BUSY"])
            continue
        if candidate["entry_ms"] < busy_until:
            candidate.update(status="SKIPPED", reasons=["PORTFOLIO_BUSY"])
            continue
        outcome = simulate_exit(candidate, bars)
        candidate.update(outcome)
        candidate["entered"] = True
        if candidate["status"] == "CENSORED":
            unknown_from = candidate["missing_at_ms"]
            candidate.update(raw_gross=None, all_in_cost_4bp=None, all_in_cost_8bp=None,
                             net_4bp=None, net_8bp=None)
        else:
            busy_until = candidate["exit_ms"] + (MINUTE if candidate["exit_phase"] == "intrabar" else 0)
            side = 1 if candidate["side"] == "LONG" else -1
            gross = side * (candidate["exit"] - candidate["entry"]) * candidate["quantity"]
            cost4, cost8 = candidate["entry_notional"] * Decimal("0.0004"), candidate["entry_notional"] * RESERVE
            candidate.update(raw_gross=gross, all_in_cost_4bp=cost4, all_in_cost_8bp=cost8,
                             net_4bp=gross - cost4, net_8bp=gross - cost8)
        ledger.append(dict(candidate))
    return ledger


def run_research(metadata: Mapping[str, Any], snapshots: Iterable[Mapping[str, Any]],
                 price_rows: Iterable[Mapping[str, Any]], *, synthetic: bool = False) -> dict[str, Any]:
    """Pure function; no I/O or mutation of caller inputs. Returns JSON-compatible data."""
    tick, step, as_of, seed = validate_metadata(metadata, synthetic)
    bars = parse_bars(price_rows, as_of, tick)
    bars15 = aggregate_15m(bars)
    atrs = previous_atr14(bars15, seed)
    normalized = [normalize_snapshot(row, synthetic) for row in snapshots]
    ids = [row["snapshot_id"] for row in normalized]
    if len(set(ids)) != len(ids):
        raise ValidationError("duplicate immutable snapshot_id")
    normalized.sort(key=lambda row: (row["slot_ms"], row.get("freeze_ms", row["slot_ms"]), row["snapshot_id"]))
    chosen_slots: set[int] = set()
    results = []
    for snapshot in normalized:
        if snapshot["slot_ms"] > as_of:
            snapshot["reasons"].append("OBSERVATION_AFTER_DATA_AS_OF")
        if snapshot.get("freeze_ms", 0) > as_of:
            snapshot["reasons"].append("FREEZE_AFTER_DATA_AS_OF")
        if not snapshot["reasons"]:
            if snapshot["slot_ms"] in chosen_slots:
                snapshot["reasons"] = ["LATER_FREEZE_FOR_SLOT"]
            else:
                chosen_slots.add(snapshot["slot_ms"])
                if as_of < snapshot["deadline_ms"] + MINUTE:
                    # v0 evaluates only mature episodes. Closed-only CSV needs
                    # the deadline minute itself closed to supply its open.
                    snapshot.update(status="PENDING", reasons=["EPISODE_NOT_MATURE"])
                else:
                    snapshot = first_candidate(snapshot, bars, bars15, atrs, tick, step,
                                               metadata["contract"]["verified_at_ms"])
        results.append(snapshot)
    ledger = apply_portfolio(results, bars)
    counts = Counter(reason for row in results for reason in row["reasons"])
    report = {"version": VERSION, "series_id": SERIES, "synthetic": synthetic,
              "model": "idealized closed-1m OHLC, not maker fills; price only; no spot filter",
              "fixed_comparison_capital": CAPITAL, "risk_budget": RISK, "size_rr_reserve": RESERVE,
              "snapshot_count": len(results), "entered_count": len(ledger),
              "closed_count": sum(row["status"] == "CLOSED" for row in ledger),
              "pending_count": sum(row["status"] == "PENDING" for row in results),
              "censored_count": sum(row["status"] == "CENSORED" for row in results),
              "reason_counts": dict(sorted(counts.items())), "snapshots": results,
              "ledger_4bp": [dict(row, all_in_rate=Decimal("0.0004"), net=row["net_4bp"]) for row in ledger],
              "ledger_8bp": [dict(row, all_in_rate=RESERVE, net=row["net_8bp"]) for row in ledger]}
    return serializable(report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--snapshots", required=True, type=Path, help="JSON array of normalized frozen/missed records")
    parser.add_argument("--prices", required=True, type=Path, help="closed 1m CSV: ts_ms,open,high,low,close")
    parser.add_argument("--output", required=True, type=Path, help="new output JSON path; existing files are never overwritten")
    parser.add_argument("--synthetic", action="store_true", help="requires synthetic=true in metadata and every snapshot")
    args = parser.parse_args(argv)
    try:
        # Capture each input exactly once. Parsing and hashes describe these
        # same immutable bytes even if a source file changes during calculation.
        payloads = {name: path.read_bytes() for name, path in
                    (("metadata", args.metadata), ("snapshots", args.snapshots), ("prices", args.prices))}
        metadata = json.loads(payloads["metadata"].decode("utf-8-sig"))
        snapshots = json.loads(payloads["snapshots"].decode("utf-8-sig"))
        if not isinstance(snapshots, list):
            raise ValidationError("snapshots JSON must be an array")
        with StringIO(payloads["prices"].decode("utf-8-sig"), newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != ["ts_ms", "open", "high", "low", "close"]:
                raise ValidationError("CSV columns must be exactly ts_ms,open,high,low,close")
            rows = list(reader)
            for row in rows:
                row["ts_ms"] = int(row["ts_ms"])
        report = run_research(metadata, snapshots, rows, synthetic=args.synthetic)
        report["input_sha256"] = {name: hashlib.sha256(payload).hexdigest()
                                  for name, payload in payloads.items()}
        # Exclusive create preserves prior artifacts; the CLI never contacts any service.
        with args.output.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        print(json.dumps({key: report[key] for key in ("version", "synthetic", "snapshot_count", "entered_count", "closed_count", "pending_count", "reason_counts")}, ensure_ascii=False))
        return 0
    except (ValidationError, OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
