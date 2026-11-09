"""Research-only, fixed-quantity funding replay for the pinned BTC experiment.

Rates are decimal fractions (0.0001 = 0.01%), event/price times are UTC epoch
seconds, and a['t'] contains hourly CLOSE times. No order or account API is used.
See replay_cashflows.md for boundary conventions and unsupported-period status.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from types import MappingProxyType
import numpy as np
import pandas as pd

HOUR = 3600
FUNDING_INTERVAL = 8 * HOUR
# First observed Binance USDT-M funding in the pinned public history; this is a
# data-support boundary, not an assertion about an earlier contract launch time.
DEFAULT_SUPPORTED_FROM = 1568102400  # 2019-09-10 08:00 UTC
MAIN = {"над синей", "под синей"}


@dataclass(frozen=True)
class PreparedFunding:
    """Immutable, sorted funding input reusable across every trade and mode."""
    times: tuple
    rates: object
    attrs: object
    conflicts: tuple


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, set):
        return frozenset(_freeze(v) for v in value)
    return value


def prepare_funding(fund, *, attrs=None):
    """Normalize once; attrs overrides source metadata without modifying it.

    Example: prepare_funding(series, attrs={'supported_from_s': 1568102400,
    'expected_interval_s': 28800}). Pass the result as event_net's fund argument.
    """
    rates, source_attrs, conflicts = _funding_series(fund)
    merged = dict(source_attrs)
    merged.update(attrs or {})
    return PreparedFunding(tuple(sorted(rates)), MappingProxyType(dict(rates)),
                           _freeze(merged), tuple(conflicts))


def _funding_series(fund):
    """Normalize supported public source shapes, preserving attrs and NaNs."""
    if isinstance(fund, PreparedFunding):
        return fund.rates, fund.attrs, fund.conflicts
    attrs = dict(getattr(fund, "attrs", {}))
    if isinstance(fund, pd.Series):
        time, rate = fund.index.to_numpy(), fund.to_numpy()
    elif isinstance(fund, pd.DataFrame):
        pairs = (("fundingTime", "fundingRate"), ("ms", "rate"), ("t", "rate"), ("time", "rate"))
        tc, rc = next(((tc, rc) for tc, rc in pairs if tc in fund and rc in fund), (None, None))
        if tc is None:
            raise ValueError("Funding DataFrame needs (fundingTime,fundingRate), (ms,rate), or (t,rate)")
        time, rate = fund[tc].to_numpy(), fund[rc].to_numpy()
    elif isinstance(fund, dict) and "times" in fund:
        time = fund["times"]
        rate = np.asarray(fund["rates_pct"], float) / 100 if "rates_pct" in fund else fund["rates"]
        for key in ("expected_interval_s", "schedule_anchor_s", "supported_from_s", "venue"):
            if key in fund:
                attrs[key] = fund[key]
        attrs.update(fund.get("attrs", {}))
    elif fund is None:
        time, rate = [], []
    else:
        raise TypeError("fund must be a Series, public funding DataFrame, funding-record dict, or None")
    if isinstance(time, pd.DatetimeIndex) or np.issubdtype(np.asarray(time).dtype, np.datetime64):
        time = pd.DatetimeIndex(time).asi8.astype(float) / 1e9
    else:
        time = np.asarray(time, float)
    rate = np.asarray(rate, float)
    if len(time) != len(rate):
        raise ValueError("Funding times/rates differ in length")
    finite_time = np.isfinite(time)
    time, rate = time[finite_time], rate[finite_time]
    if len(time):
        magnitude = np.median(np.abs(time))
        time = time / (1e6 if magnitude > 1e14 else 1000 if magnitude > 1e11 else 1)
    time = (np.floor(time / 60) * 60).astype(np.int64)
    # Identical duplicated payments are a single observation. Conflicting or
    # nonfinite duplicates become unavailable rather than being silently summed.
    values = {}
    conflicts = []
    order = np.argsort(time, kind="stable")
    time, rate = time[order], rate[order]
    starts = np.r_[0, np.flatnonzero(np.diff(time)) + 1] if len(time) else np.array([], dtype=int)
    stops = np.r_[starts[1:], len(time)] if len(time) else np.array([], dtype=int)
    for left, right in zip(starts, stops):
        t, r = int(time[left]), rate[left:right]
        good = np.isfinite(r).all() and np.all(r == r[0])
        values[int(t)] = float(r[0]) if good else float("nan")
        if not good:
            conflicts.append(int(t))
    return values, attrs, conflicts


def _price(a, pay):
    """Use the exact same-clock hourly close; never forward/backward fill."""
    t = np.asarray(a["t"], np.int64)
    i = int(np.searchsorted(t, pay))
    if i == len(t) or t[i] != pay:
        return float("nan")
    px = float(a["c"][i])
    return px if np.isfinite(px) and px > 0 else float("nan")


def _leg_membership(pay, leg, end, target, mode):
    """0 absent, 1 present, None unresolved order within an intrabar interval."""
    initial = leg["initial"]
    if mode == "basis_bug" or initial:
        start = leg["entry_t"]
        if pay <= start:
            return 0
    elif mode == "old_event_clock":
        if pay <= leg["add_t"]:
            return 0
    else:
        # Funding precedes standing-order executions on the same bar OPEN.
        start, close = leg["add_t"] - HOUR, leg["add_t"]
        if pay <= max(start, leg["entry_t"]):
            return 0
        if pay < close:
            return None
    if mode in {"corrected", "basis_bug"} and target:
        if pay >= end:
            return 0
        if pay > end - HOUR:
            return None
    elif pay > end:
        return 0
    return 1


def event_net(e, a, fund, mode="corrected"):
    """Replay one CLOSED engine event with explicit funding support and bounds.

    net_no_funding copies e['res'] (already includes the engine's commissions).
    funding_cost_pct > 0 is a cost; short receipts are negative. The observed-only
    benchmark is retained even for unsupported/incomplete history, while the
    strict result is NaN whenever a rate, price, or event order is unresolved.

    Optional fund.attrs keys: expected_interval_s (default 8h), schedule_anchor_s
    (default UTC 00:00 grid), supported_from_s (default first observed BTC USDT-M
    funding), venue (e.g. Bitstamp). a may also specify venue. Synthetic tests can
    explicitly set supported_from_s=0 rather than pretending to be 2019 history.
    """
    if mode not in {"corrected", "old_event_clock", "basis_bug"}:
        raise ValueError(f"Unknown mode: {mode}")
    p = e["pos"]
    entry, end = int(p["entry_t"]), int(e["t"])
    if end < entry:
        raise ValueError("Exit precedes entry")
    side = int(p.get("side", e.get("side")))
    if side not in {-1, 1}:
        raise ValueError("Position side must be -1 or 1")
    tag = p.get("tag", e.get("tag"))
    weight = 1.0 if tag == "432" else float(p["w"])
    first_weight = weight * .5 if tag in MAIN else weight
    legs = [{"label": "initial", "initial": True, "entry_t": entry,
             "price": float(p["entry"]), "weight": first_weight}]
    if tag in MAIN and p.get("add_done", False):
        if p.get("add_t") is None or p.get("add_px") is None:
            raise ValueError("Completed add needs add_t and add_px")
        add_t = int(p["add_t"])
        if not entry <= add_t <= end:
            raise ValueError("Add timestamp lies outside the trade")
        legs.append({"label": "add", "initial": False, "entry_t": entry,
                     "add_t": add_t, "price": float(p["add_px"]), "weight": weight * .5})
    if any(not np.isfinite(x["price"]) or x["price"] <= 0 or not np.isfinite(x["weight"]) for x in legs):
        raise ValueError("Leg prices/weights must be finite, prices positive")
    target = str(e.get("why", "")).startswith("цель")
    rates, attrs, conflicts = _funding_series(fund)
    interval = int(attrs.get("expected_interval_s", FUNDING_INTERVAL))
    anchor = int(attrs.get("schedule_anchor_s", 0))
    if interval <= 0:
        raise ValueError("Expected funding interval must be positive")
    supported_from = int(attrs.get("supported_from_s", DEFAULT_SUPPORTED_FROM))
    venue = str(attrs.get("venue", a.get("venue", "Binance"))).lower()
    unsupported = venue == "bitstamp" or entry < supported_from
    # Both expected settlements and actually supplied off-schedule observations
    # matter. Missing expected rates must not silently become zero.
    first_expected = (entry - anchor) // interval * interval + anchor + interval
    expected = set(range(first_expected, end + 1, interval))
    if isinstance(fund, PreparedFunding):
        observed = set(fund.times[bisect_right(fund.times, entry):bisect_right(fund.times, end)])
    else:
        observed = {t for t in rates if entry < t <= end}
    candidates = sorted(expected | observed)
    missing, missing_prices, ambiguous, detail = [], [], [], []
    cost = lower = upper = 0.0
    for pay in candidates:
        memberships = [_leg_membership(pay, x, end, target, mode) for x in legs]
        if not any(x != 0 for x in memberships):
            continue
        r = rates.get(pay, float("nan"))
        if not np.isfinite(r):
            missing.append(pay)
            continue
        px = _price(a, pay)
        if not np.isfinite(px) and r != 0:
            missing_prices.append(pay)
        for leg, active in zip(legs, memberships):
            if active == 0:
                continue
            if active is None:
                ambiguous.append({"pay_t": pay, "leg": leg["label"]})
            if not np.isfinite(px) and r != 0:
                continue
            amount = 0.0 if r == 0 else side * leg["weight"] * 100 / leg["price"] * px * r
            if active is None:
                lower += min(0.0, amount)
                upper += max(0.0, amount)
            else:
                cost += amount
                lower += amount
                upper += amount
            detail.append({"pay_t": pay, "leg": leg["label"], "rate": r,
                           "spot_proxy_price": px, "funding_cost_pct": amount,
                           "membership": "uncertain" if active is None else "present"})
    history_complete = not missing and not unsupported
    complete = history_complete and not missing_prices and not ambiguous
    reasons = []
    if unsupported:
        reasons.append("unsupported_venue" if venue == "bitstamp" else "before_observed_funding_inception")
    if missing:
        reasons.append("missing_funding_records")
    if missing_prices:
        reasons.append("missing_same_clock_spot_proxy")
    if ambiguous:
        reasons.append("ambiguous_intrabar_payment_order")
    if conflicts:
        # Only relevant conflicting payments affect this trade's completeness.
        relevant = set(missing) & set(conflicts)
        if relevant:
            reasons.append("conflicting_or_nonfinite_duplicate_rates")
    bounds_available = not missing and not missing_prices and not unsupported
    net = float(e["res"])
    benchmark = net - cost
    return {"mode": mode, "net_no_funding": net, "funding_cost_pct": cost,
            "net_with_observed_funding": benchmark,
            "benchmark_net_with_observed_funding": benchmark,
            "net_with_funding_strict": benchmark if complete else float("nan"),
            "funding_complete": complete, "funding_history_complete": history_complete,
            "status": "complete_spot_proxy" if complete else ";".join(reasons),
            "funding_cost_lower_pct": lower if bounds_available else float("nan"),
            "funding_cost_upper_pct": upper if bounds_available else float("nan"),
            "net_with_funding_lower_pct": net - upper if bounds_available else float("nan"),
            "net_with_funding_upper_pct": net - lower if bounds_available else float("nan"),
            "missing_funding_times": missing, "missing_proxy_price_times": sorted(set(missing_prices)),
            "ambiguous_payments": ambiguous, "payments": detail,
            "funding_price_method": "same_clock_spot_hour_close_proxy_not_actual_mark",
            "clock_convention": "entry excludes same-time pay; standing orders after open pay; close exits after close pay"}
