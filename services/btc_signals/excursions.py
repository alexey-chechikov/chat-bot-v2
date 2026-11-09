"""Excursions bounded by execution, with explicit intrabar uncertainty.

Hourly closes give complete hourly extrema. A first-touch target gives only
partial knowledge of its exit bar: favorable excursion stops at execution;
the adverse extreme may have happened before or after it. Minute OHLC narrows
that uncertainty to the touching minute, and never claims tick-level order.
"""
from __future__ import annotations

import numpy as np

PATH_BOUND_FIELDS = {
    "MFE lower, ATR", "MFE upper, ATR", "MAE lower, ATR", "MAE upper, ATR",
    "MFE lower, %", "MFE upper, %", "MAE lower, %", "MAE upper, %",
    "качество пути", "разрешение выхода", "причина качества пути", "качество порядка ±1 ATR",
    "часов до MFE lower", "часов до MFE upper", "часов до MAE lower", "часов до MAE upper",
    "семантика времени экстремумов",
}


def _distance(side, entry, high, low):
    favorable = high - entry if side == 1 else entry - low
    adverse = entry - low if side == 1 else high - entry
    return max(float(favorable), 0.0), max(float(adverse), 0.0)


def _full(side, entry, high, low, at, span_h=1.0):
    f, a = _distance(side, entry, high, low)
    return (f, f, a, a, float(at), float(at - span_h))


def _touch(side, entry, exit_px, open_px, high, low, at, open_fill=False, span_h=1.0):
    favorable = max(float(side * (exit_px - entry)), 0.0)
    known_adverse = max(float(-side * (exit_px - entry)), 0.0)
    if np.isfinite(open_px):
        known_adverse = max(known_adverse, float(-side * (open_px - entry)))
    possible_adverse = known_adverse if open_fill else max(known_adverse, _distance(side, entry, high, low)[1])
    return (favorable, favorable, known_adverse, possible_adverse, float(at), float(at if open_fill else at - span_h))


def _first_order(parts, atr):
    if not parts:
        return 0.0, "exact"
    a = np.asarray(parts, float)
    if not np.isfinite(a[:, :4]).all():
        return None, "ambiguous"
    def first(column):
        hit = np.flatnonzero(a[:, column] >= atr)
        return int(hit[0]) if len(hit) else np.inf
    f_certain, f_possible, a_certain, a_possible = (first(k) for k in range(4))
    if f_possible == a_possible == np.inf:
        return 0.0, "exact"
    if f_certain < a_possible:
        return 1.0, "exact"
    if a_certain < f_possible:
        return -1.0, "exact"
    return None, "ambiguous"


def _minute_parts(execution, side, entry, exit_px, bar_start, bar_end, entry_time):
    """Return only observations up to first target hit; reject gaps before it."""
    try:
        ts, op, hi, lo, close = (np.asarray(execution[k], float) for k in ("t", "o", "h", "l", "c"))
    except (KeyError, TypeError, ValueError):
        return None, "invalid_minute_schema"
    arrays = (ts, op, hi, lo, close)
    if any(x.ndim != 1 or len(x) != len(ts) for x in arrays):
        return None, "invalid_minute_schema"
    sel = (ts >= bar_start) & (ts < bar_end)
    ts, op, hi, lo, close = (x[sel] for x in arrays)
    if not len(ts):
        return None, "missing_exit_hour_minutes"
    parts = []
    for k in range(len(ts)):
        if ts[k] != bar_start + 60 * k:
            return None, "minute_gap_before_execution"
        values = np.array([op[k], hi[k], lo[k], close[k]])
        if (not np.isfinite(values).all() or lo[k] > min(op[k], close[k]) or
                hi[k] < max(op[k], close[k]) or hi[k] < lo[k]):
            return None, "invalid_minute_ohlc"
        open_hit = side * (op[k] - exit_px) >= 0
        hit = hi[k] >= exit_px if side == 1 else lo[k] <= exit_px
        if open_hit or hit:
            at = (ts[k] + (0 if open_hit else 60) - entry_time) / 3600
            parts.append(_touch(side, entry, exit_px, op[k], hi[k], lo[k], at, open_hit, span_h=1 / 60))
            return parts, "minute_open" if open_hit else "minute_touch_bounds"
        parts.append(_full(side, entry, hi[k], lo[k], (ts[k] + 60 - entry_time) / 3600, span_h=1 / 60))
    return None, "minute_target_not_found"


def trade_path(a: dict, i0: int, i1: int, side: int, entry: float, exit_px: float,
               *, exit_mode: str = "close", execution: dict | None = None) -> dict:
    """Legacy path keys plus lower/upper bounds and a quality label.

    execution: optional minute OHLC, `t` is minute OPEN time in UTC seconds.
    It is consumed only for target exits. Missing/gapped minute tapes fall back
    to honest hourly bounds; they do not invent an exact execution path.
    """
    if exit_mode not in {"close", "target"}:
        raise ValueError("exit_mode must be close or target")
    if side not in (-1, 1) or not 0 <= i0 <= i1 < len(a["c"]):
        raise ValueError("invalid side or trade interval")
    entry, exit_px, atr = float(entry), float(exit_px), float(a["atr4"][i0])
    if not np.isfinite([entry, exit_px, atr]).all() or entry <= 0 or atr <= 0:
        raise ValueError("entry, exit and entry ATR must be finite and positive")
    t = np.asarray(a.get("t", np.arange(len(a["c"])) * 3600), float)
    entry_time = float(t[i0])
    high, low = np.asarray(a["h"], float), np.asarray(a["l"], float)
    parts, resolution, reason = [], "hour", "close_complete_bar"
    last_full = i1 + 1 if exit_mode == "close" else i1
    for i in range(i0 + 1, last_full):
        parts.append(_full(side, entry, high[i], low[i], (t[i] - entry_time) / 3600))
    if exit_mode == "target" and i1 > i0:
        op = float(a["o"][i1]) if "o" in a else np.nan
        open_fill = np.isfinite(op) and side * (op - exit_px) >= 0
        if open_fill:
            parts.append(_touch(side, entry, exit_px, op, high[i1], low[i1],
                                (t[i1] - 3600 - entry_time) / 3600, True))
            resolution, reason = "open", "target_filled_at_hour_open"
        else:
            minute, minute_reason = (None, "hour_target_bounds")
            if execution is not None:
                minute, minute_reason = _minute_parts(execution, side, entry, exit_px,
                                                      t[i1] - 3600, t[i1], entry_time)
            if minute is not None:
                parts.extend(minute)
                resolution, reason = "minute", minute_reason
            else:
                parts.append(_touch(side, entry, exit_px, op, high[i1], low[i1],
                                    (t[i1] - entry_time) / 3600))
                reason = minute_reason
    values = np.asarray(parts, float) if parts else np.zeros((0, 6))
    f_lo, f_hi, a_lo, a_hi = np.max(values[:, :4], axis=0) if len(parts) else np.zeros(4)
    mfe_known = bool(np.isclose(f_lo, f_hi, rtol=1e-12, atol=1e-12))
    mae_known = bool(np.isclose(a_lo, a_hi, rtol=1e-12, atol=1e-12))
    mfe, mae = float(f_lo) if mfe_known else None, float(a_lo) if mae_known else None
    first, first_quality = _first_order(parts, atr)
    quality = "exact" if mfe_known and mae_known and first_quality == "exact" else "ambiguous"
    fin = side * (exit_px - entry)
    out = {"MFE, %": mfe / entry * 100 if mfe is not None else None,
           "MAE, %": mae / entry * 100 if mae is not None else None,
           "MFE, ATR": mfe / atr if mfe is not None else None,
           "MAE, ATR": mae / atr if mae is not None else None,
           "часов до MFE": float(values[np.argmax(values[:, 0]), 4]) if len(parts) and mfe_known else (0.0 if not parts else None),
           "часов до MAE": float(values[np.argmax(values[:, 2]), 4]) if len(parts) and mae_known else (0.0 if not parts else None),
           "отдача, ATR": (mfe - fin) / atr if mfe is not None else None,
           "отдача, доля MFE": (mfe - fin) / mfe if mfe is not None and mfe > 0 else None,
           "сначала +1 ATR или −1 ATR": first, "часов в сделке": float((t[i1] - entry_time) / 3600),
           "качество пути": quality, "разрешение выхода": resolution,
           "причина качества пути": reason, "качество порядка ±1 ATR": first_quality,
           "семантика времени экстремумов": "bar_upper_bound_not_tick_time"}
    for kind, known, column in (("MFE", mfe_known, 0), ("MAE", mae_known, 2)):
        if known and len(parts):
            peak = int(np.argmax(values[:, column]))
            lower, upper = max(float(values[peak, 5]), 0.0), max(float(values[peak, 4]), 0.0)
        elif not parts:
            lower = upper = 0.0
        else:
            lower = upper = None
        out[f"часов до {kind} lower"], out[f"часов до {kind} upper"] = lower, upper
    for kind, lower, upper in (("MFE", f_lo, f_hi), ("MAE", a_lo, a_hi)):
        out[f"{kind} lower, ATR"], out[f"{kind} upper, ATR"] = float(lower / atr), float(upper / atr)
        out[f"{kind} lower, %"], out[f"{kind} upper, %"] = float(lower / entry * 100), float(upper / entry * 100)
    for w, name in ((24, "24ч"), (72, "72ч"), (168, "7д")):
        # Preserve the legacy capped-horizon meaning, explicitly documented in
        # the audit, using clock hours rather than a count of source rows.
        # A missing exact horizon cannot be replaced by a later observed price.
        horizon = entry_time + w * 3600
        if horizon >= t[i1]:
            px = exit_px
        else:
            j = int(np.searchsorted(t, horizon))
            px = float(a["c"][j]) if j < len(t) and t[j] == horizon else np.nan
        out[f"ход через {name}, %"] = side * (px / entry - 1) * 100 if np.isfinite(px) else None
    return out
