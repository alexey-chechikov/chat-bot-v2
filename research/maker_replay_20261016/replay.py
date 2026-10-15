"""Offline received-order sensitivity model. Standard library, no network/client imports."""
from __future__ import annotations

import bisect
from collections import Counter, defaultdict
import csv
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
import hashlib
import heapq
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INPUTS = (
    ("five_minutes", "market_capture_001", "59fba38efbee9626f3b321b192712403d58ecc4481b8fa1a3b0f442dfc83a5be", None),
    ("old_chunk_common_prefix", "capture_24h_001/chunk_000001", "7453c5d2214def73705b108e2fb0015a50f630537ad4e47693f88042b4183af0", 5283),
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_frames(path, expected_sha=None, cutoff=None):
    if expected_sha and sha(path) != expected_sha:
        raise ValueError("frozen input hash mismatch")
    result = []
    previous_mono = None
    with Path(path).open(encoding="utf-8") as handle:
        for expected, line in enumerate(handle, 1):
            row = json.loads(line)
            if row["receive_seq"] != expected:
                raise ValueError("receive sequence gap")
            if cutoff is not None and expected >= cutoff:
                break
            mono = row["recv_monotonic_ns"]
            if previous_mono is not None and mono < previous_mono:
                raise ValueError("monotonic reversal")
            previous_mono = mono
            result.append({"seq": expected, "mono": mono, "raw": json.loads(row["raw_json"]), "session": row["session"]})
    if not result or len({x["session"] for x in result}) != 1:
        raise ValueError("empty or multiple-session input")
    origin = result[0]["mono"]
    for row in result:
        row["ms"] = (row["mono"] - origin) / 1e6
    return result


@dataclass
class Order:
    oid: int
    kind: str
    side: str
    price: float
    remaining: float
    requested_ms: float
    acknowledged: bool = False
    cancel_pending: bool = False
    queue: float | None = None
    ack_seq: int = -1
    ack_ms: float = -1
    filled: float = 0


class Engine:
    EPS = 1e-10

    def __init__(self, end_ms, delay_ms=100, queue_factor=1, min_levels=15, fee_bp=1,
                 quote_usd=30, max_age_ms=900000):
        self.end = end_ms
        self.delay = delay_ms
        self.queue_factor = queue_factor
        self.min_levels = min_levels
        self.fee = fee_bp / 10000
        self.quote_usd = quote_usd
        self.max_age = max_age_ms
        self.eod_trigger = max(0, end_ms - 2 * delay_ms)
        self.now = 0.0
        self.seq = 0
        self.events = []
        self.serial = 0
        self.next_oid = 0
        self.order = None
        self.position = 0.0
        self.entry_price = None
        self.episode = None
        self.episodes = []
        self.ledger = []
        self.fills = []
        self.books = {"b": {}, "a": {}}
        self.book_valid = False
        self.last_book_ms = None
        self.last_u = None
        self.mid_history = []
        self.seen = {}
        self.liquidating = False
        self.force_pending = False
        self.force_attempted = False
        self.closing = False
        self.last_quote_ms = -math.inf
        self.exit_reason = ""
        self.coverage = Counter()
        self.schedule(self.eod_trigger, "eod")

    def schedule(self, at, kind, oid=None):
        self.serial += 1
        heapq.heappush(self.events, (at, self.serial, kind, oid))

    def log(self, event, **fields):
        self.ledger.append({"ms": round(self.now, 3), "seq": self.seq,
                            "episode": self.episode["id"] if self.episode else None,
                            "event": event, "position": self.position, **fields})

    def fresh(self):
        return self.book_valid and self.last_book_ms is not None and self.now - self.last_book_ms <= 1000

    def submit(self, kind, price, qty):
        if self.order is not None or qty <= self.EPS:
            raise ValueError("overlapping own order or nonpositive qty")
        self.next_oid += 1
        self.order = Order(self.next_oid, kind, "buy" if kind == "entry" else "sell", price, qty, self.now)
        self.log("submit", oid=self.next_oid, kind=kind, side=self.order.side, price=price, qty=qty)
        self.schedule(self.now + self.delay, "ack", self.next_oid)
        if kind == "entry":
            self.schedule(self.now + 5000, "ttl", self.next_oid)

    def cancel(self, reason):
        if self.order is not None and not self.order.cancel_pending:
            self.order.cancel_pending = True
            self.log("cancel_request", oid=self.order.oid, reason=reason)
            self.schedule(self.now + self.delay, "cancel_ack", self.order.oid)

    def liquidate(self, reason):
        self.liquidating = True
        self.exit_reason = self.exit_reason or reason
        if self.episode:
            if reason == "end_of_data":
                self.episode["truncated"] = True
            if not any(x["reason"] == reason for x in self.episode["risk_triggers"]):
                self.episode["risk_triggers"].append({"reason": reason, "ms": self.now, "inventory": self.position})
                self.log("liquidation_trigger", reason=reason)
        self.cancel(reason)

    def check_risk(self):
        """Run on every frame/state transition, including a newly created position.

        A missing new book does not suspend the stale guard. Inventory and own
        pending orders remain live until their modeled terminal events; a forced
        exit without a valid price will explicitly retain unresolved inventory.
        """
        if not self.episode or (self.position <= self.EPS and self.order is None):
            return
        if not self.fresh():
            self.episode["coverage_uncertain"] = True
            if not self.liquidating:
                self.liquidate("stale_or_invalid_book")
            return
        if self.liquidating or self.position <= self.EPS:
            return
        if max(self.books["b"]) <= self.entry_price * (1 - 25 / 10000):
            self.liquidate("stop")
        elif self.now - self.episode["first_fill_ms"] >= self.max_age:
            self.liquidate("max_age")

    def advance(self, until, inclusive):
        while self.events and (self.events[0][0] <= until if inclusive else self.events[0][0] < until):
            at, _, kind, oid = heapq.heappop(self.events)
            self.now = at
            order = self.order
            if kind == "eod":
                self.closing = True
                if self.episode:
                    self.liquidate("end_of_data")
            elif kind == "max_age":
                if self.episode and oid == self.episode["id"] and self.position > self.EPS:
                    self.liquidate("max_age")
            elif kind == "force":
                self.force_pending = False
                self.force_attempted = True
                self.forced_exit()
            elif order is not None and order.oid == oid:
                if kind == "ack":
                    marketable = self.fresh() and (order.price >= min(self.books["a"]) if order.side == "buy" else order.price <= max(self.books["b"]))
                    if not self.fresh() or marketable:
                        self.log("postonly_reject", oid=oid, reason="stale_or_invalid" if not self.fresh() else "marketable")
                        self.order = None
                        if order.kind == "exit":
                            self.liquidate("tp_rejected")
                    else:
                        order.acknowledged = True
                        order.ack_seq, order.ack_ms = self.seq, self.now
                        visible = self.books["b" if order.side == "buy" else "a"].get(order.price)
                        order.queue = visible * self.queue_factor if visible is not None else None
                        if order.queue is None:
                            self.episode["unknown_queue_orders"] += 1
                        self.log("virtual_ack", oid=oid, queue=order.queue, queue_unknown=order.queue is None)
                elif kind == "ttl" and order.kind == "entry":
                    self.cancel("ttl")
                elif kind == "cancel_ack":
                    self.log("virtual_cancel_ack", oid=oid, unfilled=order.remaining)
                    self.order = None
            self.reconcile(allow_open=False)
        self.now = until

    def book(self, raw):
        try:
            if raw["e"] == "depthSnapshot":
                self.books = {"b": {}, "a": {}}
            elif self.last_u is None or int(raw["U"]) != self.last_u:
                raise ValueError("sequence_gap")
            for side in ("b", "a"):
                for p, q in raw.get(side, []):
                    p, q = float(p), float(q)
                    if not math.isfinite(p) or not math.isfinite(q) or p <= 0 or q < 0:
                        raise ValueError("nonfinite_or_invalid_book")
                    if q:
                        self.books[side][p] = q
                    else:
                        self.books[side].pop(p, None)
            self.last_u = int(raw["u"])
            if min(len(x) for x in self.books.values()) < self.min_levels:
                raise ValueError("insufficient_depth")
            if max(self.books["b"]) >= min(self.books["a"]):
                raise ValueError("crossed_book")
            if self.last_book_ms is not None and self.now - self.last_book_ms > 1000:
                self.coverage["stale_depth_intervals"] += 1
                if self.episode:
                    self.episode["coverage_uncertain"] = True
                    self.liquidate("stale_depth")
            self.book_valid = True
            self.coverage["valid_depth_frames"] += 1
            if raw["e"] == "depthSnapshot":
                self.coverage["depth_snapshot_frames"] += 1
            self.last_book_ms = self.now
            bid, ask = max(self.books["b"]), min(self.books["a"])
            self.mid_history.append((self.now, (bid + ask) / 2))
        except (ValueError, KeyError, TypeError) as exc:
            self.book_valid = False
            self.coverage["invalid_depth_frames"] += 1
            self.log("coverage_invalid", reason=str(exc))
            if self.episode:
                self.episode["coverage_uncertain"] = True
                self.liquidate("coverage_gap")

    def trade(self, raw):
        volume = defaultdict(float)
        for t in raw.get("d", []):
            self.coverage["received_trade_rows"] += 1
            if raw["e"] == "tradeSnapshot":
                self.coverage["received_snapshot_trade_rows"] += 1
            tid = str(t.get("t", ""))
            signature = (t.get("T"), t.get("p"), t.get("q"), t.get("m"))
            if not tid or tid == "None" or type(t.get("m")) is not bool:
                self.coverage["invalid_trade_rows"] += 1
                if self.episode:
                    self.episode["coverage_uncertain"] = True
                    self.liquidate("unknown_trade_side_or_id")
                continue
            if tid in self.seen:
                if signature != self.seen[tid]:
                    self.coverage["conflicting_trade_ids"] += 1
                    if self.episode:
                        self.episode["coverage_uncertain"] = True
                        self.liquidate("conflicting_trade_id")
                continue
            self.seen[tid] = signature
            p, q = float(t["p"]), float(t["q"])
            if not math.isfinite(p) or not math.isfinite(q) or p <= 0 or q <= 0:
                raise ValueError("invalid trade amount")
            if raw["e"] == "tradeSnapshot":
                self.coverage["bootstrap_trade_rows"] += 1
                continue
            self.coverage["unique_live_trade_rows"] += 1
            volume[(p, t["m"])] += q
        order = self.order
        if not order or not order.acknowledged or self.seq <= order.ack_seq or not self.fresh():
            return
        if order.queue is None:
            self.coverage["frames_with_unmodelled_unknown_queue"] += 1
            return
        available = volume[(order.price, order.side == "buy")]
        ahead = min(order.queue, available)
        order.queue -= ahead
        available -= ahead
        amount = min(order.remaining, available)
        if amount > self.EPS:
            order.remaining -= amount
            order.filled += amount
            if order.remaining <= self.EPS:
                self.order = None
            # Mark terminal/remaining order state before the fill's immediate
            # risk check; a fully filled entry needs no spurious cancel ACK.
            self.fill(order.side, order.price, amount, "passive", order.oid)

    def fill(self, side, price, qty, liquidity, oid=None):
        if side == "sell" and qty > self.position + self.EPS:
            raise ValueError("reduceOnly overfill")
        value = price * qty
        fee = value * self.fee
        if side == "buy":
            if self.position <= self.EPS:
                self.entry_price = price
                self.episode["first_fill_ms"] = self.now
                self.schedule(self.now + self.max_age, "max_age", self.episode["id"])
            self.position += qty
        else:
            self.position -= qty
            if abs(self.position) <= self.EPS:
                self.position = 0.0
        self.episode["cash_price"] += value * (1 if side == "sell" else -1)
        self.episode["fees"] += fee
        self.episode["turnover"] += value
        self.episode["max_inventory"] = max(self.episode["max_inventory"], self.position)
        self.episode["fill_count"] += 1
        if liquidity == "passive":
            self.episode["ambiguous_passive_fills"] += 1
        self.fills.append({"ms": self.now, "episode": self.episode["id"], "side": side, "price": price,
                           "qty": qty, "liquidity": liquidity, "fee": fee,
                           "receipt_after_virtual_ack_only": liquidity == "passive"})
        self.log("fill", oid=oid, side=side, price=price, qty=qty, liquidity=liquidity, fee=fee)
        self.check_risk()

    def forced_exit(self):
        if self.order is not None:
            raise ValueError("forced exit before own order terminal")
        if not self.fresh():
            self.episode["unresolved"] = True
            self.log("forced_exit_unresolved", reason="no_fresh_book")
            return
        # One market-order scenario walking observed bids; market impact is unknown.
        remaining = self.position
        for price, displayed in sorted(self.books["b"].items(), reverse=True):
            qty = min(remaining, displayed)
            if qty > self.EPS:
                self.fill("sell", price, qty, "forced_taker")
                remaining -= qty
            if remaining <= self.EPS:
                break
        if remaining > self.EPS:
            self.episode["unresolved"] = True
            self.log("forced_exit_unresolved", reason="insufficient_visible_depth")

    def reconcile(self, allow_open):
        self.check_risk()
        if self.order and self.order.kind == "entry" and self.order.filled > self.EPS:
            self.cancel("first_partial")
        if self.liquidating:
            if self.order:
                self.cancel(self.exit_reason)
                return
            if self.position > self.EPS:
                if not self.force_pending and not self.force_attempted:
                    self.force_pending = True
                    self.schedule(self.now + self.delay, "force")
                return
        if self.order is None and self.position > self.EPS:
            target = float((Decimal(str(self.entry_price)) * Decimal("1.0008") / Decimal("0.01")).to_integral_value(rounding=ROUND_CEILING) * Decimal("0.01"))
            self.submit("exit", target, self.position)
            return
        if self.order is None and self.position <= self.EPS and self.episode:
            ep = self.episode
            ep["end_ms"] = self.now
            ep["reason"] = self.exit_reason or ("tp_filled" if ep["fill_count"] else "no_fill")
            ep["net_scenario"] = ep["cash_price"] - ep["fees"]
            ep["scenario_cost_per_M"] = -ep["net_scenario"] / ep["turnover"] * 1e6 if ep["turnover"] else None
            ep["complete_before_boundary"] = not ep["truncated"] and not ep["unresolved"]
            ep["full_15min_followup_available"] = ep["first_fill_ms"] is not None and ep["first_fill_ms"] + self.max_age <= self.end
            self.episodes.append(ep)
            self.log("episode_terminal", reason=ep["reason"])
            self.episode = None
            self.liquidating = False
            self.force_attempted = False
            self.exit_reason = ""
        if not allow_open or self.episode or self.closing or self.now >= self.eod_trigger or self.now - self.last_quote_ms < 5000 or not self.fresh():
            return
        bid, ask = max(self.books["b"]), min(self.books["a"])
        if (ask - bid) / ((ask + bid) / 2) * 10000 > 3:
            return
        self.episode = {"id": len(self.episodes) + 1, "start_ms": self.now, "first_fill_ms": None,
                        "cash_price": 0.0, "fees": 0.0, "turnover": 0.0, "max_inventory": 0.0,
                        "fill_count": 0, "ambiguous_passive_fills": 0, "unknown_queue_orders": 0,
                        "coverage_uncertain": False, "truncated": False, "unresolved": False, "risk_triggers": []}
        self.last_quote_ms = self.now
        self.submit("entry", bid, self.quote_usd / bid)

    def frame(self, frame):
        self.advance(frame["ms"], inclusive=False)
        self.seq = frame["seq"]
        self.check_risk()
        raw = frame["raw"]
        if raw.get("s") == "ETHUSDT":
            self.coverage["eth_frames"] += 1
            if raw.get("e") in ("depth", "depthSnapshot"):
                self.book(raw)
            elif raw.get("e") in ("trade", "tradeSnapshot"):
                self.trade(raw)
        # A single received frame is fully consumed before virtual ACK or strategy action.
        self.advance(frame["ms"], inclusive=True)
        self.reconcile(allow_open=True)

    def finish(self):
        self.advance(self.end, inclusive=True)
        if self.episode:
            ep = self.episode
            ep.update({"end_ms": self.end, "reason": "unresolved_boundary", "truncated": True, "unresolved": True,
                       "net_scenario": None, "scenario_cost_per_M": None, "complete_before_boundary": False,
                       "full_15min_followup_available": False, "remaining_inventory": self.position})
            self.episodes.append(ep)
            self.episode = None
        times = [x[0] for x in self.mid_history]
        for fill in self.fills:
            sign = 1 if fill["side"] == "buy" else -1
            for seconds in (1, 5, 30, 60):
                at = fill["ms"] + seconds * 1000
                ix = bisect.bisect_right(times, at) - 1
                available = at <= self.end and ix >= 0 and at - times[ix] <= 1000
                fill[f"received_mid_markout_{seconds}s_bp"] = sign * (self.mid_history[ix][1] - fill["price"]) / fill["price"] * 10000 if available else None
        return self.summary()

    def summary(self):
        result = {"status": "sensitivity_model_only_not_actual_execution", "delay_ms": self.delay,
                  "displayed_queue_factor": self.queue_factor, "duration_s": self.end / 1000,
                  "coverage": dict(self.coverage), "remaining_inventory": self.position,
                  "episodes": len(self.episodes), "episodes_with_fills": sum(e["fill_count"] > 0 for e in self.episodes),
                  "truncated_episodes": sum(e["truncated"] for e in self.episodes),
                  "unresolved_episodes": sum(e["unresolved"] for e in self.episodes),
                  "unknown_queue_orders": sum(e["unknown_queue_orders"] for e in self.episodes),
                  "full_15min_followup_episodes": sum(e["full_15min_followup_available"] for e in self.episodes),
                  "passive_fills_with_unresolved_engine_ack_causality": sum(e["ambiguous_passive_fills"] for e in self.episodes),
                  "historical_quote_filters": "unknown; continuous quantity and assumed price tick",
                  "raw_m_direction_status": "inferred from reviewed recorder, not independently verified",
                  "actual_cost_per_M": None}
        for name, selected in (("closed_before_boundary", [e for e in self.episodes if e["complete_before_boundary"]]),
                               ("truncated", [e for e in self.episodes if e["truncated"]])):
            turnover = sum(e["turnover"] for e in selected)
            known = all(not e["unresolved"] for e in selected)
            net = sum(e["net_scenario"] for e in selected) if known else None
            result[name] = {"episodes": len(selected), "modeled_turnover": turnover, "modeled_net_after_assumed_fee": net,
                            "closed_filled_episodes": sum(e["fill_count"] > 0 and not e["unresolved"] for e in selected),
                            "modeled_price_pnl": sum(e["cash_price"] for e in selected) if known else None,
                            "assumed_fees": sum(e["fees"] for e in selected), "assumed_funding": 0.0, "assumed_rebate": 0.0,
                            "conditional_scenario_cost_per_M": -net / turnover * 1e6 if known and turnover else None}
        return result


def write_csv(path, rows):
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys or ["event"])
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in row.items()})


def main():
    summaries = []
    for name, rel, expected, cutoff in INPUTS:
        path = ROOT.parent / "weex_public_capture_20261015" / rel / "ordered_public.jsonl"
        frames = read_frames(path, expected, cutoff)
        for delay in (100, 500, 1000):
            for queue in (0, 1):
                run = Engine(frames[-1]["ms"], delay_ms=delay, queue_factor=queue)
                for frame in frames:
                    run.frame(frame)
                summary = run.finish()
                stem = f"{name}_d{delay}_q{queue}"
                summary.update({"capture": name, "accepted_frames": len(frames), "last_receive_seq": frames[-1]["seq"],
                                "source_full_sha256": expected, "cutoff_exclusive": cutoff, "output_stem": stem})
                write_csv(ROOT / f"{stem}_ledger.csv", run.ledger)
                write_csv(ROOT / f"{stem}_fills.csv", run.fills)
                write_csv(ROOT / f"{stem}_episodes.csv", run.episodes)
                summaries.append(summary)
    report = {"schema_version": 1, "scope": "offline public received-order sensitivity only", "actual_cost_per_M": None,
              "source_code_sha256": sha(__file__), "assumptions_sha256": sha(ROOT / "ASSUMPTIONS.md"), "scenarios": summaries}
    (ROOT / "scenario_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Offline maker sensitivity: 16 October 2026", "", "**Not actual fills, actual cost/M, or expected profit.** Frozen assumptions: ASSUMPTIONS.md. Fee 1 bp per modeled leg, zero funding assumption; historical filters and queue/latency are uncalibrated.", "", "| Capture | Delay ms | Queue factor | Filled episodes | Truncated | Unknown queue orders | Complete-scenario cost/M | Truncated-scenario cost/M |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    def fmt(value):
        return "n/a" if value is None else f"{value:.2f}"
    for s in summaries:
        lines.append(f"| {s['capture']} | {s['delay_ms']} | {s['displayed_queue_factor']} | {s['episodes_with_fills']} | {s['truncated_episodes']} | {s['unknown_queue_orders']} | {fmt(s['closed_before_boundary']['conditional_scenario_cost_per_M'])} | {fmt(s['truncated']['conditional_scenario_cost_per_M'])} |")
    lines.extend(["", "The two inputs are about five and twelve minutes; no filled episode has full 15-minute follow-up. Boundary closes are separated, and unavailable markout horizons are blank. Zero fills means no modeled executed turnover, not zero cost. Unknown TP queues are censored with a no-modeled-passive-fill policy, not assumed empty.", "", "Risk guards are checked on every received frame, state reconciliation and fill, including first position creation. A stale held position initiates cancellation even without another book frame. A late fill already below the current fresh stop initiates risk liquidation instead of placing TP. Unpriceable exits retain unresolved inventory. See test_replay.py and qa.json for verification; risk_guard_revision.json records changes from the pre-fix run.", "", "All passive fills are ambiguous with respect to real engine ACK ordering. Trade batches are atomic; no L2 shrink grants queue progress; same-price volume is consumed once. Scenarios are neither estimates nor mathematical bounds on actual fill probability or actual economic results.", "", "Files: scenario_report.json; per-scenario *_ledger.csv, *_fills.csv and *_episodes.csv. Replay is reproducible with `python -B research/maker_replay_20261016/replay.py`; tests with `python -B -m unittest discover -s research/maker_replay_20261016 -p test_replay.py -v`."])
    (ROOT / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"scenario_runs": len(summaries), "scope": report["scope"], "actual_cost_per_M": None}))


if __name__ == "__main__":
    main()
