"""LPX-A0 pure-offline reference kernel; no market adapter or end-to-end runner.

All public execution paths verify the immutable registration before doing work.
Only the CLI's invented demonstration creates scores. No market data are read.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import random
from collections import defaultdict

MINUTE = 60_000
FIVE_MIN = 5 * MINUTE
DAY = 24 * 60 * MINUTE
HORIZON = 240
SIDES = ("LONG", "SHORT")
LEV = (10, 25, 50, 100)
HALF_WIDTH = Decimal("0.0025")
TOLERANCE = Decimal("0.000000001")
EPSILON = Decimal("0.05")
EVENT_SCHEMA = "binance_usdm_force_order_snapshot_v1"
PROTOCOL_SHA256 = "cc2c39b252910bf91a2d50e724c88853fbbfa30fc2e0441c4a62a5ddf389c4ea"
MODEL_SHA256 = "8c01da241ce7ef72027491ef6a4e1443e613697332d990171069607729d2c554"
AMENDMENT_SHA256 = "9cf7437036b658d2c79271a9d39f8992772bf8325588a21a5b9c206b73836062"
AMENDMENT_002_SHA256 = "932d04381f612abda769723ce8119a2f4a8e5a21b7a1417679fb2d87424547c9"


class IntegrityError(ValueError):
    """Invalid normalized input, mutation, parameter change or state invariant."""


class NotAssessable(ValueError):
    """Known missing coverage or unavailable historical information."""


def decimal(value):
    if isinstance(value, bool):
        raise IntegrityError("boolean is not a market number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise IntegrityError("invalid numeric field") from exc
    if not result.is_finite():
        raise IntegrityError("nonfinite numeric field")
    return result


def integer(value):
    if type(value) is not int or value < 0:
        raise IntegrityError("timestamp/count must be a nonnegative integer")
    return value


def verify_registration(root=None):
    root = Path(root) if root else Path(__file__).resolve().parent
    reg = json.loads((root / "PREREGISTRATION.json").read_bytes())
    if reg.get("schema") != "lpx-a0-preregistration-v1":
        raise IntegrityError("unknown preregistration schema")
    expected = {"PROTOCOL.md": PROTOCOL_SHA256, "MODEL.md": MODEL_SHA256}
    indexed = {item["file"]: item for item in reg.get("files", [])}
    for name, sha in expected.items():
        body = (root / name).read_bytes()
        actual = hashlib.sha256(body).hexdigest()
        if actual != sha or indexed.get(name, {}).get("sha256") != sha or indexed[name]["bytes"] != len(body):
            raise IntegrityError(f"frozen document changed: {name}")
    parameters = {"primary_feature_lag_minutes": 5, "cohort_lifetime_hours": 24,
                  "weights": [.25]*4, "bootstrap_seed": 20261018, "placebos": 199,
                  "leverages": list(LEV), "epsilon": .05, "bootstrap_resamples": 10000,
                  "outcome_minutes": 240, "lag_sensitivity_minutes": 30}
    if reg.get("parameters") != parameters:
        raise IntegrityError("registration parameters differ from A0 kernel")
    for number, frozen_sha in (("001",AMENDMENT_SHA256),("002",AMENDMENT_002_SHA256)):
        amendment = (root / f"AMENDMENT_{number}.md").read_bytes()
        amendment_reg = json.loads((root / f"AMENDMENT_{number}_REGISTRATION.json").read_bytes())
        if (hashlib.sha256(amendment).hexdigest() != frozen_sha or
            amendment_reg.get("sha256") != frozen_sha or amendment_reg.get("bytes") != len(amendment) or
            amendment_reg.get("schema") != "lpx-a0-amendment-registration-v1"):
            raise IntegrityError(f"amendment {number} changed or unregistered")
    return {"verified": True, "files": expected,
            "amendment_001_sha256":AMENDMENT_SHA256,
            "amendment_002_sha256":AMENDMENT_002_SHA256,
            "registration_sha256": hashlib.sha256((root / "PREREGISTRATION.json").read_bytes()).hexdigest()}


@dataclass(frozen=True)
class FeatureBar:
    start_ms: int
    end_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    base_volume: Decimal
    quote_volume: Decimal
    oi_quantity: Decimal
    oi_unit: str
    received_at_ms: int | None = None

    @property
    def vwap(self):
        return decimal(self.quote_volume) / decimal(self.base_volume)


def validate_bar(bar):
    integer(bar.start_ms); integer(bar.end_ms)
    if bar.start_ms % FIVE_MIN or bar.end_ms != bar.start_ms + FIVE_MIN:
        raise IntegrityError("feature is not an exact closed UTC 5m bar")
    prices = [decimal(getattr(bar, field)) for field in ("open", "high", "low", "close")]
    o, h, l, c = prices
    if min(prices) <= 0 or l > min(o, c) or h < max(o, c) or l > h:
        raise IntegrityError("bad OHLC")
    if decimal(bar.base_volume) <= 0 or decimal(bar.quote_volume) <= 0:
        raise IntegrityError("nonpositive VWAP volume")
    if not l <= bar.vwap <= h:
        raise IntegrityError("VWAP outside OHLC")
    if decimal(bar.oi_quantity) < 0:
        raise IntegrityError("negative OI")
    if not isinstance(bar.oi_unit, str) or not bar.oi_unit.strip():
        raise IntegrityError("missing native quantity unit")
    if bar.received_at_ms is not None:
        integer(bar.received_at_ms)
        if bar.received_at_ms < bar.end_ms:
            raise IntegrityError("known closed-bar receipt precedes its end")


@dataclass(frozen=True)
class Cohort:
    side: str
    birth_end_ms: int
    level: Decimal
    mass: Decimal


def validate_cohort(cohort):
    if cohort.side not in SIDES:
        raise IntegrityError("unknown cohort side")
    integer(cohort.birth_end_ms)
    if decimal(cohort.level) <= 0 or decimal(cohort.mass) < 0:
        raise IntegrityError("invalid cohort level/mass")


def newborns(end_ms, vwap, mass):
    result = []
    for side in SIDES:
        sign = -1 if side == "LONG" else 1
        for leverage in LEV:
            result.append(Cohort(side, end_ms, vwap * (1 + Decimal(sign)/leverage), mass/4))
    return result


class ProxyState:
    """Mutable feature-prefix state. Snapshots contain only immutable copies."""

    def __init__(self):
        verify_registration()
        self._clear()

    def _clear(self):
        self.unknown = {side: Decimal(0) for side in SIDES}
        self.oi_cohorts = []
        self.price_cohorts = []
        self.quantity = Decimal(0)
        self.unit = None
        self.last_end_ms = None
        self.last_close = None
        self.first_start_ms = None
        self.contiguous_bars = 0

    @property
    def warm(self):
        return self.first_start_ms is not None and self.last_end_ms - self.first_start_ms >= DAY

    def check_identities(self):
        bound = TOLERANCE * max(Decimal(1), self.quantity)
        for side in SIDES:
            if self.unknown[side] < 0:
                raise IntegrityError("negative unknown mass")
            for cohort in self.oi_cohorts:
                validate_cohort(cohort)
            total = self.unknown[side] + sum((c.mass for c in self.oi_cohorts if c.side == side), Decimal(0))
            if abs(total - self.quantity) > bound:
                raise IntegrityError(f"per-side native OI identity failed: {side}")

    def _retire(self, cohorts, bar, transfer):
        retained, reasons = [], {"touch_only": Decimal(0), "expiry_only": Decimal(0), "touch_and_expiry": Decimal(0)}
        for cohort in cohorts:
            # AMENDMENT_001: previous-end == current-start is already born.
            old = cohort.birth_end_ms <= bar.start_ms
            touch = old and ((cohort.side == "LONG" and decimal(bar.low) <= cohort.level) or
                             (cohort.side == "SHORT" and decimal(bar.high) >= cohort.level))
            expired = bar.end_ms - cohort.birth_end_ms >= DAY
            if touch or expired:
                reason = "touch_and_expiry" if touch and expired else "touch_only" if touch else "expiry_only"
                reasons[reason] += cohort.mass
                if transfer:
                    self.unknown[cohort.side] += cohort.mass
            elif cohort.mass > 0:
                retained.append(cohort)
        return retained, reasons

    def add_bar(self, bar):
        try:
            validate_bar(bar)
        except (IntegrityError, AttributeError, TypeError):
            self._clear()
            raise
        reset = None
        if self.last_end_ms is not None:
            self.check_identities()
            if bar.end_ms <= self.last_end_ms:
                self._clear()
                raise IntegrityError("duplicate/conflicting/nonchronological feature time")
            if bar.start_ms != self.last_end_ms:
                reset = "missing_5m_grid"
            elif bar.oi_unit != self.unit:
                reset = "quantity_unit_changed"
            if reset:
                self._clear()
        quantity = decimal(bar.oi_quantity)
        if self.last_end_ms is None:
            self.quantity = quantity
            self.unknown = {side: quantity for side in SIDES}
            self.first_start_ms = bar.start_ms
            self.unit = bar.oi_unit
            retirement, price_retirement = {}, {}
        else:
            self.oi_cohorts, retirement = self._retire(self.oi_cohorts, bar, True)
            self.price_cohorts, price_retirement = self._retire(self.price_cohorts, bar, False)
            if quantity < self.quantity:
                factor = quantity / self.quantity
                self.unknown = {side: value * factor for side, value in self.unknown.items()}
                self.oi_cohorts = [replace(c, mass=c.mass*factor) for c in self.oi_cohorts if c.mass*factor > 0]
            elif quantity > self.quantity:
                self.oi_cohorts.extend(newborns(bar.end_ms, bar.vwap, quantity-self.quantity))
            self.price_cohorts.extend(newborns(bar.end_ms, bar.vwap, Decimal(1)))
            self.quantity = quantity
        self.last_end_ms, self.last_close = bar.end_ms, decimal(bar.close)
        self.contiguous_bars += 1
        self.check_identities()
        return {"status": "ACCEPTED", "reset_reason": reset, "contiguous_bars": self.contiguous_bars,
                "warm": self.warm, "retired_mass_by_disjoint_reason": {k: str(v) for k,v in retirement.items()},
                "price_retired_mass_by_disjoint_reason": {k: str(v) for k,v in price_retirement.items()}}


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    anchor_ms: int
    feature_end_ms: int
    lag_minutes: int
    reference_price: Decimal
    oi_unit: str
    oi_quantity: Decimal
    unknown_by_side: tuple[Decimal, Decimal]
    oi_cohorts: tuple[Cohort, ...]
    price_cohorts: tuple[Cohort, ...]
    contiguous_bars: int


def validate_snapshot(snapshot):
    verify_registration()
    integer(snapshot.anchor_ms); integer(snapshot.feature_end_ms)
    if not snapshot.snapshot_id or snapshot.anchor_ms % (6*60*MINUTE):
        raise IntegrityError("snapshot requires nonempty ID and fixed 00/06/12/18 UTC anchor")
    if snapshot.lag_minutes not in (5,30) or snapshot.feature_end_ms != snapshot.anchor_ms-snapshot.lag_minutes*MINUTE:
        raise IntegrityError("snapshot cutoff differs from frozen 5/30m lag")
    if decimal(snapshot.reference_price) <= 0 or decimal(snapshot.oi_quantity) < 0 or not snapshot.oi_unit:
        raise IntegrityError("invalid snapshot units/reference/OI")
    if snapshot.contiguous_bars < 288:
        raise NotAssessable("24h uninterrupted feature warm-up unavailable")
    for c in (*snapshot.oi_cohorts, *snapshot.price_cohorts):
        validate_cohort(c)
        if c.birth_end_ms > snapshot.feature_end_ms or snapshot.feature_end_ms-c.birth_end_ms >= DAY:
            raise IntegrityError("future or expired cohort in frozen feature state")
    for index, side in enumerate(SIDES):
        unknown = decimal(snapshot.unknown_by_side[index])
        total = unknown + sum((c.mass for c in snapshot.oi_cohorts if c.side == side), Decimal(0))
        if unknown < 0 or abs(total-snapshot.oi_quantity) > TOLERANCE*max(Decimal(1),snapshot.oi_quantity):
            raise IntegrityError("snapshot OI identity failed")


def freeze_prefix(bars, anchor_ms, snapshot_id, lag_minutes=5):
    integer(anchor_ms)
    if not snapshot_id or anchor_ms % (6*60*MINUTE) or lag_minutes not in (5,30):
        raise IntegrityError("nonregistered anchor, ID or lag")
    cutoff = anchor_ms - lag_minutes*MINUTE
    state = ProxyState()
    for bar in bars:
        if bar.end_ms > cutoff:
            continue  # Unadmitted future data cannot affect the frozen prefix.
        validate_bar(bar)
        if bar.received_at_ms is not None and max(bar.end_ms+lag_minutes*MINUTE,bar.received_at_ms) > anchor_ms:
            raise NotAssessable("known late feature receipt; unavailable bar is not skipped")
        state.add_bar(bar)
    if state.last_end_ms != cutoff:
        raise NotAssessable("exact latest admitted feature endpoint is missing")
    if not state.warm:
        raise NotAssessable("24h uninterrupted feature warm-up unavailable")
    snapshot = Snapshot(snapshot_id,anchor_ms,cutoff,lag_minutes,state.last_close,state.unit,state.quantity,
                        tuple(state.unknown[side] for side in SIDES),tuple(state.oi_cohorts),
                        tuple(state.price_cohorts),state.contiguous_bars)
    validate_snapshot(snapshot)
    return snapshot


def top_bands(snapshot):
    validate_snapshot(snapshot)
    result = {}
    for side in SIDES:
        own = [c for c in snapshot.oi_cohorts if c.side == side]
        candidates = []
        for j in range(-100,101):
            if j == 0 or (side == "LONG") != (j < 0):
                continue
            center = snapshot.reference_price*(1+Decimal(j)/1000)
            lower, upper = center*(1-HALF_WIDTH), center*(1+HALF_WIDTH)
            weight = sum((c.mass for c in own if lower <= c.level <= upper), Decimal(0))
            if weight > 0:
                candidates.append((weight,abs(j),center,lower,upper))
        selected = []
        for candidate in sorted(candidates,key=lambda c:(-c[0],c[1],c[2])):
            _,_,center,lower,upper = candidate
            if all(upper < old[3] or lower > old[4] for old in selected):
                selected.append(candidate)
                if len(selected) == 3:
                    break
        result[side] = [{"center":str(c),"lower":str(lo),"upper":str(hi),"mass":str(w)}
                        for w,_,c,lo,hi in selected]
    return result


def _age_bucket(age):
    if age < 0 or age >= DAY:
        raise IntegrityError("active cohort has invalid feature-state age")
    for index, limit in enumerate((60*MINUTE,4*60*MINUTE,12*60*MINUTE,DAY)):
        if age < limit:
            return index
    raise IntegrityError("age bucket unavailable")


def _distance_bucket(distance):
    for index, boundary in enumerate((Decimal(".5"),Decimal(1),Decimal(2),Decimal(3),Decimal(5))):
        if distance < boundary:
            return index
    return 5 if distance <= 10 else 6


def placebos(snapshot):
    validate_snapshot(snapshot)
    groups = defaultdict(list)
    for c in sorted(snapshot.oi_cohorts,key=lambda c:(SIDES.index(c.side),c.birth_end_ms,c.level,c.mass)):
        key = (SIDES.index(c.side),_age_bucket(snapshot.feature_end_ms-c.birth_end_ms),
               _distance_bucket(abs(c.level/snapshot.reference_price-1)*100))
        groups[key].append(c)
    ordered_keys = sorted(groups)
    singletons = sum(len(v) for v in groups.values() if len(v)==1)
    result = []
    for index in range(199):
        material = f"LPX-A0|20261018|{snapshot.snapshot_id}|{index}".encode()
        rng = random.Random(int(hashlib.sha256(material).hexdigest()[:16],16))
        shuffled = []
        for key in ordered_keys:
            originals = groups[key]
            masses = [c.mass for c in originals]
            rng.shuffle(masses)
            shuffled.extend(replace(c,mass=m) for c,m in zip(originals,masses))
        item = replace(snapshot,oi_cohorts=tuple(shuffled))
        validate_snapshot(item)
        result.append(item)
    return tuple(result), {"count":199,"replicate_indices":"0..198","age_reference":"feature_end_ms",
                           "group_order":"LONG then SHORT; ascending age bucket then distance bucket",
                           "singleton_cohort_fraction":singletons/len(snapshot.oi_cohorts) if snapshot.oi_cohorts else None,
                           "groups":len(groups)}


@dataclass(frozen=True)
class MarkMinute:
    start_ms: int
    end_ms: int
    close: Decimal
    price_kind: str
    closed: bool


@dataclass(frozen=True)
class Message:
    canonical_id: str
    event_ms: int
    position_side: str
    schema_id: str
    transport_sha256: str
    venue: str
    product: str
    symbol: str
    envelope_event_ms: int
    event_time_field: str = "o.T"
    received_at_ms: int | None = None


@dataclass(frozen=True)
class ConnectedSpan:
    start_ms: int
    end_ms: int
    schema_id: str
    connected: bool
    provenance_ref: str
    venue: str = "BINANCE"
    product: str = "USD-M"
    symbol: str = "BTCUSDT"
    channel: str = "forceOrder"


def _check_spans(spans, start, end):
    intervals = []
    for span in spans:
        integer(span.start_ms); integer(span.end_ms)
        if span.end_ms <= span.start_ms:
            raise NotAssessable("invalid feed coverage interval bounds")
        # A complete inventory may include unrelated disconnected intervals.
        # They cannot invalidate an already covered, disjoint target window.
        if span.end_ms <= start or span.start_ms >= end:
            continue
        if span.schema_id != EVENT_SCHEMA or span.connected is not True or span.end_ms <= span.start_ms:
            raise NotAssessable("unknown/invalid feed coverage provenance")
        if (not span.provenance_ref or (span.venue,span.product,span.symbol,span.channel) !=
            ("BINANCE","USD-M","BTCUSDT","forceOrder")):
            raise NotAssessable("coverage metadata do not identify the primary source")
        intervals.append((max(start,span.start_ms),min(end,span.end_ms)))
    # Check ALL intersecting metadata before accepting their union. A full
    # healthy span cannot hide a contradictory disconnected overlapping span.
    cursor = start
    for clipped_start,clipped_end in sorted(intervals):
        if clipped_end <= cursor:
            continue
        if clipped_start > cursor:
            raise NotAssessable("event feed connection coverage gap")
        cursor = max(cursor,clipped_end)
        if cursor >= end:
            break
    if cursor < end:
        raise NotAssessable("event feed connection coverage incomplete")


def _canonical_messages(messages, start, end, *, include_receive_audit=False):
    unique, transports, receive_audit, duplicate_count = {}, {}, {}, 0
    for event in messages:
        integer(event.event_ms)
        integer(event.envelope_event_ms)
        if event.received_at_ms is not None:
            integer(event.received_at_ms)
        if (not event.canonical_id or event.position_side not in SIDES or event.schema_id != EVENT_SCHEMA or
            (event.venue,event.product,event.symbol) != ("BINANCE","USD-M","BTCUSDT") or
            event.event_time_field != "o.T" or
            len(event.transport_sha256) != 64 or any(c not in "0123456789abcdef" for c in event.transport_sha256)):
            raise IntegrityError("unknown side/schema/venue/identity/provenance")
        if not start <= event.event_ms < end:
            raise IntegrityError("event outside supplied half-open outcome window")
        old = unique.get(event.canonical_id)
        if old is not None:
            # Actual local receipt belongs to audit metadata, never to the
            # canonical public envelope identity (AMENDMENT_002).
            if replace(old,received_at_ms=None) != replace(event,received_at_ms=None):
                raise IntegrityError("conflicting canonical message identity")
            duplicate_count += 1
            receive_audit[event.canonical_id]["copies"] += 1
            if event.received_at_ms is not None:
                receive_audit[event.canonical_id]["receipts"].append(event.received_at_ms)
            continue
        if (event.transport_sha256 in transports and
            replace(transports[event.transport_sha256],received_at_ms=None) != replace(event,received_at_ms=None)):
            raise IntegrityError("same canonical transport bytes have inconsistent normalization/ID")
        transports[event.transport_sha256] = event
        unique[event.canonical_id] = event
        receive_audit[event.canonical_id] = {"copies":1,"receipts":([] if event.received_at_ms is None else [event.received_at_ms])}
    audit = [{"canonical_id":identity,"transport_copies":item["copies"],"known_receipts":len(item["receipts"]),
              "receive_min_ms":min(item["receipts"]) if item["receipts"] else None,
              "receive_max_ms":max(item["receipts"]) if item["receipts"] else None}
             for identity,item in receive_audit.items()]
    basic = (tuple(unique.values()), duplicate_count)
    return (*basic,audit) if include_receive_audit else basic


def _path_weights(cohorts, closes):
    exposures = [sum((c.mass for c in cohorts if abs(x/c.level-1) <= HALF_WIDTH),Decimal(0)) for x in closes]
    total = sum(exposures,Decimal(0))
    if total == 0:
        return [1/HORIZON]*HORIZON, True
    weights = [float((1-EPSILON)*value/total+EPSILON/HORIZON) for value in exposures]
    return weights, False


def score(snapshot, mark_minutes, messages, connected_spans):
    """Conditional path log-score; declared provenance is checked, not inferred."""
    validate_snapshot(snapshot)
    if len(mark_minutes) != HORIZON:
        raise NotAssessable("primary requires exactly 240 MARK close slots")
    closes = []
    for index,row in enumerate(mark_minutes):
        start = snapshot.anchor_ms+index*MINUTE
        if (row.start_ms != start or row.end_ms != start+MINUTE or row.price_kind != "MARK" or
            row.closed is not True or decimal(row.close) <= 0):
            raise NotAssessable("missing/nonchronological/forming/non-MARK primary path")
        closes.append(decimal(row.close))
    end = snapshot.anchor_ms+HORIZON*MINUTE
    _check_spans(connected_spans,snapshot.anchor_ms,end)
    unique, duplicates, receive_audit = _canonical_messages(messages,snapshot.anchor_ms,end,include_receive_audit=True)
    sides, defined = {}, []
    for side in SIDES:
        counts = [0]*HORIZON
        for event in unique:
            if event.position_side == side:
                counts[(event.event_ms-snapshot.anchor_ms)//MINUTE] += 1
        oi_weights, uniform_oi = _path_weights([c for c in snapshot.oi_cohorts if c.side==side],closes)
        price_weights, uniform_price = _path_weights([c for c in snapshot.price_cohorts if c.side==side],closes)
        total = sum(counts)
        d = math.fsum((y/total)*math.log(a/b) for y,a,b in zip(counts,oi_weights,price_weights) if y) if total else None
        oi_uniform = math.fsum((y/total)*math.log(a*HORIZON) for y,a in zip(counts,oi_weights) if y) if total else None
        price_uniform = math.fsum((y/total)*math.log(a*HORIZON) for y,a in zip(counts,price_weights) if y) if total else None
        if d is not None:
            defined.append(side)
        sides[side] = {"messages":total,"minute_counts":counts,"d":d,"p_oi":oi_weights,"p_price":price_weights,
                       "descriptive_oi_vs_uniform":oi_uniform,"descriptive_price_vs_uniform":price_uniform,
                       "uniform_oi":uniform_oi,"uniform_price":uniform_price}
    return {"schema":"lpx-a0-anchor-reference-v1","snapshot_id":snapshot.snapshot_id,"anchor_ms":snapshot.anchor_ms,
            "feature_end_ms":snapshot.feature_end_ms,"lag_minutes":snapshot.lag_minutes,
            "status":"DEFINED" if defined else "NO_OBSERVED_MESSAGES",
            "anchor_d":math.fsum(sides[s]["d"] for s in defined)/len(defined) if defined else None,
            "defined_sides":defined,"sides":sides,"canonical_messages":len(unique),"transport_duplicates":duplicates,
            "message_receive_audit":receive_audit,
            "conditional_on_realized_path":True,"forecast_probability":False,"PnL":False,
            "protocol_sha256":PROTOCOL_SHA256,"model_sha256":MODEL_SHA256,
            "amendment_001_sha256":AMENDMENT_SHA256,"amendment_002_sha256":AMENDMENT_002_SHA256,
            "target_time_semantics":"adapter-declared o.T; envelope E preserved separately",
            "provenance_certified_by_kernel":False}


@dataclass(frozen=True)
class ScoreRecord:
    anchor_ms: int
    anchor_d: float | None
    long_messages: int
    short_messages: int


def _daily(records):
    days = defaultdict(list)
    for record in records:
        if record.anchor_d is not None:
            day = datetime.fromtimestamp(record.anchor_ms/1000,timezone.utc).date()
            days[day].append(record.anchor_d)
    return {day:math.fsum(values)/len(values) for day,values in days.items()}


def _mean(values):
    values = list(values)
    return math.fsum(values)/len(values) if values else None


def _percentile(values, q):
    ordered = sorted(values)
    index = (len(ordered)-1)*q
    lower,upper = math.floor(index),math.ceil(index)
    return ordered[lower]+(ordered[upper]-ordered[lower])*(index-lower)


def validation_summary(records):
    """Pure aggregate only: caller must supply the separately frozen validation set.

    Does not choose a split, load data, validate RUN_PLAN or compute lag/placebos.
    A positive interval never grants progression until those external diagnostics.
    """
    verify_registration()
    records = list(records)
    seen = set()
    for record in records:
        integer(record.anchor_ms); integer(record.long_messages); integer(record.short_messages)
        if record.anchor_ms % (6*60*MINUTE) or record.anchor_ms in seen:
            raise IntegrityError("off-grid or duplicate aggregate anchor")
        seen.add(record.anchor_ms)
        total = record.long_messages+record.short_messages
        if (record.anchor_d is None) != (total == 0):
            raise IntegrityError("no-message outcome must be undefined, not zero or omitted evidence")
        if record.anchor_d is not None and not math.isfinite(record.anchor_d):
            raise IntegrityError("nonfinite conditional score")
    day_values = _daily(records)
    all_days = {datetime.fromtimestamp(r.anchor_ms/1000,timezone.utc).date() for r in records}
    feed_weeks = {day-timedelta(days=day.weekday()) for day in all_days}
    weeks = sorted({day-timedelta(days=day.weekday()) for day in day_values})
    by_week = {week:[value for day,value in day_values.items() if day-timedelta(days=day.weekday())==week] for week in weeks}
    defined = sum(r.anchor_d is not None for r in records)
    positive_long = sum(r.long_messages>0 for r in records)
    positive_short = sum(r.short_messages>0 for r in records)
    unmet = [name for condition,name in ((len(weeks)<8,"calendar_week_clusters_lt_8"),
                                        (len(day_values)<40,"defined_UTC_days_lt_40"),
                                        (defined<100,"defined_anchors_lt_100"),
                                        (positive_long<30,"LONG_event_positive_anchors_lt_30"),
                                        (positive_short<30,"SHORT_event_positive_anchors_lt_30")) if condition]
    result = {"role":"validation_aggregate_reference_only","valid_anchors":len(records),"defined_anchors":defined,
              "no_message_anchors":len(records)-defined,"valid_days":len(all_days),"defined_days":len(day_values),
              "calendar_week_clusters":len(weeks),"feed_valid_calendar_weeks":len(feed_weeks),
              "score_defined_calendar_weeks":len(weeks),"LONG_event_positive_anchors":positive_long,
              "SHORT_event_positive_anchors":positive_short,"primary_mean":_mean(day_values.values()),
              "unmet_gates":unmet,"CI95":None,"verdict":"INCONCLUSIVE","bootstrap_resamples":10000,
              "bootstrap_seed":20261018,"bootstrap_undefined_resamples":0,
              "percentile_definition":"linear interpolation at (n-1)*q",
              "required_external_checks":["frozen_inventory_and_RUN_PLAN","30m_lag_sensitivity","199_placebos"],
              "estimand":"whole fixed OI construction, including positive-OI birth timing and OI masses",
              "order_permission":False,"CoinGlass_equivalence":False}
    # Largest episode deletion uses observed total messages, never result size.
    largest = sorted(records,key=lambda r:(-(r.long_messages+r.short_messages),r.anchor_ms))[:3]
    deleted_times = {r.anchor_ms for r in largest}
    survivors = [r for r in records if r.anchor_ms not in deleted_times]
    result["largest3_deleted_diagnostic"] = {"deleted_anchor_ms":[r.anchor_ms for r in largest],
        "defined_anchors":sum(r.anchor_d is not None for r in survivors),"daily_weighted_mean":_mean(_daily(survivors).values())}
    if unmet:
        return result
    rng = random.Random(20261018)
    distribution = []
    for _ in range(10000):
        sample = [value for _ in weeks for value in by_week[rng.choice(weeks)]]
        if sample:
            distribution.append(_mean(sample))
        else:
            result["bootstrap_undefined_resamples"] += 1
    if result["bootstrap_undefined_resamples"]:
        result["unmet_gates"].append("undefined_week_bootstrap_replicate")
        return result
    lower,upper = _percentile(distribution,.025),_percentile(distribution,.975)
    result["CI95"] = [lower,upper]
    if upper <= 0:
        result["verdict"] = "REJECT_FIXED_PROXY_INCREMENTAL_VALUE_ON_SPECIFIED_FEED_PERIOD"
    elif lower > 0:
        result["verdict"] = "POSITIVE_INTERVAL_REQUIRES_FIXED_DIAGNOSTICS_BEFORE_SEPARATE_NEXT_TEST"
    return result


def synthetic_demo():
    """Invented constant-price example: no input paths, no files, no real results."""
    anchor = 1790920800000
    bars = [FeatureBar(anchor-FIVE_MIN-(288-i)*FIVE_MIN,anchor-FIVE_MIN-(287-i)*FIVE_MIN,
                       Decimal(100),Decimal(100),Decimal(100),Decimal(100),Decimal(1),Decimal(100),
                       Decimal(100),"BTC") for i in range(288)]
    snap = freeze_prefix(bars,anchor,"INVENTED_ONLY",5)
    marks = [MarkMinute(anchor+i*MINUTE,anchor+(i+1)*MINUTE,Decimal(100),"MARK",True) for i in range(240)]
    result = score(snap,marks,[],[ConnectedSpan(anchor,anchor+240*MINUTE,EVENT_SCHEMA,True,"INVENTED_ONLY")])
    return {"synthetic":True,"market_data_loaded":False,"status":result["status"],"anchor_d":result["anchor_d"],
            "contiguous_bars":snap.contiguous_bars,"end_to_end_pipeline_ready":False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--verify-registration",action="store_true")
    modes.add_argument("--synthetic-demo",action="store_true")
    args = parser.parse_args(argv)
    verified = verify_registration()
    result = verified if args.verify_registration else {**synthetic_demo(),"registration":verified}
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))


if __name__ == "__main__":
    main()
